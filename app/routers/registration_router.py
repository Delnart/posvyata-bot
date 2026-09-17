from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardRemove

from app.data.bot_state import global_state
from app.utils.google_sheets import add_user_to_sheet
from app.db.db_requests import add_user, get_user
import asyncio
import logging
import os
import re
from dotenv import load_dotenv

load_dotenv()
router = Router()

# Шаблон: 2-4 букви, тире/пробіл, до 2 букв (форма навчання: з, о, мп тощо), 1-2 цифри (курс), 1-2 цифри (номер групи)
# Приклади: ІП-55, АС-з61, МД-з61мп, ФЕ-п21
KPI_GROUP_PATTERN = re.compile(
    r"^[А-ЯІЇЄҐа-яіїєґA-Za-z]{2,4}[-\u2014\u2013]?[а-яіїєґa-z]{0,2}\d{1,2}[а-яіїєґa-z]{0,2}$",
    re.IGNORECASE
)


FACULTIES_KPI = [
    "ФІОТ"
]

MONO_JAR_URL = "https://send.monobank.ua/jar/7utHDHzbHL"

RULES_TEXT = (
    "📜 <b>Правила заходу</b>\n\n"
    "<b>Заборонено:</b>\n"
    "1) Діяти всупереч чинному законодавству України\n"
    "2) На території заходу заборонено перебувати зі зброєю, наркотичними речовинами та іншими забороненими предметами\n"
    "3) Приходити у стані алкогольного чи наркотичного сп'яніння\n"
    "4) Псувати майно закладу та Студради\n"
    "5) Палити та використовувати електронні сигарети у місцях скупчення людей та зон активностей\n"
    "6) Смітити\n"
    "7) Поводитись зневажливо або агресивно до інших\n\n"
    "<b>Важливо:</b> У разі повітряної тривоги необхідно негайно прямувати до найближчого укриття.\n\n"
    "<i>У разі порушення правил організатори залишають за собою право "
    "вивести людину з заходу без пояснення причин.</i>\n\n"
    "Ти погоджуєшся з правилами заходу?"
)


class RegisterForm(StatesGroup):
    entering_name = State()
    entering_username = State()
    entering_group = State()
    agreeing_to_rules = State()
    waiting_confirmation = State()


