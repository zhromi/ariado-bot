from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from icalendar import Calendar

from bot.db import Database
from bot.timeutils import as_utc, iso_utc

log = logging.getLogger(__name__)

MAX_BYTES = 5_000_000
TOTAL_TIMEOUT = 30
ALLOWED_HOST = "lms.astanait.edu.kz"
ALLOWED_PATH_PREFIX = "/calendar/export_execute.php"
USER_AGENT = "AITUDeadlineBot/1.0"


class SyncError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    count: int = 0
    error: str | None = None


def validate_calendar_url(url: str) -> str | None:
    url = url.strip()
    if not url or len(url) > 2000 or any(ch.isspace() for ch in url):
        return "Ссылка пустая или слишком длинная."
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        return "Нужна ссылка, которая начинается с https://."
    if parts.username or parts.password:
        return "В ссылке не должно быть логина и пароля."
    if (parts.hostname or "").lower() != ALLOWED_HOST or parts.port not in (None, 443):
        return f"Нужна ссылка с {ALLOWED_HOST}."
    if not parts.path.startswith(ALLOWED_PATH_PREFIX):
        return "Это не ссылка экспорта календаря. Нужна ссылка из calendar/export.php."
    return None


def safe_host(url: str) -> str:
    try:
        return urlsplit(url).netloc or "unknown"
    except Exception:
        return "unknown"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    cats = getattr(value, "cats", None)
    if cats:
        return _text(cats[0])
    to_ical = getattr(value, "to_ical", None)
    if callable(to_ical) and not isinstance(value, str):
        raw = to_ical()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", "replace").strip()
    return str(value).strip()


def _uid(component: Any, summary: str, dtstart: str) -> str:
    raw = _text(component.get("uid"))
    if raw:
        return raw[:200]
    digest = hashlib.sha256(f"{summary}|{dtstart}".encode()).hexdigest()
    return digest[:32]


def _parse_event(component: Any) -> dict[str, Any] | None:
    start_prop = component.get("dtstart")
    if start_prop is None:
        return None
    start = as_utc_prop(start_prop)
    if start is None:
        return None
    summary = _text(component.get("summary")) or "Без названия"
    start_iso = iso_utc(start)
    end_iso = None
    end_prop = component.get("dtend")
    if end_prop is not None:
        end = as_utc_prop(end_prop)
        if end is not None:
            end_iso = iso_utc(end)
    course = _text(component.get("categories")) or None
    if course:
        course = course[:120]
    return {
        "uid": _uid(component, summary, start_iso),
        "summary": summary,
        "course": course,
        "dtstart": start_iso,
        "dtend": end_iso,
    }


def parse_ics(payload: bytes) -> list[dict[str, Any]]:
    if b"BEGIN:VCALENDAR" not in payload[:4096].upper():
        raise SyncError("Это не файл календаря.")
    try:
        calendar = Calendar.from_ical(payload)
    except Exception as exc:
        raise SyncError("Файл календаря не читается.") from exc
    events: list[dict[str, Any]] = []
    for component in calendar.walk():
        if component.name != "VEVENT":
            continue
        try:
            event = _parse_event(component)
        except Exception:
            log.warning("skipped unreadable event in calendar")
            continue
        if event is not None:
            events.append(event)
    return events


def as_utc_prop(prop: Any):
    from datetime import date, datetime

    raw = getattr(prop, "dt", prop)
    if isinstance(raw, datetime):
        return as_utc(raw)
    if isinstance(raw, date):
        from bot.timeutils import ALMATY

        local = datetime(raw.year, raw.month, raw.day, 0, 0, tzinfo=ALMATY)
        return as_utc(local)
    return None


async def _check_request(request: httpx.Request) -> None:
    error = validate_calendar_url(str(request.url))
    if error:
        raise SyncError("Ссылка перенаправляет не на Moodle.")


async def download_ics(url: str) -> bytes:
    error = validate_calendar_url(url)
    if error:
        raise SyncError(error)
    chunks: list[bytes] = []
    total = 0
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                max_redirects=3,
                headers={"User-Agent": USER_AGENT},
                event_hooks={"request": [_check_request]},
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise SyncError(f"HTTP {response.status_code}")
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise SyncError("Календарь слишком большой.")
                        chunks.append(chunk)
    except SyncError:
        raise
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise SyncError("Moodle не ответил вовремя.") from exc
    except httpx.HTTPError as exc:
        raise SyncError("Не удалось скачать календарь.") from exc
    return b"".join(chunks)


async def sync_user(db: Database, discord_id: int, url: str) -> SyncResult:
    try:
        payload = await download_ics(url)
        events = parse_ics(payload)
        if not events and await db.count_moodle_events(discord_id) > 0:
            raise SyncError("Календарь пришёл пустым, старые события оставил.")
        count = await db.replace_moodle_events(discord_id, events)
    except SyncError as exc:
        log.info("sync failed for %s host=%s error=%s", discord_id, safe_host(url), exc.message)
        await db.set_sync_status(discord_id, False, exc.message)
        return SyncResult(ok=False, error=exc.message)
    except Exception:
        log.exception("sync crashed for %s host=%s", discord_id, safe_host(url))
        await db.set_sync_status(discord_id, False, "внутренняя ошибка синка")
        return SyncResult(ok=False, error="Не получилось обновить календарь.")
    await db.set_sync_status(discord_id, True, None)
    log.info("sync ok for %s host=%s events=%s", discord_id, safe_host(url), count)
    return SyncResult(ok=True, count=count)


async def sync_all(db: Database) -> None:
    for user in await db.users_with_calendar():
        url = user.get("calendar_url") or ""
        if not url:
            continue
        await sync_user(db, int(user["discord_id"]), url)
