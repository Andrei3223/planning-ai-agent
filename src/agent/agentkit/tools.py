import json
import aiosqlite
from datetime import datetime

from typing import List, Dict, Optional, Set

# LangChain / LangGraph
from langchain.tools import tool
from pydantic import BaseModel
import os

# Database path from environment
DB_PATH = os.getenv("DB_PATH_USERS", "users.sqlite")




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
        WHERE user_id = ?
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


async def find_common_availability(conn: aiosqlite.Connection, user_ids: List[int]) -> Dict[str, List[List[str]]]:
    """
    Compute intersection of FREE availability across all given users.
    Returns:
        {date: [[start,end], ...]} representing common free intervals.
    """
    if not user_ids:
        return {}

    # Load first user's free slots
    base_av = await get_user_free_slots(conn, user_ids[0])
    common: Dict[str, List[List[str]]] = {d: [s[:] for s in slots] for d, slots in base_av.items()}

    # Intersect with each additional user
    for uid in user_ids[1:]:
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



class Slot(BaseModel):
    date: str  # ISO date, e.g. "2025-11-10"
    start: str  # "HH:MM"
    duration: str    # "HH:MM"


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
      - busy_hours

    Args:
        telegram_id: user's Telegram ID
        add_preferences: list of new tags to add
        remove_preferences: list of tags to remove
        add_availability: list of Slot(date, start, end)
        clear_availability: if True, delete all busy_hours for this user
    Returns:
        Dict summary of updated profile
    """
    add_preferences = add_preferences or []
    remove_preferences = remove_preferences or []
    add_availability = add_availability or []

    async with aiosqlite.connect(DB_PATH) as conn:
        # Ensure user exists
        now = datetime.utcnow().isoformat()
        await conn.execute(
            """
            INSERT OR IGNORE INTO users (telegram_id, preferences, created_at)
            VALUES (?, '', ?)
            """,
            (telegram_id, now),
        )
        await conn.commit()

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

        # Update availability
        if clear_availability:
            await conn.execute("DELETE FROM busy_hours WHERE user_id = ?", (telegram_id,))

        for slot in add_availability:
            # We store start as "YYYY-MM-DD HH:MM" and duration as "HH:MM"
            start = f"{slot.date} {slot.start}"
            duration = slot.end  # or compute time difference if needed
            await conn.execute(
                "INSERT INTO busy_hours (user_id, start, duration) VALUES (?, ?, ?)",
                (telegram_id, start, duration),
            )

        await conn.commit()

        # Summarize
        async with conn.execute(
            "SELECT DISTINCT date(start) FROM busy_hours WHERE user_id = ?", (telegram_id,)
        ) as cur:
            days = [r[0] for r in await cur.fetchall()]

        summary = {
            "user_id": telegram_id,
            "preferences": sorted(existing_prefs),
            "availability_days": sorted(days),
        }
        return summary


@tool
async def get_personal_event_suggestions_db(
    telegram_id: int,
) -> Dict:
    """
    Suggest events for a single user based on their preferences and availability.
    Uses `users`, `events`, and `busy_hours` tables.

    Returns:
        {
            "user_id": telegram_id,
            "events": [ {event_dict}, ... ]
        }
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT preferences FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
            prefs = set()
            if row and row[0]:
                try:
                    prefs = set(json.loads(row[0])) if row[0].startswith("[") else set(row[0].split(","))
                except Exception:
                    prefs = set(row[0].split(","))

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

        async with conn.execute("SELECT id, name, date, tags, start, duration FROM events") as cur:
            all_events = await cur.fetchall()

        # Normalize events into dicts
        events: List[Dict] = []
        for eid, name, date, tags, start, duration in all_events:
            tag_list = []
            if tags:
                tag_list = json.loads(tags) if tags.startswith("[") else [t.strip().lower() for t in tags.split(",")]
            events.append(
                {
                    "id": eid,
                    "name": name,
                    "date": date,
                    "tags": tag_list,
                    "start": start,
                    "end": duration,  # keep naming consistent (duration acts as end time)
                }
            )

        matches: List[Dict] = []
        for e in events:
            # Filter by preference intersection
            if prefs and not prefs.intersection(e["tags"]):
                continue

            # Date filter
            day = e["date"]
            if day not in availability:
                continue

            # Time overlap
            for s, end_ in availability[day]:
                if not (e["end"] <= s or end_ <= e["start"]):
                    matches.append(e)
                    break

        return {
            "user_id": telegram_id,
            "events": matches,
        }



@tool
async def get_joint_event_suggestions_db(
    user_ids: List[int],
) -> Dict:
    """
    Suggest events suitable for ALL given users (async + DB-based).

    Logic:
      1. Load all users' preferences.
      2. Compute shared preferences (intersection).
      3. Compute shared availability using find_common_availability().
      4. Load events from DB.
      5. Return only those events that match shared preferences AND overlap
         with shared availability windows.
    """
    if len(user_ids) < 2:
        return {"error": "Provide at least two user_ids to get joint suggestions."}

    async with aiosqlite.connect(DB_PATH) as conn:
        prefs_sets: List[Set[str]] = []
        for uid in user_ids:
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

        common_av = await find_common_availability(conn, user_ids)

        async with conn.execute("SELECT id, name, date, tags, start, duration FROM events") as cur:
            rows = await cur.fetchall()

        events = []
        for eid, name, date, tags, start, duration in rows:
            tag_list = []
            if tags:
                tag_list = json.loads(tags) if tags.startswith("[") else [t.strip().lower() for t in tags.split(",")]
            events.append(
                {
                    "id": eid,
                    "name": name,
                    "date": date,
                    "tags": tag_list,
                    "start": start,
                    "end": duration,  # using duration as end time
                }
            )

        matches: List[Dict] = []
        for e in events:
            # Filter by shared preferences (if any)
            if shared_prefs and not shared_prefs.intersection(e["tags"]):
                continue

            day = e["date"]
            if day not in common_av:
                continue

            # Check if any shared availability window overlaps event time
            for s, end_ in common_av[day]:
                if not (e["end"] <= s or end_ <= e["start"]):
                    matches.append(e)
                    break

        return {
            "user_ids": user_ids,
            "shared_preferences": sorted(shared_prefs),
            "shared_availability_days": sorted(common_av.keys()),
            "events": matches,
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

    async with aiosqlite.connect(DB_PATH) as db:
        # Optionally clear existing records
        if clear_existing:
            await db.execute("DELETE FROM busy_hours WHERE user_id = ?", (telegram_id,))
            await db.commit()

        # Insert new slots
        for slot in add_slots:
            # Combine date and start time into single string
            start_dt = f"{slot.date} {slot.start}"
            duration = slot.end  # stored as string "HH:MM"
            await db.execute(
                "INSERT INTO busy_hours (user_id, start, duration) VALUES (?, ?, ?)",
                (telegram_id, start_dt, duration),
            )

        await db.commit()

        # Return updated summary
        async with db.execute(
            "SELECT id, start, duration FROM busy_hours WHERE user_id = ? ORDER BY start",
            (telegram_id,),
        ) as cur:
            rows = await cur.fetchall()

        summary = {
            "user_id": telegram_id,
            "busy_hours_count": len(rows),
            "busy_hours": [{"start": r[1], "end": r[2]} for r in rows],
        }

        return summary

TOOLS = [
    update_user_profile_db,
    update_busy_hours,
    get_personal_event_suggestions_db,
    get_joint_event_suggestions_db,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
