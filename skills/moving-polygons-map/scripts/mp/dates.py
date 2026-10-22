"""Dates in the app's convention.

The app stores ISO strings. Negative years use JS numbering: "-0509-01-01…"
is JS year -509 and displays as "509 BC" (app/utils/dateUtils.ts). Scenario
dates are written the same way; "216 BC" is accepted as a shorthand for
"-0216". Date-only values default to 12:00 UTC so no timezone can shift the
day. Times of day (battles) are written as local clock time in UTC fields.
"""

from __future__ import annotations

import re
from typing import NamedTuple

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_MS = 86_400_000

_SCENARIO_RE = re.compile(
    r"^(-?)(\d{1,6})(?:-(\d{1,2})(?:-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?Z?)?)?)?$"
)
_BC_RE = re.compile(r"^(\d{1,6})\s*(BC|BCE|B\.C\.)$", re.I)
_AD_RE = re.compile(r"^(?:AD|A\.D\.|CE)?\s*(\d{1,4})\s*(?:AD|A\.D\.|CE)?$", re.I)

# What the app itself accepts (server/utils/validation.ts + app/utils/dateUtils.ts)
_APP_NEG_RE = re.compile(r"^-(\d+)-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2}))?")
_APP_POS_RE = re.compile(
    r"^\+?(\d{4}|\d{6})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})?)?$"
)


class When(NamedTuple):
    year: int
    month: int = 1
    day: int = 1
    hour: int = 12
    minute: int = 0
    second: int = 0

    @property
    def ms(self) -> int:
        return to_ms(self)

    @property
    def iso(self) -> str:
        return to_iso(self)


def parse(value: object) -> When:
    """Parse a scenario date: 1815, "1815-06-18", "1815-06-18T11:30", "-0216-08-02", "216 BC"."""
    if isinstance(value, bool):
        raise ValueError(f"not a date: {value!r}")
    if isinstance(value, int):
        return When(value)
    if isinstance(value, float) and value.is_integer():
        return When(int(value))
    if not isinstance(value, str):
        raise ValueError(f"not a date: {value!r}")
    s = value.strip()
    m = _BC_RE.match(s)
    if m:
        return When(-int(m.group(1)))
    m = _SCENARIO_RE.match(s)
    if m:
        sign, y, mo, d, hh, mi, ss = m.groups()
        year = -int(y) if sign else int(y)
        month = int(mo) if mo else 1
        day = int(d) if d else 1
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError(f"bad month/day in {value!r}")
        if hh is None:
            return When(year, month, day)
        return When(year, month, day, int(hh), int(mi), int(ss or 0))
    m = _AD_RE.match(s)
    if m:
        return When(int(m.group(1)))
    raise ValueError(f"unrecognised date {value!r} (use YYYY, YYYY-MM-DD, YYYY-MM-DDTHH:MM or -YYYY-MM-DD for BC)")


def days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 in the proleptic Gregorian calendar (same as JS Date)."""
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return y + (m <= 2), m, d


def to_ms(w: When) -> int:
    return (days_from_civil(w.year, w.month, w.day) * DAY_MS
            + ((w.hour * 60 + w.minute) * 60 + w.second) * 1000)


def from_ms(ms: float) -> When:
    ms = int(round(ms))
    days, rem = divmod(ms, DAY_MS)
    y, m, d = civil_from_days(days)
    secs = rem // 1000
    return When(y, m, d, secs // 3600, (secs // 60) % 60, secs % 60)


def to_iso(w: When) -> str:
    year = f"-{-w.year:04d}" if w.year < 0 else f"{w.year:04d}"
    return f"{year}-{w.month:02d}-{w.day:02d}T{w.hour:02d}:{w.minute:02d}:{w.second:02d}.000Z"


def format_year(w: When) -> str:
    if w.year < 0:
        return f"{-w.year} BC"
    if w.year == 0:
        return "1 BC"
    return str(w.year)


def format_tick(w: When, span_ms: float) -> str:
    """Mirror of formatTimeTick in app/utils/dateUtils.ts."""
    if span_ms >= 3 * 365 * DAY_MS:
        return format_year(w)
    month = MONTHS[w.month - 1]
    if span_ms > 60 * DAY_MS:
        return f"{month} {format_year(w)}"
    day = f"{w.day} {month}"
    if span_ms > 3 * DAY_MS:
        return day
    return f"{day} {w.hour:02d}:{w.minute:02d}"


def parse_app_datetime(value: object) -> int | None:
    """Epoch ms the way the app's server parses an import datetime; None when it would reject it."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.startswith("-"):
        m = _APP_NEG_RE.match(s)
        if not m:
            return None
        y, mo, d, hh, mi, ss = m.groups()
        w = When(-int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
    else:
        m = _APP_POS_RE.match(s)
        if not m:
            return None
        y, mo, d, hh, mi, ss, tz = m.groups()
        w = When(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
        if tz and tz != "Z":
            sign = 1 if tz[0] == "+" else -1
            offset = sign * (int(tz[1:3]) * 60 + int(tz[4:6])) * 60_000
            return to_ms(w) - offset
    if not (1 <= w.month <= 12 and 1 <= w.day <= 31 and w.hour < 24 and w.minute < 60 and w.second < 60):
        return None
    return to_ms(w)
