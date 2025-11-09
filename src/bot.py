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
from langchain_core.messages import HumanMessage  # for agent.invoke payloads
from agent.agentkit.graph import agent
from rag.create_chromium_db import create_chromium_db
from dotenv import load_dotenv
import random
import re
import json


# OpenAI (async)
from openai import AsyncOpenAI, APIConnectionError, APIError, RateLimitError

# ------------- ENV -------------
load_dotenv()
# BOT
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# DBS
OPENAI_API_KEY = os.getenv("API_KEY")
DB_PATH_EVENTS = "DBs/RAG"
DB_PATH_BUSYHOURS = "DBs/busyhours.sqlite"
DB_PATH_USERS = "DBs/users.sqlite"
DB_PATH_TEAMS = "DBs/teams.sqlite"

# EMBEDING
EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_MODEL = "gpt-o4-mini"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in .env")

# ------------- LOGGING -------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tg-bot")

# ------------- AI CLIENT -------------
oaiclient = AsyncOpenAI(api_key=OPENAI_API_KEY)



# ------------- UI HELPERS -------------

# ------------- REPLY KEYBOARD (Teams) -------------

def main_menu_kb() -> types.ReplyKeyboardMarkup:
    # Two buttons: Edit Preferences, Find Event for All
    return types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [types.KeyboardButton(text="Menu")]
        ]
    )


def team_root_kb() -> types.ReplyKeyboardMarkup:
    # One persistent button
    return types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [types.KeyboardButton(text="Create Team"), types.KeyboardButton(text="Assign Team")],
            [types.KeyboardButton(text="Find Team Events"), types.KeyboardButton(text="Find my Events")],
            [types.KeyboardButton(text="Team info"), types.KeyboardButton(text="⬅️ Back")]
        ]
    )


class TeamStates(StatesGroup):
    WAITING_TEAM_CODE = State()


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
    team_id INTEGER,
    FOREIGN KEY (team_id) REFERENCES teams(id)
);
"""

CREATE_TEAMS_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER UNIQUE NOT NULL,
    team_key TEXT UNIQUE NOT NULL
);
"""

CREATE_BUSYHOURS_SQL = """
CREATE TABLE IF NOT EXISTS busy_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    start TEXT NOT NULL,
    duration TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
);
"""

INSERT_USER_SQL = """
INSERT OR IGNORE INTO users (telegram_id, preferences)
VALUES (?, NULL);
"""

UPDATE_PREFS_SQL = "UPDATE users SET preferences = ? WHERE telegram_id = ?;"
GET_USER_SQL = "SELECT id, telegram_id, preferences, team_id FROM users WHERE telegram_id = ?;"
GET_ALL_USERS_SQL = "SELECT telegram_id, preferences, team_id FROM users;"
GET_ALL_PREFS_NONEMPTY_SQL = "SELECT telegram_id, preferences FROM users WHERE preferences IS NOT NULL AND TRIM(preferences) <> '';"

async def init_db():
    """Initializes the SQLite databases and tables."""
    os.makedirs("DBs", exist_ok=True)

    async with aiosqlite.connect(DB_PATH_TEAMS) as db:
        await db.execute(CREATE_TEAMS_SQL)
        await db.commit()

    async with aiosqlite.connect(DB_PATH_USERS) as db:
        await db.execute(CREATE_USERS_SQL)
        await db.commit()

    async with aiosqlite.connect(DB_PATH_BUSYHOURS) as db:
        await db.execute(CREATE_BUSYHOURS_SQL)
        await db.commit()
# ------------- DB HELPERS -------------

    create_chromium_db(persist_directory=DB_PATH_EVENTS)

async def ensure_user(conn: aiosqlite.Connection, tg_id: int):
    await conn.execute(INSERT_USER_SQL, (tg_id,))
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
TEAM_CODE_RE = re.compile(r"^\d{6}$")

async def generate_unique_team_code() -> int:
    """Generate a unique 6-digit numeric code not already used in teams.team_id."""
    while True:
        code = random.randint(100000, 999999)
        async with aiosqlite.connect(DB_PATH_TEAMS) as db:
            async with db.execute("SELECT 1 FROM teams WHERE team_id = ?;", (code,)) as cur:
                if await cur.fetchone() is None:
                    return code