@router.callback_query(F.data == "registration")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if not global_state.get("registration_open", True):
        await callback.answer("На жаль, реєстрація вже закрита ❌", show_alert=True)
        return

    existing_user = await get_user(callback.from_user.id)

    if existing_user:
        builder = InlineKeyboardBuilder()
        builder.button(text="Перейти в профіль", callback_data="profile")
        builder.button(text="Головне меню", callback_data="controller_hub")
        builder.adjust(1)

        await callback.message.edit_text(
            "❌ <b>Ти вже зареєстрований на цей захід!</b>\n\n"
            "Якщо ти хочеш змінити свої дані, перейди у свій Профіль.",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    text = (
        "💙 <b>Вхід на захід вільний, але будемо дуже вдячні за донат на актуальний збір:</b>\n"
        f"🔗 <a href='{MONO_JAR_URL}'>Посилання на банку</a>\n\n"
        "───────────────\n"
        "Введи твоє ПІБ\n"
        "Приклад: Шевченко Тарас Григорович\n\n"
        "<i>*після підтвердження реєстрації дані можна змінити в профілі</i>"
    )

    try:
        new_msg = await callback.message.edit_text(text, disable_web_page_preview=True)
    except Exception:
        new_msg = await callback.message.answer(text, disable_web_page_preview=True)

    await state.update_data(main_message_id=new_msg.message_id)
    await state.set_state(RegisterForm.entering_name)
    await callback.answer()


# ==================== КРОК 1: ПІБ ====================

@router.message(RegisterForm.entering_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    err_msg_id = data.get("error_msg_id")
    if err_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, err_msg_id)
            await state.update_data(error_msg_id=None)
        except Exception:
            pass

    try:
        await message.delete()
    except Exception:
        pass

    name_text = message.text.strip()
    words = name_text.split()
    
    if len(words) > 3:
        err_msg = await message.answer("❌ Будь ласка, введи ПІБ (не більше 3 слів).\nПриклад: Шевченко Тарас Григорович")
        await state.update_data(error_msg_id=err_msg.message_id)
        return
        
    await state.update_data(name=name_text)
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    if message.from_user.username:
        # Юзернейм є — переходимо одразу до вводу групи
        await state.update_data(tg_username=f"@{message.from_user.username}")
        
        text = "Введи свою групу\nПриклад: ІП-55"
        
        if main_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text
                )
            except Exception:
                new_msg = await message.answer(text)
                await state.update_data(main_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(text)
            await state.update_data(main_message_id=new_msg.message_id)
            
        await state.set_state(RegisterForm.entering_group)
        
    else:
        # Юзернейму немає — запитуємо вручну
        text = (
            "Введи свій юзернейм (або телефон/інстаграм) для зв'язку\n"
            "Приклад: @username\n\n"
            "<i>(Оскільки у тебе не встановлений юзернейм в налаштуваннях Telegram, ми запитуємо контактні дані вручну. "
            "Якщо не хочеш нічого вказувати — введи «немає».)</i>"
        )
    
        if main_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=main_msg_id,
                    text=text
                )
            except Exception:
                new_msg = await message.answer(text)
                await state.update_data(main_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(text)
            await state.update_data(main_message_id=new_msg.message_id)
            
        await state.set_state(RegisterForm.entering_username)


# ==================== КРОК 2: ЮЗЕРНЕЙМ ====================

@router.message(RegisterForm.entering_username, F.text)
async def process_username_input(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    # Нормалізуємо — якщо не вказано @ і не "немає", додаємо
    if raw.lower() == "немає":
        tg_username = "немає"
    elif raw.startswith("@"):
        tg_username = raw
    else:
        tg_username = f"@{raw}"

    await state.update_data(tg_username=tg_username)
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    try:
        await message.delete()
    except Exception:
        pass

    text = "Введи свою групу\nПриклад: ІП-55"

    if main_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_msg_id,
                text=text
            )
        except Exception:
            new_msg = await message.answer(text)
            await state.update_data(main_message_id=new_msg.message_id)
    else:
        new_msg = await message.answer(text)
        await state.update_data(main_message_id=new_msg.message_id)
        
    await state.set_state(RegisterForm.entering_group)


# ==================== КРОК 3: ГРУПА ====================

@router.message(RegisterForm.entering_group, F.text)
async def process_group(message: types.Message, state: FSMContext):
    data = await state.get_data()
    err_msg_id = data.get("error_msg_id")
    if err_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, err_msg_id)
            await state.update_data(error_msg_id=None)
        except Exception:
            pass

    try:
        await message.delete()
    except Exception:
        pass

    group_text = message.text.strip().upper()
    
    if not KPI_GROUP_PATTERN.match(group_text):
        err_msg = await message.answer("❌ Некоректний формат групи. Введи у форматі, наприклад: ІП-55 або АС-з61мп")
        await state.update_data(error_msg_id=err_msg.message_id)
        return
        
    await state.update_data(
        group=group_text,
        university="КПІ ім. Ігоря Сікорського",
        faculty="ФІОТ"
    )
    await ask_for_rules(message, state)


# ==================== ПРАВИЛА ЗАХОДУ ====================


async def ask_for_rules(event: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")
    bot = event.bot
    chat_id = event.message.chat.id if isinstance(event, types.CallbackQuery) else event.chat.id

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Погоджуюсь з правилами", callback_data="agree_rules")

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(
            text=RULES_TEXT,
            reply_markup=builder.as_markup()
        )
    else:
        if main_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=main_msg_id,
                    text=RULES_TEXT,
                    reply_markup=builder.as_markup()
                )
            except Exception:
                new_msg = await event.answer(text=RULES_TEXT, reply_markup=builder.as_markup())
                await state.update_data(main_message_id=new_msg.message_id)

    await state.set_state(RegisterForm.agreeing_to_rules)


