from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.db_requests import get_user, update_user_field
from app.utils.google_sheets import update_user_in_sheet

import asyncio
import re

from app.routers.registration_router import FACULTIES_KPI

router = Router()

KPI_GROUP_PATTERN = re.compile(
    r"^[А-ЯІЇЄҐа-яіїєґA-Za-z]{2,4}[-\u2014\u2013]?[а-яіїєґa-z]{0,2}\d{1,2}[а-яіїєґa-z]{0,2}$",
    re.IGNORECASE
)


class ProfileForm:
    pass


from aiogram.fsm.state import StatesGroup, State


class ProfileEditForm(StatesGroup):
    waiting_for_new_name = State()
    waiting_for_new_username = State()
    waiting_for_new_university = State()
    waiting_for_new_faculty = State()
    waiting_for_new_group = State()


@router.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    tg_id = callback.from_user.id

    user = await get_user(tg_id)
    if not user:
        await callback.message.answer("Профіль не знайдено. Спочатку зареєструйся.")
        await callback.answer()
        return

    text = (
        f"<b>ТВІЙ ПРОФІЛЬ</b>\n"
        f"───────────────\n"
        f"<b>ПІБ:</b> {user.name}\n"
        f"<b>Telegram:</b> {user.username}\n"
        f"<b>Університет:</b> {user.university}\n"
    )
    if user.faculty and user.faculty != "-":
        text += f"<b>Факультет:</b> {user.faculty}\n"
    if user.group_name and user.group_name != "-":
        text += f"<b>Група:</b> {user.group_name}\n"
        
    text += (
        f"───────────────\n"
        f"📅 <b>26 вересня</b>, <b>13:00</b>\n"
        f"📍 <b>КПІ ім. Ігоря Сікорського</b> (посилання на точку збору надамо пізніше)\n\n"
        f"💙 <b>Нагадуємо про актуальний збір:</b>\n"
        f"🔗 <a href='https://send.monobank.ua/jar/7utHDHzbHL'>Посилання на банку</a>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="Змінити дані", callback_data="prof_edit_menu")
    builder.button(text="Назад", callback_data="controller_hub_new")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), disable_web_page_preview=True)

    await callback.answer()


@router.callback_query(F.data == "prof_edit_menu")
async def edit_profile_menu(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Помилка: юзера не знайдено.")
        return

    is_kpi = "КПІ" in user.university.upper() or "СІКОРСЬКОГО" in user.university.upper()

    builder = InlineKeyboardBuilder()
    builder.button(text="ПІБ", callback_data="edit_prof_name")
    builder.button(text="Telegram", callback_data="edit_prof_username")
    builder.button(text="Університет", callback_data="edit_prof_university")
    
    if is_kpi:
        builder.button(text="Факультет", callback_data="edit_prof_faculty")
        builder.button(text="Група", callback_data="edit_prof_group")
        
    builder.button(text="Назад до профілю", callback_data="profile")
    
    if is_kpi:
        builder.adjust(2, 2, 1, 1)
    else:
        builder.adjust(2, 1, 1)

    await callback.message.edit_text(
        "<b>Що саме ти хочеш змінити?</b>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_prof_"))
async def start_edit_text_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_prof_", "")

    prompts = {
        "name":       "Введи нове ПІБ:\nПриклад: Шевченко Тарас Григорович",
        "username":   "Введи новий юзернейм у Telegram:\nПриклад: @username",
        "university": "Введи назву свого університету:\nПриклад: КПІ ім. Ігоря Сікорського",
        "faculty":    "Введи новий факультет або напрям:\nПриклад: ФІОТ",
        "group":      "Введи нову групу або курс:\nПриклад: ІП-55",
    }

    states = {
        "name":       ProfileEditForm.waiting_for_new_name,
        "username":   ProfileEditForm.waiting_for_new_username,
        "university": ProfileEditForm.waiting_for_new_university,
        "faculty":    ProfileEditForm.waiting_for_new_faculty,
        "group":      ProfileEditForm.waiting_for_new_group,
    }

    prompt = prompts.get(field)
    target_state = states.get(field)

    await state.set_state(target_state)

    builder = InlineKeyboardBuilder()
    
    if field == "faculty":
        user = await get_user(callback.from_user.id)
        if user and ("КПІ" in user.university.upper() or "СІКОРСЬКОГО" in user.university.upper()):
            for fac in FACULTIES_KPI:
                builder.button(text=fac, callback_data=f"prof_fac_{fac}")
            builder.button(text="Скасувати", callback_data="prof_edit_menu")
            builder.adjust(1)
            prompt = "Обери свій факультет:"
        else:
            builder.button(text="Скасувати", callback_data="prof_edit_menu")
            builder.adjust(1)
    else:
        builder.button(text="Скасувати", callback_data="prof_edit_menu")
        builder.adjust(1)

    new_msg = await callback.message.edit_text(prompt, reply_markup=builder.as_markup())
    await state.update_data(main_message_id=new_msg.message_id)
    await callback.answer()


