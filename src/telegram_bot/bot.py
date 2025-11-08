import asyncio
import logging
import os
from datetime import datetime, timezone

import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# OpenAI (async)
from openai import AsyncOpenAI, APIConnectionError, APIError, RateLimitError

# ------------- ENV -------------
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print(TELEGRAM_BOT_TOKEN)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("DB_PATH", "tg_events.sqlite")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-o4-mini")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in .env")

# ------------- LOGGING -------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tg-bot")

# ------------- AI CLIENT -------------
oaiclient = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ------------- STATES -------------
class PrefStates(StatesGroup):
    WAITING_PREFERENCES = State()

# ------------- UI HELPERS -------------
def main_menu_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Edit preferences", callback_data="edit_prefs")
    kb.button(text="🎟️ Find event for all users", callback_data="find_event_all")
    kb.adjust(1)
    return kb.as_markup()

WELCOME_TEXT = (
    "Hi! 👋\n\n"
    "Tell me your event preferences (e.g., “live hip-hop concerts, Fridays after 19:00, €25–€40, Amsterdam”).\n"
    "I’ll save them, and then you can:\n"
    "• Edit preferences\n"
    "• Find an event for the whole group (broadcast to everyone)\n\n"
    "Send your preferences now:"
)

# ------------- DB LIFECYCLE -------------
CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    preferences TEXT,
    created_at TEXT NOT NULL
);
"""

INSERT_USER_SQL = """
INSERT OR IGNORE INTO users (telegram_id, preferences, created_at)
VALUES (?, NULL, ?);
"""

UPDATE_PREFS_SQL = "UPDATE users SET preferences = ? WHERE telegram_id = ?;"
GET_USER_SQL = "SELECT id, telegram_id, preferences, created_at FROM users WHERE telegram_id = ?;"
GET_ALL_USERS_SQL = "SELECT telegram_id, preferences FROM users;"
GET_ALL_PREFS_NONEMPTY_SQL = "SELECT telegram_id, preferences FROM users WHERE preferences IS NOT NULL AND TRIM(preferences) <> '';"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_USERS_SQL)
        await db.commit()

async def ensure_user(conn: aiosqlite.Connection, tg_id: int):
    await conn.execute(INSERT_USER_SQL, (tg_id, datetime.now(timezone.utc).isoformat()))
    await conn.commit()

async def get_user(conn: aiosqlite.Connection, tg_id: int):
    async with conn.execute(GET_USER_SQL, (tg_id,)) as cur:
        return await cur.fetchone()

async def set_preferences(conn: aiosqlite.Connection, tg_id: int, prefs: str):
    await conn.execute(UPDATE_PREFS_SQL, (prefs.strip(), tg_id))
    await conn.commit()

async def get_all_users(conn: aiosqlite.Connection):
    async with conn.execute(GET_ALL_USERS_SQL) as cur:
        return await cur.fetchall()  # list of (telegram_id, preferences)

async def get_all_nonempty_preferences(conn: aiosqlite.Connection):
    async with conn.execute(GET_ALL_PREFS_NONEMPTY_SQL) as cur:
        return await cur.fetchall()  # list of (telegram_id, preferences)

# ------------- OPENAI CALL -------------
async def fetch_group_event_suggestion(all_prefs: list[tuple[int, str]]) -> str:
    """
    all_prefs: list of (telegram_id, preferences)
    """
    if not all_prefs:
        return "No user preferences found yet. Ask everyone to set preferences first."

    # Build a compact, structured prompt
    prefs_block = "\n".join(
        f"- user:{tgid} → {prefs}" for tgid, prefs in all_prefs
    )

    system_msg = (
        "You are an event concierge for a friend group. "
        "Given user preferences (music genres, time windows, budget, city), "
        "propose 1–3 concrete event ideas that fit the group collectively. "
        "Be specific, concise, and practical. Suggest dates, times, locations, and why they fit."
    )

    user_msg = (
        "Here are all users' preferences:\n"
        f"{prefs_block}\n\n"
        "Now suggest the best event(s) that most users can attend, and explain briefly."
    )

    try:
        resp = await oaiclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()
    except RateLimitError:
        return "OpenAI rate limit reached. Please try again shortly."
    except (APIConnectionError, APIError) as e:
        log.exception("OpenAI API error: %s", e)
        return "There was a temporary issue reaching the event planner. Please try again."
    except Exception as e:
        log.exception("Unexpected OpenAI error: %s", e)
        return "Unexpected error while generating the event. Please try again."

# ------------- BOT SETUP -------------
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ------------- HANDLERS -------------
@dp.message(CommandStart())
async def on_start(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as conn:
        await ensure_user(conn, tg_id)
        user = await get_user(conn, tg_id)

    # If no preferences -> ask now
    prefs = user[2]  # preferences
    if not prefs:
        await state.set_state(PrefStates.WAITING_PREFERENCES)
        await message.answer(WELCOME_TEXT)
    else:
        await message.answer(
            f"Welcome back! Your current preferences are:\n\n“{prefs}”",
            reply_markup=main_menu_kb()
        )

# @dp.message(PrefStates.WAITING_PREFERENCES)
# async def receive_preferences(message: types.Message, state: FSMContext):
#     tg_id = message.from_user.id
#     prefs = message.text or ""
#     prefs = prefs.strip()
#     if not prefs:
#         await message.answer("Please send some text for your preferences 🙂")
#         return

#     async with aiosqlite.connect(DB_PATH) as conn:
#         await set_preferences(conn, tg_id, prefs)

#     await state.clear()
#     await message.answer(
#         f"Got it! Saved your preferences:\n\n“{prefs}”",
#         reply_markup=main_menu_kb()
#     )

@dp.message(PrefStates.WAITING_PREFERENCES)
async def receive_preferences(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    prefs = message.text.strip() if message.text else ""

    if not prefs:
        await message.answer("Please send some text for your preferences 🙂")
        return

    async with aiosqlite.connect(DB_PATH) as conn:
        # 🔍 Check if user already has preferences
        async with conn.execute(
            "SELECT preferences FROM users WHERE telegram_id = ?;",
            (tg_id,)
        ) as cur:
            row = await cur.fetchone()

        if row and row[0]:
            old_prefs = row[0]
            await message.answer(
                f"You already have saved preferences:\n\n“{old_prefs}”\n\n"
                "Do you want to overwrite them? Send 'yes' to confirm or type new ones to replace."
            )
            # if you prefer, you could require explicit confirmation here
            # but if user sends new prefs directly, we can overwrite automatically below

        # 💾 Update or insert new preferences
        await conn.execute(
            "UPDATE users SET preferences = ? WHERE telegram_id = ?;",
            (prefs, tg_id)
        )
        await conn.commit()

    await state.clear()
    await message.answer(
        f"✅ Preferences saved:\n\n“{prefs}”",
        reply_markup=main_menu_kb()
    )



@dp.callback_query(F.data == "edit_prefs")
async def on_edit_prefs(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(PrefStates.WAITING_PREFERENCES)
    await cb.message.edit_text(
        "Okay! Send your **new** preferences, and I’ll update them.",
        parse_mode="Markdown"
    )
    await cb.answer()

@dp.callback_query(F.data == "find_event_all")
async def on_find_event_all(cb: types.CallbackQuery):
    await cb.answer("Collecting everyone’s preferences…")
    # Fetch all non-empty preferences
    async with aiosqlite.connect(DB_PATH) as conn:
        all_prefs = await get_all_nonempty_preferences(conn)

    # Generate event suggestion (OpenAI)
    await cb.message.edit_text("🧠 Planning an event that fits the whole group…")
    suggestion = await fetch_group_event_suggestion(all_prefs)

    # Broadcast to all registered users (even those without prefs—so they see the result)
    async with aiosqlite.connect(DB_PATH) as conn:
        all_users = await get_all_users(conn)

    tasks = []
    text = "📣 *Group Event Suggestion*\n\n" + suggestion
    for tg_id, _prefs in all_users:
        tasks.append(bot.send_message(chat_id=tg_id, text=text, parse_mode="Markdown"))

    # Fire all sends concurrently
    await asyncio.gather(*tasks, return_exceptions=True)

    # Also acknowledge the original chat with buttons again
    await cb.message.answer("Sent the event suggestion to everyone ✅", reply_markup=main_menu_kb())

# ------------- MAIN -------------
async def main():
    await init_db()
    log.info("DB ready at %s", DB_PATH)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