async def create_team_and_assign(tg_id: int) -> int:
    """
    Create a team with a unique 6-digit team_id and a random team_key,
    insert into DBs/teams.sqlite, and assign the creating user in DBs/users.sqlite.
    Returns the 6-digit team_id (code) shown to the user.
    """
    team_code = await generate_unique_team_code()
    # simple random key for future use
    team_key = os.urandom(9).hex()  # 18 hex chars

    # 1) Create team (teams.sqlite)
    async with aiosqlite.connect(DB_PATH_TEAMS) as tdb:
        await tdb.execute(
            "INSERT INTO teams (team_id, team_key) VALUES (?, ?);",
            (team_code, team_key)
        )
        await tdb.commit()
        # fetch internal PK id for FK in users table
        async with tdb.execute("SELECT id FROM teams WHERE team_id = ?;", (team_code,)) as cur:
            row = await cur.fetchone()
            if not row:
                raise RuntimeError("Team creation failed unexpectedly.")
            team_row_id = row[0]

    # 2) Assign user (users.sqlite) -> users.team_id stores teams.id (FK to teams.id)
    async with aiosqlite.connect(DB_PATH_USERS) as udb:
        await ensure_user(udb, tg_id)
        await udb.execute(
            "UPDATE users SET team_id = ? WHERE telegram_id = ?;",
            (team_row_id, tg_id)
        )
        await udb.commit()

    return team_code