@router.callback_query(ProfileEditForm.waiting_for_new_faculty, F.data.startswith("prof_fac_"))
async def process_prof_kpi_faculty_choice(callback: types.CallbackQuery, state: FSMContext):
    choice = callback.data.replace("prof_fac_", "")
    
    await update_user_field(callback.from_user.id, "faculty", choice)
    asyncio.create_task(update_user_in_sheet(tg_id=callback.from_user.id, field="faculty", new_value=choice))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутися в профіль", callback_data="profile")
    
    await callback.message.edit_text("✅ Дані успішно оновлено!", reply_markup=builder.as_markup())
    await state.clear()
    await callback.answer()


@router.message(ProfileEditForm.waiting_for_new_name, F.text)
@router.message(ProfileEditForm.waiting_for_new_username, F.text)
@router.message(ProfileEditForm.waiting_for_new_university, F.text)
@router.message(ProfileEditForm.waiting_for_new_faculty, F.text)
@router.message(ProfileEditForm.waiting_for_new_group, F.text)
async def save_text_field(message: types.Message, state: FSMContext):
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

    current_state = await state.get_state()

    state_to_field = {
        ProfileEditForm.waiting_for_new_name.state:       "name",
        ProfileEditForm.waiting_for_new_username.state:   "username",
        ProfileEditForm.waiting_for_new_university.state: "university",
        ProfileEditForm.waiting_for_new_faculty.state:    "faculty",
        ProfileEditForm.waiting_for_new_group.state:      "group_name",
    }
    field_to_update = state_to_field.get(current_state)
    input_text = message.text.strip()

    if field_to_update == "name":
        if len(input_text.split()) > 3:
            err_msg = await message.answer("❌ Будь ласка, введи ПІБ (не більше 3 слів).\nПриклад: Шевченко Тарас Григорович")
            await state.update_data(error_msg_id=err_msg.message_id)
            return

    # Нормалізуємо юзернейм
    if field_to_update == "username":
        if input_text.lower() != "немає" and not input_text.startswith("@"):
            input_text = f"@{input_text}"

    if field_to_update in ["faculty", "group_name"]:
        input_text = input_text.upper()
        
    if field_to_update == "group_name":
        user = await get_user(message.from_user.id)
        if user and "КПІ" in user.university.upper() and input_text != "-":
            if not KPI_GROUP_PATTERN.match(input_text):
                err_msg = await message.answer("❌ Некоректний формат групи. Введи у форматі, наприклад: ІП-55 або АС-з61мп")
                await state.update_data(error_msg_id=err_msg.message_id)
                return

    await update_user_field(message.from_user.id, field_to_update, input_text)

    asyncio.create_task(update_user_in_sheet(
        tg_id=message.from_user.id,
        field=field_to_update,
        new_value=input_text
    ))
    
    # Якщо змінили університет на не-КПІ, скидаємо факультет та групу
    if field_to_update == "university":
        if "КПІ" not in input_text.upper() and "СІКОРСЬКОГО" not in input_text.upper():
            await update_user_field(message.from_user.id, "faculty", "-")
            await update_user_field(message.from_user.id, "group_name", "-")
            asyncio.create_task(update_user_in_sheet(message.from_user.id, "faculty", "-"))
            asyncio.create_task(update_user_in_sheet(message.from_user.id, "group_name", "-"))

    data = await state.get_data()

    builder = InlineKeyboardBuilder()
    builder.button(text="Повернутися в профіль", callback_data="profile")
    
    main_message_id = data.get("main_message_id")
    if main_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_message_id,
                text="✅ Дані успішно оновлено!",
                reply_markup=builder.as_markup()
            )
        except Exception:
            await message.answer("✅ Дані успішно оновлено!", reply_markup=builder.as_markup())
    else:
        await message.answer("✅ Дані успішно оновлено!", reply_markup=builder.as_markup())
        
    await state.clear()
