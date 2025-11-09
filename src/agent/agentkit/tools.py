import json
import aiosqlite
from datetime import datetime

from typing import List, Dict, Optional, Set

# LangChain / LangGraph
from langchain.tools import tool
from pydantic import BaseModel
import os

# custom imports 
from .model import llm
from .get_nearest import get_nearest_events

# Database paths from environment
DB_PATH_EVENTS = "DBs/RAG"
DB_PATH_BUSYHOURS = "DBs/busyhours.sqlite"
DB_PATH_USERS = "DBs/users.sqlite"
DB_PATH_TEAMS = "DBs/teams.sqlite"


class Slot(BaseModel):
    date: str  # ISO date, e.g. "2025-11-10"
    start: str  # "HH:MM"
    duration: str    # "HH:MM"


#     !!!!!!!!!     ###################################################
def _overlap_two_day_slots(slots_a: List[List[str]], slots_b: List[List[str]]) -> List[List[str]]:
    """Compute overlaps between two users' free slots on the same day."""
    overlaps: List[List[str]] = []
    for s1, e1 in slots_a:
        for s2, e2 in slots_b:
            start = max(s1, s2)
            end = min(e1, e2)
            if start < end:
                overlaps.append([start, end])
    return overlaps


def invert_busy_to_free(busy_slots: List[List[str]], day_start="08:00", day_end="22:00") -> List[List[str]]:
    """
    Given a list of busy [start,end] slots for one day,
    return free [start,end] slots between day_start and day_end.
    """
    # Sort busy slots
    busy_sorted = sorted(busy_slots, key=lambda x: x[0])
    free_slots: List[List[str]] = []
    current_start = day_start

    for s, e in busy_sorted:
        if s > current_start:
            free_slots.append([current_start, s])
        if e > current_start:
            current_start = max(current_start, e)

    # Last free interval until day_end
    if current_start < day_end:
        free_slots.append([current_start, day_end])

    return free_slots


async def get_user_free_slots(conn: aiosqlite.Connection, telegram_id: int) -> Dict[str, List[List[str]]]:
    """
    Load a user's FREE slots (computed as day_window - busy_hours).
    Returns:
        {date: [[start, end], ...]}  # all times as strings
    """
    # Fetch busy intervals from DB
    query = """
        SELECT start, duration
        FROM busy_hours
        WHERE telegram_id = ?
    """
    result: Dict[str, List[List[str]]] = {}

    async with conn.execute(query, (telegram_id,)) as cursor:
        async for start, duration in cursor:
            # Expected: start like "2025-11-10 09:00", duration = "11:00" (end time)
            if " " in start:
                date, t_start = start.split(" ", 1)
            else:
                date, t_start = "unknown", start
            t_end = duration
            result.setdefault(date, []).append([t_start, t_end])

    # Invert busy → free for each day
    free_by_day: Dict[str, List[List[str]]] = {}
    for day, busy_slots in result.items():
        free_by_day[day] = invert_busy_to_free(busy_slots)

    return free_by_day


async def find_common_availability(conn: aiosqlite.Connection, telegram_ids: List[int]) -> Dict[str, List[List[str]]]:
    """
    Compute intersection of FREE availability across all given users.
    Returns:
        {date: [[start,end], ...]} representing common free intervals.
    """
    if not telegram_ids:
        return {}

    # Load first user's free slots
    base_av = await get_user_free_slots(conn, telegram_ids[0])
    common: Dict[str, List[List[str]]] = {d: [s[:] for s in slots] for d, slots in base_av.items()}

    # Intersect with each additional user
    for uid in telegram_ids[1:]:
        av = await get_user_free_slots(conn, uid)
        new_common: Dict[str, List[List[str]]] = {}
        for day in set(common) & set(av):
            overlaps = _overlap_two_day_slots(common[day], av[day])
            if overlaps:
                new_common[day] = overlaps
        common = new_common
        if not common:
            break

    return common
#     !!!!!!!!!     ###################################################