@router.callback_query(RegisterForm.agreeing_to_rules, F.data == "agree_rules")
async def process_agree_rules(callback: types.CallbackQuery, state: FSMContext):
    await show_confirmation_screen(callback, state)
    await callback.answer()


# ==================== ЕКРАН ПІДТВЕРДЖЕННЯ ====================

async def show_confirmation_screen(event: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get('name')
    tg_username = data.get('tg_username')
    group = data.get('group')

    confirmation_text = (
        f"<b>Перевір свої дані перед підтвердженням:</b>\n\n"
        f"<b>ПІБ:</b> {name}\n"
        f"<b>Telegram:</b> {tg_username}\n"
        f"<b>Група:</b> {group}\n\n"
        f"Усе правильно? Натисни підтвердити або скасуй реєстрацію."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Підтвердити реєстрацію", callback_data="confirm_registration")
    builder.button(text="❌ Скасувати", callback_data="cancel_registration")
    builder.adjust(1)

    await event.message.edit_text(text=confirmation_text, reply_markup=builder.as_markup())
    await state.set_state(RegisterForm.waiting_confirmation)


@router.callback_query(RegisterForm.waiting_confirmation, F.data == "confirm_registration")
async def confirm_registration(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get('name')
    tg_username = data.get('tg_username')
    university = data.get('university') or "КПІ ім. Ігоря Сікорського"
    faculty = data.get('faculty') or "ФІОТ"
    group = data.get('group')

    # Якщо юзер вводив юзернейм вручну — беремо його,
    # але також беремо реальний Telegram username для ідентифікації
    real_username = callback.from_user.username
    stored_username = tg_username if tg_username else (f"@{real_username}" if real_username else "немає")

    try:
        await add_user(
            tg_id=callback.from_user.id,
            username=stored_username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group,
        )

        asyncio.create_task(add_user_to_sheet(
            tg_id=callback.from_user.id,
            username=stored_username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group,
        ))

        builder = InlineKeyboardBuilder()
        builder.button(text="Мій профіль", callback_data="profile")
        builder.button(text="Головне меню", callback_data="controller_hub")
        builder.adjust(1)

        await callback.message.edit_text(
            text=(
                "🎉 <b>Реєстрацію підтверджено!</b>\n\n"
                "Твої дані збережено. Чекаємо тебе на <b>Посвяті</b>!\n\n"
                "📅 <b>Коли:</b> 26 вересня\n"
                "📍 <b>Де:</b> КПІ ім. Ігоря Сікорського\n\n"
                "Слідкуй за оновленнями та актуальною інформацією про захід на "
                "<a href='https://t.me/fice_time'>FICE Time 🇺🇦</a>\n\n"
                "💙 <b>Будемо вдячні за донат на підтримку збору:</b>\n"
                f"🔗 <a href='{MONO_JAR_URL}'>Посилання на банку</a>"
            ),
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )
        await state.clear()

    except Exception as e:
        logging.error(f"\033[31mПомилка БД під час реєстрації: {e}\033[0m")
        builder = InlineKeyboardBuilder()
        builder.button(text="Спробувати ще раз", callback_data="registration")

        await callback.message.edit_text(
            text="⚠️ Виникла помилка під час збереження даних. Спробуй ще раз.",
            reply_markup=builder.as_markup()
        )
        await state.clear()

    await callback.answer()


@router.callback_query(RegisterForm.waiting_confirmation, F.data == "cancel_registration")
async def cancel_registration(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутись в меню", callback_data="controller_hub")

    await callback.message.edit_text(
        text="❌ <b>Реєстрацію скасовано.</b> Твої дані не було збережено в системі.",
        reply_markup=builder.as_markup()
    )
    await state.clear()
    await callback.answer()
