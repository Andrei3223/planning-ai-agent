from typing import List, Dict, Optional

# LangChain / LangGraph
from langchain.tools import tool
from pydantic import BaseModel





#     !!!!!!!!!     ###################################################
# TEMPORAL INSTEAD OF DB
USERS: Dict[str, Dict] = {}  # user_id -> { "preferences": set[str], "availability": {date: [[start,end], ...]} }
EVENTS: List[Dict] = []      # list of events: {"id","name","date","tags","start","end"}


def ensure_user(user_id: str):
    if user_id not in USERS:
        USERS[user_id] = {
            "preferences": set(),
            "availability": {},  # date -> list of [start, end]
        }

def _overlap_two_day_slots(slots_a: List[List[str]], slots_b: List[List[str]]) -> List[List[str]]:
    """Compute overlaps between two users' time slots on the same day."""
    overlaps: List[List[str]] = []
    for s1, e1 in slots_a:
        for s2, e2 in slots_b:
            start = max(s1, s2)
            end = min(e1, e2)
            if start < end:
                overlaps.append([start, end])
    return overlaps

def find_common_availability(user_ids: List[str]) -> Dict[str, List[List[str]]]:
    """
    Compute intersection of availability across all users.
    Returns: {date: [[start,end], ...]} representing overlapping intervals.
    """
    if not user_ids:
        return {}

    for uid in user_ids:
        ensure_user(uid)

    # Start from first user's availability
    base_av = USERS[user_ids[0]]["availability"]
    common: Dict[str, List[List[str]]] = {d: [s[:] for s in slots] for d, slots in base_av.items()}

    for uid in user_ids[1:]:
        av = USERS[uid]["availability"]
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
    end: str    # "HH:MM"


@tool
def refresh_events_catalog() -> str:
    """
    Refresh the catalog of available events.

    Use this when the user or system asks to refresh/update the list of events.
    """
    EVENTS.clear()
    EVENTS.extend(
        [
            {
                "id": "e1",
                "name": "Evening Run in the Park",
                "date": "2025-11-10",
                "tags": ["sport"],
                "start": "18:00",
                "end": "20:00",
            },
            {
                "id": "e2",
                "name": "Tech Meetup: AI & Pizza",
                "date": "2025-11-10",
                "tags": ["meetups", "tech"],
                "start": "19:00",
                "end": "21:00",
            },
            {
                "id": "e3",
                "name": "Live Jazz Concert",
                "date": "2025-11-11",
                "tags": ["music"],
                "start": "20:00",
                "end": "22:00",
            },
        ]
    )
    return f"Events refreshed: {len(EVENTS)} in catalog."


@tool
def update_user_profile(
    user_id: str,
    add_preferences: Optional[List[str]] = None,
    remove_preferences: Optional[List[str]] = None,
    add_availability: Optional[List[Slot]] = None,
    clear_availability: bool = False,
) -> Dict:
    """
    Update the stored profile of a user: preferences and availability.

    The LLM should:
    - Use add_preferences when the user mentions new interests (e.g. "I like sport and meetups").
    - Use remove_preferences when the user says they no longer like something.
    - Use add_availability when the user mentions free time (dates and times).
    - Use clear_availability=True when the user wants to reset their schedule completely.

    Args:
        user_id: ID of the user whose profile is being updated.
        add_preferences: list of new preference tags to add (lowercase tags like 'sport', 'music').
        remove_preferences: list of preference tags to remove.
        add_availability: list of Slot objects describing new available intervals.
        clear_availability: if True, remove all previously stored availability for this user before adding new ones.

    Returns a summary of the updated profile.
    """
    ensure_user(user_id)
    add_preferences = add_preferences or []
    remove_preferences = remove_preferences or []
    add_availability = add_availability or []

    prefs = USERS[user_id]["preferences"]
    av = USERS[user_id]["availability"]

    # Preferences
    for p in add_preferences:
        if p:
            prefs.add(p.lower())
    for p in remove_preferences:
        if p:
            prefs.discard(p.lower())

    # Availability
    if clear_availability:
        av.clear()

    for slot in add_availability:
        av.setdefault(slot.date, []).append([slot.start, slot.end])

    summary = {
        "user_id": user_id,
        "preferences": sorted(prefs),
        "availability_days": sorted(av.keys()),
    }
    return summary


@tool
def get_personal_event_suggestions(user_id: str) -> Dict:
    """
    Suggest events for a single user based on their preferences and availability.

    The LLM should call this when the user asks for events just for themselves.
    """
    ensure_user(user_id)
    prefs = USERS[user_id]["preferences"]
    av = USERS[user_id]["availability"]

    matches: List[Dict] = []

    for e in EVENTS:
        # Filter by preferences (if any stored)
        if prefs and not prefs.intersection(e["tags"]):
            continue

        day = e["date"]
        if day not in av:
            continue

        # Check time overlap on that date
        slots = av[day]
        for s, end_ in slots:
            if not (e["end"] <= s or end_ <= e["start"]):
                matches.append(e)
                break

    return {
        "user_id": user_id,
        "events": matches,
    }


@tool
def get_joint_event_suggestions(user_ids: List[str]) -> Dict:
    """
    Suggest events that are suitable for ALL given users.

    The LLM should call this when the user asks for events they can attend
    together with one or more other users.

    Logic:
    - Intersect users' availability to find overlapping time slots.
    - Intersect users' preferences to find shared interests.
    - Return events whose time windows overlap with the shared availability
      and whose tags match the shared preferences.
    """
    if len(user_ids) < 2:
        return {"error": "Provide at least two user_ids to get joint suggestions."}

    for uid in user_ids:
        ensure_user(uid)

    # Shared preferences (intersection over all users)
    prefs_sets = [USERS[uid]["preferences"] for uid in user_ids]
    if prefs_sets:
        shared_prefs = set.intersection(*prefs_sets) if all(prefs_sets) else set()
    else:
        shared_prefs = set()

    common_av = find_common_availability(user_ids)

    matches: List[Dict] = []
    for e in EVENTS:
        # If we have shared prefs, require at least one tag match
        if shared_prefs and not shared_prefs.intersection(e["tags"]):
            continue

        day = e["date"]
        if day not in common_av:
            continue

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


TOOLS = [
    refresh_events_catalog,
    update_user_profile,
    get_personal_event_suggestions,
    get_joint_event_suggestions,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
