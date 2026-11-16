from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app.models import StudyActivity

KINDS = ('video', 'vocabulary', 'writing', 'pdf', 'podcast')

def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def timezone_or_422(name: str) -> ZoneInfo:
    if len(name) > 100:
        raise HTTPException(422, 'Invalid timezone')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise HTTPException(422, 'Invalid timezone')

def daily_durations(activities: list[StudyActivity], zone: ZoneInfo) -> dict[date, dict[str, float]]:
    days: dict[date, dict[str, float]] = defaultdict(lambda: {kind: 0.0 for kind in KINDS})
    for item in activities:
        current, end = utc(item.started_at), utc(item.ended_at)
        if item.activity_type not in KINDS or end <= current:
            continue
        while current < end:
            local_date = current.astimezone(zone).date()
            next_midnight = datetime.combine(local_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
            segment_end = min(end, next_midnight)
            days[local_date][item.activity_type] += (segment_end - current).total_seconds()
            current = segment_end
    return days

def streaks(days: dict[date, dict[str, float]], today: date) -> tuple[int, int]:
    studied = {day for day, kinds in days.items() if sum(kinds.values()) >= 60}
    current_day = today if today in studied else today - timedelta(days=1)
    current = 0
    while current_day in studied:
        current += 1
        current_day -= timedelta(days=1)
    longest, run, previous = 0, 0, None
    for day in sorted(studied):
        run = run + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest
