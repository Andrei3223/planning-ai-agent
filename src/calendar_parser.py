import requests
from datetime import datetime, timedelta, timezone, date
from icalendar import Calendar
from dateutil.rrule import rrulestr, rruleset

ICS_URL = ""

# ---- window: now .. now+7 days in local time ----
local_tz = datetime.now().astimezone().tzinfo
now = datetime.now(local_tz)
window_start = now
window_end = now + timedelta(days=7)

def to_local_aware(dt):
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=local_tz)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=local_tz)
    return dt.astimezone(local_tz)

def fmt_duration(td: timedelta) -> str:
    total_mins = int(td.total_seconds() // 60)
    if total_mins <= 0: return "0m"
    days, rem = divmod(total_mins, 1440)
    hrs, mins = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hrs:  parts.append(f"{hrs}h")
    if mins or not parts: parts.append(f"{mins}m")
    return " ".join(parts)

def base_duration(vevent, occ_start_local):
    if vevent.get("dtend"):
        return to_local_aware(vevent.get("dtend").dt) - occ_start_local
    if vevent.get("duration"):
        return vevent.get("duration").dt
    # All-day events without explicit end: assume 1 day
    if isinstance(vevent.get("dtstart").dt, date) and not isinstance(vevent.get("dtstart").dt, datetime):
        return timedelta(days=1)
    return timedelta(0)

def expand_instances(vevent, start, end):
    """Yield (occ_start_local, duration, instance_id, name)."""
    uid = str(vevent.get("uid", ""))
    name = str(vevent.get("summary", "(no title)"))

    dtstart_prop = vevent.get("dtstart")
    if not dtstart_prop:
        return
    dtstart_local = to_local_aware(dtstart_prop.dt)

    # Build recurrence set
    rs = rruleset()
    if vevent.get("rrule"):
        rule = rrulestr(vevent.get("rrule").to_ical().decode(), dtstart=dtstart_local)
        rs.rrule(rule)
    else:
        rs.rdate(dtstart_local)

    for rdate in vevent.get("rdate", []):
        for v in rdate.dts:
            rs.rdate(to_local_aware(v.dt))
    for exdate in vevent.get("exdate", []):
        for v in exdate.dts:
            rs.exdate(to_local_aware(v.dt))

    # Emit instances inside window
    for occ_start in rs.between(start, end, inc=True):
        dur = base_duration(vevent, occ_start)
        # Create a stable instance id (UID for single, UID#YYYYmmddTHHMMSS for recurrences)
        inst_id = uid if not vevent.get("rrule") else f"{uid}#{occ_start.strftime('%Y%m%dT%H%M%S')}"
        yield occ_start, dur, inst_id, name

# ---- fetch + parse ----
resp = requests.get(ICS_URL, timeout=20)
resp.raise_for_status()
cal = Calendar.from_ical(resp.content)

# ---- collect + print ----
rows = []
for ve in cal.walk("VEVENT"):
    rows.extend(expand_instances(ve, window_start, window_end) or [])

for start, dur, inst_id, name in sorted(rows, key=lambda x: x[0]):
    print(f"{start.strftime('%Y-%m-%d %H:%M')} — {fmt_duration(dur)} — {inst_id} — {name}")