async def find_team_row_id_by_code(team_code_text: str) -> int | None:
    """Return teams.id if a team with the given 6-digit code exists, else None."""
    if not TEAM_CODE_RE.match(team_code_text):
        return None
    code = int(team_code_text)
    async with aiosqlite.connect(DB_PATH_TEAMS) as tdb:
        async with tdb.execute("SELECT id FROM teams WHERE team_id = ?;", (code,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def assign_user_to_team_row_id(tg_id: int, team_row_id: int) -> None:
    async with aiosqlite.connect(DB_PATH_USERS) as udb:
        await ensure_user(udb, tg_id)
        await udb.execute(
            "UPDATE users SET team_id = ? WHERE telegram_id = ?;",
            (team_row_id, tg_id)
        )
        await udb.commit()





@dp.message(CommandStart())
async def on_start(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    print(f"User /start: {tg_id}")
    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        await ensure_user(conn, tg_id)
        user = await get_user(conn, tg_id)

    prefs = user[2]

    if prefs:
        try:
            parsed = json.loads(prefs)
            if isinstance(parsed, list):
                prefs_str = ", ".join(map(str, parsed))
            else:
                prefs_str = str(parsed)
        except (json.JSONDecodeError, TypeError):
            prefs_str = str(prefs)
    else:
        prefs_str = None




    if not prefs_str:
        await message.answer(WELCOME_TEXT + "\n"
                       "If you want to create or find a team, click the button below", reply_markup=main_menu_kb())
    else:
        await message.answer(f"Welcome back! Your current preferences are:\n\n“{prefs_str}”"
            "If you want to create or find a team, click the button below", reply_markup=main_menu_kb())
    

# ------------- MENU / TEAM KEYBOARD SWITCHING -------------

@dp.message(F.text == "Menu")
async def on_menu_clicked(message: types.Message):
    # Switch to team_root_kb when Menu is clicked
    await message.answer("Team controls:", reply_markup=team_root_kb())

@dp.message(F.text == "⬅️ Back")
async def on_back_clicked(message: types.Message):
    # Return to the main menu keyboard
    await message.answer("Back to menu.", reply_markup=main_menu_kb())


@dp.message(F.text == "Create Team")
async def on_create_team(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        team_code = await create_team_and_assign(tg_id)

        await message.answer(
            "✅ Team created!\n\n"
            "Share this 6-digit code with your friends so they can join.\n\n"
            "You have been assigned to this team.",
            reply_markup=team_root_kb(),
            parse_mode="Markdown"
        )

        await message.answer(
            f"🔑 *Team Code:* `{team_code}`",
            parse_mode="Markdown"
        )

        await state.clear()

    except Exception as e:
        log.exception("Create team failed: %s", e)
        await message.answer(
            "❌ Sorry, something went wrong while creating the team. Please try again.",
            reply_markup=team_root_kb()
        )

@dp.message(F.text == "Assign Team")
async def on_assign_team(message: types.Message, state: FSMContext):
    # Ask user for code and switch state
    await state.set_state(TeamStates.WAITING_TEAM_CODE)
    await message.answer(
        "Please send the 6-digit team ID you received (e.g., 123456).\n"
        "Send only the number.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(TeamStates.WAITING_TEAM_CODE)
async def on_assign_team_code_input(message: types.Message, state: FSMContext):
    tg_id = message.from_user.id
    code_text = (message.text or "").strip()

    # Validate format first
    if not TEAM_CODE_RE.match(code_text):
        await state.clear()
        await message.answer(
            "❌ The team ID format is incorrect. It must be exactly 6 digits.\n\n"
            "Please tap **Assign Team** and try again.",
            reply_markup=team_root_kb(),
            parse_mode="Markdown"
        )
        return

    # Check existence
    team_row_id = await find_team_row_id_by_code(code_text)
    if team_row_id is None:
        await state.clear()
        await message.answer(
            "❌ This team ID does not exist.\n\n"
            "Please tap **Assign Team** and try again.",
            reply_markup=team_root_kb(),
            parse_mode="Markdown"
        )
        return

    # Assign
    try:
        await assign_user_to_team_row_id(tg_id, team_row_id)
        await state.clear()
        await message.answer(
            "✅ You have been assigned to the team.",
            reply_markup=team_root_kb()
        )
    except Exception as e:
        log.exception("Assign team failed: %s", e)
        await state.clear()
        await message.answer(
            "Sorry, something went wrong while assigning you to the team. Please try again.",
            reply_markup=team_root_kb()
        )


@dp.message(F.text == "Team info")
async def on_team_info(message: types.Message):
    print("Team info requested")
    tg_id = message.from_user.id

    # 1) Find the user's team_row_id from users.sqlite
    async with aiosqlite.connect(DB_PATH_USERS) as udb:
        async with udb.execute(
            "SELECT team_id FROM users WHERE telegram_id = ?;",
            (tg_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row or row[0] is None:
        await message.answer(
            "ℹ️ You are not assigned to any team yet.\n"
            "Use **Create Team** or **Assign Team**.",
            reply_markup=team_root_kb(),
            parse_mode="Markdown"
        )
        return

    team_row_id = row[0]

    # 2) Resolve the public 6-digit team code from teams.sqlite
    async with aiosqlite.connect(DB_PATH_TEAMS) as tdb:
        async with tdb.execute(
            "SELECT team_id FROM teams WHERE id = ?;",
            (team_row_id,)
        ) as cur:
            trow = await cur.fetchone()

    if not trow:
        await message.answer(
            "⚠️ Your team record could not be found. Please try again.",
            reply_markup=team_root_kb()
        )
        return

    team_code = trow[0]

    # 3) Fetch all team members (telegram_ids) from users.sqlite
    async with aiosqlite.connect(DB_PATH_USERS) as udb:
        async with udb.execute(
            "SELECT telegram_id FROM users WHERE team_id = ? ORDER BY telegram_id;",
            (team_row_id,)
        ) as cur:
            member_rows = await cur.fetchall()

    member_ids = [r[0] for r in member_rows] if member_rows else []

    # 4) Resolve display names via Telegram (best-effort)
    members_pretty = []
    for uid in member_ids:
        try:
            chat = await bot.get_chat(uid)
            name_parts = [chat.first_name or "", chat.last_name or ""]
            display = " ".join(p for p in name_parts if p).strip() or (chat.username and f"@{chat.username}") or f"ID {uid}"
        except Exception:
            display = f"ID {uid}"
        if uid == tg_id:
            display = f"{display} (you)"
        members_pretty.append(display)

    # 5) Build and send the info
    members_block = "\n".join(f"• {m}" for m in members_pretty) if members_pretty else "— none yet —"

    # First: general info
    await message.answer(
        "📋 *Team Info*\n"
        "Here’s your current team code and members:",
        parse_mode="Markdown"
    )
    # Second: easy-to-copy code
    await message.answer(
        f"🔑 *Team Code:* `{team_code}`",
        parse_mode="Markdown"
    )
    # Third: members list
    await message.answer(
        f"👥 *Members:*\n{members_block}",
        reply_markup=team_root_kb(),
        parse_mode="Markdown"
    )



@dp.message(F.text)
async def on_free_text(message: types.Message, state: FSMContext):

    # Only handle genuine free-typed text (callbacks come via @dp.callback_query)
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send a text message 🙂")
        return

    # Build the agent payload
    payload = {
        "messages": [HumanMessage(content=text)],
        "telegram_id": str(message.from_user.id),
        "llm_calls": 0,  # change this if you track per-user LLM usage
    }

    # Call your agent (works for both sync .invoke and async .ainvoke)
    try:
        if hasattr(agent, "ainvoke"):
            result = await agent.ainvoke(payload)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, agent.invoke, payload)
    except Exception as e:
        log.exception("Agent error: %s", e)
        await message.answer("Sorry, I couldn't process that just now. Please try again.")
        return

    # Extract a reasonable text reply from agent result
    # (Adjust if your agent returns a different structure)
    reply_text = None
    if isinstance(result, str):
        reply_text = result
    elif isinstance(result, dict):
        # Common patterns: result["output"], result["answer"], result["messages"][-1].content, etc.
        reply_text = (
            result.get("output")
            or result.get("answer")
            or (result.get("messages", [])[-1].content if result.get("messages") else None)
        )

    if not reply_text:
        reply_text = "I processed your message, but didn't get a readable answer. Try rephrasing?"

    await message.answer(reply_text)


# ------------- MAIN -------------
async def main():
    await init_db()
    log.info("DB ready at %s", DB_PATH_USERS)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
