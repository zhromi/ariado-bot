from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    ALMATY = ZoneInfo("Asia/Almaty")
except Exception:
    ALMATY = timezone(timedelta(hours=5))


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def iso_utc(dt: datetime) -> str:
    return as_utc(dt).isoformat()


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return as_utc(dt)


def format_almaty(value: str | datetime) -> str:
    dt = parse_iso(value) if isinstance(value, str) else as_utc(value)
    return dt.astimezone(ALMATY).strftime("%d.%m %H:%M")


def almaty_day_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time.min, tzinfo=ALMATY)
    end = start + timedelta(days=1)
    return iso_utc(start), iso_utc(end)


def today_almaty() -> date:
    return utcnow().astimezone(ALMATY).date()


def human_left(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    if hours < 48:
        extra = minutes % 60
        return f"{hours} ч" if extra == 0 else f"{hours} ч {extra} мин"
    days = hours // 24
    extra_h = hours % 24
    return f"{days} д" if extra_h == 0 else f"{days} д {extra_h} ч"


def parse_user_deadline(date_text: str, time_text: str | None) -> datetime | None:
    try:
        day = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    if time_text and time_text.strip():
        try:
            clock = datetime.strptime(time_text.strip(), "%H:%M").time()
        except ValueError:
            return None
    else:
        clock = time(23, 59)
    local = datetime.combine(day, clock, tzinfo=ALMATY)
    return as_utc(local)


def parse_remind_hours(text: str) -> list[float] | None:
    parts = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
    if not parts or len(parts) > 6:
        return None
    values: list[float] = []
    seen: set[float] = set()
    for part in parts:
        try:
            value = round(float(part.replace(",", ".")), 4)
        except ValueError:
            return None
        if value <= 0 or value > 24 * 30 or value in seen:
            if value in seen:
                continue
            return None
        seen.add(value)
        values.append(value)
    return values or None


def newly_crossed(hours_left: float, thresholds: list[float], already: set[float]) -> list[float]:
    if hours_left < 0:
        return []
    return sorted(t for t in thresholds if hours_left <= t and t not in already)
