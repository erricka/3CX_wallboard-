"""Helpers for the value formats the 3CX XAPI returns."""

import re
from datetime import datetime, timezone

_ISO_DURATION = re.compile(
    r"^-?P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
# .NET TimeSpan style: "1.02:03:04.567" or "02:03:04"
_TIMESPAN = re.compile(r"^(?:(?P<days>\d+)\.)?(?P<hours>\d+):(?P<minutes>\d{1,2}):(?P<seconds>\d{1,2}(?:\.\d+)?)$")
_DIGITS = re.compile(r"\d+")


def parse_duration(value) -> float:
    """Seconds from an ISO-8601 duration ("PT1M5.2S"), a TimeSpan ("00:01:05") or a number."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = _ISO_DURATION.match(text) or _TIMESPAN.match(text)
    if not match:
        return 0.0
    parts = {k: float(v) for k, v in match.groupdict().items() if v}
    return (
        parts.get("days", 0) * 86400
        + parts.get("hours", 0) * 3600
        + parts.get("minutes", 0) * 60
        + parts.get("seconds", 0)
    )


def parse_datetime(value) -> datetime | None:
    """Timezone-aware datetime; values without an offset are taken as UTC."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def number_tokens(text) -> set[str]:
    """Digit groups in a caller/callee label such as "101 Doum Ratana" or "Inbound (800)"."""
    return set(_DIGITS.findall(text or ""))
