import os
import asyncio
from dotenv import load_dotenv

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.keyboards import create_main_admin_keyboard
from app.db.db_requests import is_admin, get_all_users
from app.data.bot_state import global_state

load_dotenv()
SHEET_URL = os.getenv("SHEET_URL")
router = Router()


class BroadcastAdmin(StatesGroup):
    waiting_for_message = State()


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

    keyboard = create_main_admin_keyboard()
    await callback.message.edit_text(text=text, reply_markup=keyboard.as_markup(), parse_mode="HTML")
    await callback.answer(f"Реєстрація тепер {status}")


@router.callback_query(F.data == "admin_write_participants")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Скасувати", callback_data="controller_hub_new")

    await callback.message.edit_text(
        "📝 <b>Режим розсилки (Всім зареєстрованим)</b>\n\n"
        "Надішліть повідомлення, яке хочете розіслати (це може бути текст, фото, відео або документ):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BroadcastAdmin.waiting_for_message)


async def _run_broadcast(bot: Bot, message: types.Message, users: list, admin_id: int):
    success_count = 0
    for user in users:
        try:
            await message.send_copy(chat_id=user.telegram_id)
            success_count += 1
            await asyncio.sleep(0.05)  # Захист від лімітів спаму Telegram
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в панель", callback_data="controller_hub_new")
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=f"✅ <b>Розсилку завершено!</b>\nДоставлено: {success_count} з {len(users)}.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


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