@tool
async def update_user_profile_db(
    telegram_id: int,
    add_preferences: Optional[List[str]] = None,
    remove_preferences: Optional[List[str]] = None,
    add_availability: Optional[List[Slot]] = None,
    clear_availability: bool = False,
) -> Dict:
    """
    Update a user's preferences and availability using aiosqlite database tables:
      - users

    Args:
        telegram_id: user's Telegram ID
        add_preferences: list of new tags to add
        remove_preferences: list of tags to remove
    Returns:
        Dict summary of updated profile
    """
    add_preferences = add_preferences or []
    remove_preferences = remove_preferences or []
    add_availability = add_availability or []

    async with aiosqlite.connect(DB_PATH_USERS) as conn:

        # Load current preferences
        async with conn.execute(
            "SELECT preferences FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            existing_prefs = set()
            if row and row[0]:
                existing_prefs = set(json.loads(row[0])) if row[0].startswith("[") else set(row[0].split(","))

        # Update preferences
        for p in add_preferences:
            if p:
                existing_prefs.add(p.lower())
        for p in remove_preferences:
            if p:
                existing_prefs.discard(p.lower())

        # Save updated preferences back
        prefs_serialized = json.dumps(sorted(existing_prefs))
        await conn.execute(
            "UPDATE users SET preferences = ? WHERE telegram_id = ?",
            (prefs_serialized, telegram_id),
        )
        
        summary = {
            "telegram_id": telegram_id,
            "preferences": sorted(existing_prefs),
        }
        return summary


@tool
async def get_personal_event_suggestions_db(
    telegram_id: int,
) -> Dict:
    """
    Suggest events for a single user based on their preferences and availability.
    Integrates SQLite for user info + busy hours, and Chroma vector search for events.
    """
    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        async with conn.execute("SELECT preferences FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
            prefs = set()
            if row and row[0]:
                try:
                    prefs = set(json.loads(row[0])) if row[0].startswith("[") else set(row[0].split(","))
                except Exception:
                    prefs = set(row[0].split(","))

    async with aiosqlite.connect(DB_PATH_BUSYHOURS) as conn:
        async with conn.execute("SELECT start, duration FROM busy_hours WHERE user_id = ?", (telegram_id,)) as cur:
            rows = await cur.fetchall()

        # Build a dict: {date: [(start, end)]}
        availability: Dict[str, List[List[str]]] = {}
        for start, duration in rows:
            # Expected format: start = "YYYY-MM-DD HH:MM", duration = "HH:MM"
            if " " in start:
                date, t_start = start.split(" ", 1)
            else:
                date, t_start = "unknown", start
            t_end = duration
            availability.setdefault(date, []).append([t_start, t_end])

    # Build busy intervals per date
    busy_by_date: Dict[str, List[List[str]]] = {}
    for start, duration in rows:
        if " " in start:
            date, t_start = start.split(" ", 1)
        else:
            date, t_start = "unknown", start
        t_end = duration
        busy_by_date.setdefault(date, []).append([t_start, t_end])

    preferences_str = ", ".join(sorted(prefs)) if prefs else "general events"
    query = f"Find upcoming {preferences_str} events."

    rag_result = get_nearest_events(llm, query, persist_directory=DB_PATH_EVENTS)

    # Build return structure
    return {
        "telegram_id": telegram_id,
        "preferences": sorted(prefs),
        "busy_days": sorted(busy_by_date.keys()),
        "suggestions_query": query,
        "rag_result": rag_result,  # text result from the vector retriever
    }



@tool
async def get_joint_event_suggestions_db(
    telegram_ids: List[int],
) -> Dict:
    """
    Suggest events suitable for ALL given users (async + RAG-based).
    Combines preferences from SQLite and uses vector search via Chroma.

    Logic:
      1. Load all users' preferences.
      2. Compute shared preferences (intersection).
      3. Compute shared free days using find_common_availability().
      4. Retrieve matching events from Chroma RAG store.
    """
    if len(telegram_ids) < 2:
        return {"error": "Provide at least two telegram_ids to get joint suggestions."}

    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        prefs_sets: List[Set[str]] = []
        for uid in telegram_ids:
            async with conn.execute("SELECT preferences FROM users WHERE telegram_id = ?", (uid,)) as cur:
                row = await cur.fetchone()
                prefs = set()
                if row and row[0]:
                    try:
                        prefs = set(json.loads(row[0])) if row[0].startswith("[") else set(row[0].split(","))
                    except Exception:
                        prefs = set(row[0].split(","))
                prefs_sets.append(prefs)

    shared_prefs = set.intersection(*prefs_sets) if all(prefs_sets) else set()


    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        common_av = await find_common_availability(conn, telegram_ids)

    prefs_text = ", ".join(sorted(shared_prefs)) if shared_prefs else "general interests"
    query = f"Find upcoming events related to {prefs_text} that fit all users' shared free time."

    if common_av:
        earliest_day = sorted(common_av.keys())[0]
        query += f" Preferably after {earliest_day}."

    # Retrieve events from Chroma RAG
    rag_result = get_nearest_events(llm, query, persist_directory=DB_PATH_EVENTS)

    # Return structured output
    return {
        "telegram_ids": telegram_ids,
        "shared_preferences": sorted(shared_prefs),
        "shared_availability_days": sorted(common_av.keys()),
        "query_used": query,
        "rag_result": rag_result,  # textual recommendations from vector DB
    }


@tool
async def update_busy_hours(
    telegram_id: int,
    add_slots: Optional[List[Slot]] = None,
    clear_existing: bool = False,
) -> Dict:
    """
    Update a user's busy hours in the `busy_hours` table.

    Args:
        telegram_id: user's Telegram ID
        add_slots: list of Slot objects to add
        clear_existing: if True, remove all existing busy hours before inserting new ones

    Returns:
        Dict summary with total busy hour entries after update
    """
    add_slots = add_slots or []

    async with aiosqlite.connect(DB_PATH_BUSYHOURS) as db:
        # Optionally clear existing records
        if clear_existing:
            await db.execute("DELETE FROM busy_hours WHERE telegram_id = ?", (telegram_id,))
            await db.commit()

        # Insert new slots
        for slot in add_slots:
            # Combine date and start time into single string
            start_dt = f"{slot.date} {slot.start}"
            duration = slot.duration  # stored as string "HH:MM"
            await db.execute(
                "INSERT INTO busy_hours (telegram_id, start, duration) VALUES (?, ?, ?)",
                (telegram_id, start_dt, duration),
            )

        await db.commit()

        # Return updated summary
        async with db.execute(
            "SELECT id, start, duration FROM busy_hours WHERE telegram_id = ? ORDER BY start",
            (telegram_id,),
        ) as cur:
            rows = await cur.fetchall()

        summary = {
            "telegram_id": telegram_id,
            "busy_hours_count": len(rows),
            "busy_hours": [{"start": r[1], "end": r[2]} for r in rows],
        }

        print(summary)

        return summary


@tool
async def get_team_members_db(team_id: int) -> Dict:
    """
    Retrieve all team members for a given team based on the new schema:
      - users(team_id) references teams(id)
      - teams(id, team_id, team_key)

    Args:
        team_id (int): The team_id value from the 'teams' table (NOT the internal PK id).

    Returns:
        {
            "team_id": int,
            "members": [ {"telegram_id": int}, ... ],
            "count": int
        }
    """
    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        # First, get the internal 'id' of the team based on its public team_id
        async with conn.execute(
            "SELECT id FROM teams WHERE team_id = ?", (team_id,)
        ) as cur:
            team_row = await cur.fetchone()

        if not team_row:
            return {"error": f"No team found with team_id={team_id}"}

        internal_team_pk = team_row[0]

        # Get all users belonging to that team
        async with conn.execute(
            "SELECT telegram_id FROM users WHERE team_id = ?", (internal_team_pk,)
        ) as cur:
            rows = await cur.fetchall()

    members = [r[0] for r in rows]
    return {
        "team_id": team_id,
        "members": [{"telegram_id": t} for t in members],
        "count": len(members),
    }


@tool
async def get_user_busy_hours_db(telegram_id: int) -> Dict:
    """
    Return all busy hours for a given user from `busy_hours.sqlite`.

    Returns:
        {
            "telegram_id": int,
            "busy_hours": [
                {"start": "YYYY-MM-DD HH:MM", "end": "HH:MM"},
                ...
            ]
        }
    """
    async with aiosqlite.connect(DB_PATH_BUSYHOURS) as conn:
        async with conn.execute(
            "SELECT start, duration FROM busy_hours WHERE telegram_id = ? ORDER BY start",
            (telegram_id,),
        ) as cur:
            rows = await cur.fetchall()

    busy_hours = [{"start": s, "end": d} for s, d in rows]
    return {"telegram_id": telegram_id, "busy_hours_count": len(busy_hours), "busy_hours": busy_hours}


@tool
async def get_user_preferences_db(telegram_id: int) -> Dict:
    """
    Retrieve a user's stored preferences from `users.sqlite`.

    Returns:
        {
            "telegram_id": int,
            "preferences": [str, ...]
        }
    """
    async with aiosqlite.connect(DB_PATH_USERS) as conn:
        async with conn.execute(
            "SELECT preferences FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()

    prefs = []
    if row and row[0]:
        try:
            prefs = json.loads(row[0]) if row[0].startswith("[") else [p.strip() for p in row[0].split(",") if p.strip()]
        except Exception:
            prefs = [p.strip() for p in row[0].split(",") if p.strip()]

    return {"telegram_id": telegram_id, "preferences": sorted(prefs)}


TOOLS = [
    get_team_members_db,
    get_user_busy_hours_db,
    get_user_preferences_db,
    update_user_profile_db,
    update_busy_hours,
    get_personal_event_suggestions_db,
    get_joint_event_suggestions_db,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
