from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

Period = Literal["today", "yesterday", "7days", "1month"]
PERIODS = {
    "today": "Today",
    "yesterday": "Yesterday",
    "7days": "Last 7 days",
    "1month": "Last 1 month",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_today(tz: ZoneInfo, now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(tz).date()


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Start (inclusive) and end (exclusive) of a local calendar day, in UTC."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def period_days(period: str, tz: ZoneInfo, now: datetime | None = None) -> list[date]:
    """Local calendar days covered by a report period, oldest first."""
    today = local_today(tz, now)
    if period == "today":
        return [today]
    if period == "yesterday":
        return [today - timedelta(days=1)]
    if period == "7days":
        count = 7
    elif period == "1month":
        count = 30
    else:
        raise ValueError(f"Unknown period {period!r}; expected one of {', '.join(PERIODS)}")
    return [today - timedelta(days=i) for i in range(count - 1, -1, -1)]


def merged_seconds(
    intervals: Iterable[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> float:
    """Total seconds covered by the union of intervals, clipped to the window.

    Overlapping intervals (an agent logged in to several queues at once) count once.
    """
    clipped = sorted(
        (max(s, window_start), min(e, window_end))
        for s, e in intervals
        if e > window_start and s < window_end
    )
    total = 0.0
    cur_start = cur_end = None
    for s, e in clipped:
        if e <= s:
            continue
        if cur_end is None or s > cur_end:
            if cur_end is not None:
                total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = s, e
        else:
            cur_end = max(cur_end, e)
    if cur_end is not None:
        total += (cur_end - cur_start).total_seconds()
    return total
