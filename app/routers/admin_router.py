import os
import asyncio
from dotenv import load_dotenv

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.keyboards import create_main_admin_keyboard
from app.db.db_requests import (
    is_admin,
    get_all_users,
    get_users_by_identifiers,
    get_non_fiot_users,
    get_blocked_users,
    unblock_user,
)
from app.data.bot_state import global_state

load_dotenv()
SHEET_URL = os.getenv("SHEET_URL")
router = Router()


class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()         # Загальна розсилка всім
    waiting_for_recipients = State()      # Введення тегів або ID
    waiting_for_targeted_msg = State()    # Повідомлення для конкретних отримувачів


class AdminUnblock(StatesGroup):
    waiting_for_identifier = State()


@router.callback_query(F.data == "admin_stop_registration")
async def toggle_registration(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    global_state["registration_open"] = not global_state["registration_open"]

    status = "✅ ВІДКРИТА" if global_state["registration_open"] else "❌ ЗАКРИТА"
    text = (
        f"🔐 <b>Панель адміністратора</b>\n\n"
        f"Статус реєстрації: {status}\n"
        f"Оберіть дію:"
    )

    blocked = await get_blocked_users()
    keyboard = create_main_admin_keyboard(blocked_count=len(blocked))
    await callback.message.edit_text(text=text, reply_markup=keyboard.as_markup(), parse_mode="HTML")
    await callback.answer(f"Реєстрація тепер {status}")


# ==================== МЕНЮ ВИБОРУ РЕЖИМУ РОЗСИЛКИ ====================

@router.callback_query(F.data == "admin_write_participants")
async def choose_broadcast_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()

    non_fiot_users = await get_non_fiot_users()
    non_fiot_count = len(non_fiot_users)

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Всім зареєстрованим", callback_data="bc_mode_all")
    builder.button(text="🎯 Конкретним людям (@тег / ID)", callback_data="bc_mode_targeted")
    builder.button(text=f"👥 Не з нашого факультету ({non_fiot_count})", callback_data="bc_mode_non_fiot")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    text = (
        "📨 <b>Оберіть режим розсилки:</b>\n\n"
        "• <b>📢 Всім зареєстрованим</b> — розіслати повідомлення всій базі учасників.\n"
        "• <b>🎯 Конкретним людям</b> — розіслати за списком @username або числових Telegram ID.\n"
        f"• <b>👥 Не з нашого факультету</b> — швидка вибірка студентів не з ФІОТ (знайдено: {non_fiot_count} осіб)."
    )

    await callback.message.edit_text(text=text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== РЕЖИМ 1: ВСІМ УЧАСНИКАМ ====================

@router.callback_query(F.data == "bc_mode_all")
async def broadcast_all_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text(
        "📢 <b>Режим розсилки: Всім зареєстрованим</b>\n\n"
        "Надішліть повідомлення, яке хочете розіслати (текст, фото, відео або документ):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastAdmin.waiting_for_message)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    users = await get_all_users()
    if not users:
        await message.answer("У базі немає жодного зареєстрованого учасника.")
        await state.clear()
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    await message.answer(
        f"⏳ <b>Розсилку запущено у фоні</b> для {len(users)} учасників.\n"
        f"Ти можеш користуватись ботом, звіт надійде після завершення.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    asyncio.create_task(_run_broadcast(message.bot, message, users, message.from_user.id))
    await state.clear()


async def _run_broadcast(bot: Bot, message: types.Message, users: list, admin_id: int):
    success_count = 0
    fail_count = 0
    for user in users:
        try:
            await message.send_copy(chat_id=user.telegram_id)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Загальну розсилку завершено!</b>\n\n"
                f"• Доставлено: <b>{success_count}</b>\n"
                f"• Не доставлено: <b>{fail_count}</b>\n"
                f"• Всього учасників: <b>{len(users)}</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ==================== РЕЖИМ 2: КОНКРЕТНИМ ЛЮДЯМ (@ТЕГ / ID) ====================

@router.callback_query(F.data == "bc_mode_targeted")
async def broadcast_targeted_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text(
        "🎯 <b>Розсилка конкретним людям</b>\n\n"
        "Введіть список отримувачів через кому, пробіл або з нового рядка.\n"
        "Можна вказувати <b>@username</b> або числовий <b>Telegram ID</b>.\n\n"
        "<i>Приклад:</i>\n"
        "<code>@ivan_ivanov, @petrenko, 123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastAdmin.waiting_for_recipients)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_recipients)
async def process_recipients_input(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    raw_text = message.text or ""
    import re
    tokens = [t.strip() for t in re.split(r"[\s,;]+", raw_text) if t.strip()]

    if not tokens:
        await message.answer("❌ Будь ласка, введіть хоча б один @тег або Telegram ID.")
        return

    found_users, not_found = await get_users_by_identifiers(tokens)

    # Якщо введено ID, яких немає в базі, але це числа — дозволяємо пряме відправлення
    extra_direct_ids = []
    unresolved_tokens = []
    for nf in not_found:
        if nf.isdigit():
            extra_direct_ids.append(int(nf))
        else:
            unresolved_tokens.append(nf)

    target_user_ids = [u.telegram_id for u in found_users] + extra_direct_ids

    if not target_user_ids:
        builder = InlineKeyboardBuilder()
        builder.button(text="Спробувати ще раз", callback_data="bc_mode_targeted")
        builder.button(text="Скасувати", callback_data="admin_write_participants")
        builder.adjust(1)

        await message.answer(
            "❌ <b>Жодного отримувача не знайдено в базі!</b>\n\n"
            f"Перевірте введені дані: {', '.join(tokens)}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return

    await state.update_data(target_user_ids=target_user_ids)

    lines = [f"🎯 <b>Знайдено отримувачів: {len(target_user_ids)}</b>\n"]
    for u in found_users[:15]:
        uname = f" ({u.username})" if u.username else ""
        grp = f" [{u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")
    if len(found_users) > 15:
        lines.append(f"<i>...та ще {len(found_users) - 15} осіб</i>")

    for did in extra_direct_ids:
        lines.append(f"• Прямий ID: <code>{did}</code> (не в базі)")

    if unresolved_tokens:
        lines.append(f"\n⚠️ <b>Не знайдено в базі ({len(unresolved_tokens)}):</b> {', '.join(unresolved_tokens)}")

    lines.append("\n✏️ <b>Тепер надішліть повідомлення для розсилки</b> (текст, фото, відео тощо):")

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(BroadcastAdmin.waiting_for_targeted_msg)


# ==================== РЕЖИМ 3: НЕ З ФІОТ ====================

@router.callback_query(F.data == "bc_mode_non_fiot")
async def broadcast_non_fiot_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    non_fiot_users = await get_non_fiot_users()
    if not non_fiot_users:
        await callback.answer("У базі немає користувачів не з ФІОТ 🎉", show_alert=True)
        return

    target_user_ids = [u.telegram_id for u in non_fiot_users]
    await state.update_data(target_user_ids=target_user_ids)

    lines = [f"👥 <b>Отримувачі не з ФІОТ: {len(non_fiot_users)} осіб</b>\n"]
    for u in non_fiot_users[:15]:
        uname = f" ({u.username})" if u.username else ""
        grp = f" [група: {u.group_name}]" if u.group_name else ""
        lines.append(f"• <b>{u.name}</b>{uname}{grp}")
    if len(non_fiot_users) > 15:
        lines.append(f"<i>...та ще {len(non_fiot_users) - 15} осіб</i>")

    lines.append("\n✏️ <b>Надішліть повідомлення, яке отримають ці користувачі:</b>")

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_write_participants")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(BroadcastAdmin.waiting_for_targeted_msg)
    await callback.answer()


@router.message(BroadcastAdmin.waiting_for_targeted_msg)
async def process_targeted_broadcast_message(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    target_user_ids = data.get("target_user_ids", [])
    if not target_user_ids:
        await message.answer("❌ Список отримувачів порожній.")
        await state.clear()
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    await message.answer(
        f"⏳ <b>Розсилку запущено у фоні</b> для {len(target_user_ids)} вибраних отримувачів.\n"
        f"Ти можеш користуватись ботом, звіт надійде після завершення.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    asyncio.create_task(_run_targeted_broadcast(message.bot, message, target_user_ids, message.from_user.id))
    await state.clear()


async def _run_targeted_broadcast(bot: Bot, message: types.Message, target_ids: list[int], admin_id: int):
    success_count = 0
    fail_count = 0
    for uid in target_ids:
        try:
            await message.send_copy(chat_id=uid)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Таргетовану розсилку завершено!</b>\n\n"
                f"• Успішно доставлено: <b>{success_count}</b>\n"
                f"• Не вдалося доставити: <b>{fail_count}</b> (можливо, користувач заблокував бота)\n"
                f"• Всього отримувачів: <b>{len(target_ids)}</b>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ==================== УПРАВЛІННЯ ЗАБЛОКОВАНИМИ ====================

@router.callback_query(F.data == "admin_view_blocked")
async def view_blocked_users(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    await state.clear()
    blocked = await get_blocked_users()

    builder = InlineKeyboardBuilder()

    if not blocked:
        builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
        await callback.message.edit_text(
            "🚫 <b>Список заблокованих порожній</b>\n\n"
            "Наразі немає користувачів, заблокованих за спробу реєстрації з іншого факультету.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    lines = [f"🚫 <b>Заблоковані користувачі ({len(blocked)} осіб):</b>\n"]
    for i, b in enumerate(blocked[:15], 1):
        uname = f" (@{b.username.lstrip('@')})" if b.username else ""
        grp = f" | Група: <b>{b.attempted_group}</b>" if b.attempted_group else ""
        lines.append(f"{i}. <b>{b.name}</b>{uname}\n   ID: <code>{b.telegram_id}</code>{grp}\n   Причина: <i>{b.reason}</i>")

    if len(blocked) > 15:
        lines.append(f"\n<i>...та ще {len(blocked) - 15} осіб</i>")

    # Якщо заблокованих небагато (до 6) — даємо кнопки швидкого розблокування
    if len(blocked) <= 6:
        for b in blocked:
            label = f"🔓 {b.name[:18]}"
            builder.button(text=label, callback_data=f"admin_quick_unblock_{b.telegram_id}")

    builder.button(text="🔓 Розблокувати за @тегом чи ID", callback_data="admin_unblock_prompt")
    builder.button(text="🔙 Назад у панель", callback_data="controller_hub_new")
    builder.adjust(1)

    await callback.message.edit_text("\n\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_quick_unblock_"))
async def quick_unblock_user_handler(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    tg_id_str = callback.data.replace("admin_quick_unblock_", "")
    success, msg, unblocked_id = await unblock_user(tg_id_str)

    if success and unblocked_id:
        try:
            await callback.bot.send_message(
                chat_id=unblocked_id,
                text=(
                    "🎉 <b>Твій акаунт розблоковано адміністратором!</b>\n\n"
                    "Тепер ти можеш зареєструватися на захід. "
                    "Будь ласка, вказуй правильну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "Натисни /start або перейди в головне меню для реєстрації."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 До списку заблокованих", callback_data="admin_view_blocked")
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")
    builder.adjust(1)

    await callback.message.edit_text(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer("Розблоковано!")


@router.callback_query(F.data == "admin_unblock_prompt")
async def unblock_prompt_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="admin_view_blocked")

    await callback.message.edit_text(
        "🔓 <b>Розблокування користувача</b>\n\n"
        "Введіть <b>@username</b> або числовий <b>Telegram ID</b> користувача, якого потрібно розблокувати:\n\n"
        "<i>Приклад:</i>\n"
        "<code>@shevchenko</code> або <code>123456789</code>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(AdminUnblock.waiting_for_identifier)
    await callback.answer()


@router.message(AdminUnblock.waiting_for_identifier)
async def process_unblock_identifier(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return

    identifier = (message.text or "").strip()
    if not identifier:
        await message.answer("❌ Будь ласка, введіть @username або Telegram ID.")
        return

    success, reply_msg, unblocked_id = await unblock_user(identifier)

    if success and unblocked_id:
        try:
            await message.bot.send_message(
                chat_id=unblocked_id,
                text=(
                    "🎉 <b>Твій акаунт розблоковано адміністратором!</b>\n\n"
                    "Тепер ти можеш зареєструватися на захід. "
                    "Будь ласка, вказуй правильну групу ФІОТ (наприклад: <b>ІП-55</b>).\n\n"
                    "Натисни /start або перейди в головне меню для реєстрації."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 До списку заблокованих", callback_data="admin_view_blocked")
    builder.button(text="🔙 У панель адміна", callback_data="controller_hub_new")
    builder.adjust(1)

    await message.answer(reply_msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()




