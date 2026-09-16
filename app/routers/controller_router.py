from dotenv import load_dotenv

from aiogram import F
from aiogram.filters import Command
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

import app.utils.keyboards as kb
from app.db.db_requests import is_admin, get_user

from app.routers.admin_router import router as admin_router
from app.routers.registration_router import router as registration_router
from app.routers.profile_router import router as profile_router
from app.routers.faq_router import router as faq_router

load_dotenv()
router = Router()
router.include_routers(
    admin_router,
    registration_router,
    profile_router,
    faq_router,
)

EVENT_INFO = (
    "📅 <b>26 вересня</b>, <b>13:00</b>\n"
    "📍 <b>КПІ ім. Ігоря Сікорського</b> (посилання на точку збору надамо пізніше)\n\n"
    "💙 <b>Посилання на збір:</b> <a href='https://send.monobank.ua/jar/7utHDHzbHL'>Банка Monobank</a>"
)

WELCOME_TEXT = (
    "Привіт! Запрошуємо тебе на легендарну <b>Посвяту ФІОТ 2026😈</b>\n\n"
    "Це потужний захід, який обʼєднає цьогорічних першокурсників!\n\n"
    "На тебе чекають:\n"
    "🕵🏼‍♀️ Інтерактивний квест\n"
    "🎁 Благодійний розіграш\n\n"
    "📅 <b>26 вересня</b>\n"
    "📍 <b>КПІ ім.Ігоря Сікорського</b>"
)


async def safe_reply(message: types.Message, text: str, reply_markup=None):
    try:
        return await message.edit_text(text=text, reply_markup=reply_markup,
                                       parse_mode="HTML", disable_web_page_preview=True)
    except TelegramBadRequest:
        return await message.answer(text=text, reply_markup=reply_markup, parse_mode="HTML",
                                    disable_web_page_preview=True)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    is_user_admin = await is_admin(message.from_user.id)
    existing_user = await get_user(message.from_user.id)

    if is_user_admin:
        keyboard = kb.create_main_admin_keyboard()
        text = WELCOME_TEXT + (
            "\n\n───────────────\n"
            "🔐 Ти маєш права <b>Адміна</b>\nОбери дію:"
        )
    elif existing_user:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = (
            f"👋 Привіт, <b>{existing_user.name.split()[1] if len(existing_user.name.split()) > 1 else existing_user.name}</b>!\n"
            f"Ти вже зареєстрований на <b>Посвяту ФІОТ 2026</b> 🎉\n\n"
            f"{EVENT_INFO}"
        )
    else:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = WELCOME_TEXT + "\n\n<i>Ти не зареєстрований, натисни кнопку нижче, щоб зареєструватися!</i>"

    await message.reply(
        text=text,
        reply_markup=keyboard.as_markup()
    )


@router.callback_query(F.data.in_(["controller_hub", "controller_hub_new"]))
async def cmd_back_hub(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.clear()

    is_user_admin = await is_admin(callback.from_user.id)
    existing_user = await get_user(callback.from_user.id)

    if is_user_admin:
        keyboard = kb.create_main_admin_keyboard()
        text = WELCOME_TEXT + (
            "\n\n───────────────\n"
            "🔐 Ти маєш права <b>Адміна</b>\nОбери дію:"
        )
    elif existing_user:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = (
            f"👋 Привіт, <b>{existing_user.name.split()[1] if len(existing_user.name.split()) > 1 else existing_user.name}</b>!\n"
            f"Ти вже зареєстрований на <b>Посвяту ФІОТ 2026</b> 🎉\n\n"
            f"{EVENT_INFO}"
        )
    else:
        keyboard = kb.create_main_keyboard(is_existing_user=existing_user)
        text = WELCOME_TEXT + "\n\n<i>Ти не зареєстрований, натисни кнопку нижче, щоб зареєструватися!</i>"

    await safe_reply(
        message=callback.message,
        text=text,
        reply_markup=keyboard.as_markup()
    )
