from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import aiosqlite

from bot.timeutils import utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id INTEGER PRIMARY KEY,
    username TEXT,
    calendar_url TEXT,
    dm_enabled INTEGER NOT NULL DEFAULT 1,
    dm_blocked INTEGER NOT NULL DEFAULT 0,
    remind_hours TEXT NOT NULL DEFAULT '24,1',
    last_sync_at TEXT,
    last_sync_ok INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id INTEGER NOT NULL,
    uid TEXT NOT NULL,
    summary TEXT NOT NULL,
    course TEXT,
    dtstart TEXT NOT NULL,
    dtend TEXT,
    source TEXT NOT NULL,
    reminded_json TEXT NOT NULL DEFAULT '[]',
    hidden INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(discord_id, uid)
);

CREATE INDEX IF NOT EXISTS idx_events_user_start ON events(discord_id, dtstart);
"""


def _reminded(raw: str | None) -> list[float]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[float] = []
    for item in data:
        try:
            out.append(round(float(item), 4))
        except (TypeError, ValueError):
            continue
    return out


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    def _require(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("database is not connected")
        return self.conn

    async def touch_user(self, discord_id: int, username: str) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO users (discord_id, username, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET username=excluded.username
                """,
                (discord_id, username[:80], utcnow_iso()),
            )
            await conn.commit()

    async def get_user(self, discord_id: int) -> dict[str, Any] | None:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,))
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def set_calendar_url(self, discord_id: int, url: str | None) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute(
                "UPDATE users SET calendar_url=? WHERE discord_id=?",
                (url or None, discord_id),
            )
            await conn.commit()

    async def clear_user_data(self, discord_id: int) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute("DELETE FROM events WHERE discord_id=?", (discord_id,))
            await conn.execute(
                """
                UPDATE users
                SET calendar_url=NULL, last_sync_at=NULL, last_sync_ok=NULL, last_error=NULL
                WHERE discord_id=?
                """,
                (discord_id,),
            )
            await conn.commit()

    async def set_sync_status(self, discord_id: int, ok: bool, error: str | None) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute(
                """
                UPDATE users
                SET last_sync_at=?, last_sync_ok=?, last_error=?
                WHERE discord_id=?
                """,
                (utcnow_iso(), 1 if ok else 0, (error or None), discord_id),
            )
            await conn.commit()

    async def set_remind_hours(self, discord_id: int, hours: str) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute(
                "UPDATE users SET remind_hours=? WHERE discord_id=?",
                (hours, discord_id),
            )
            await conn.commit()

    async def set_dm_blocked(self, discord_id: int, blocked: bool) -> None:
        conn = self._require()
        async with self._lock:
            await conn.execute(
                "UPDATE users SET dm_blocked=? WHERE discord_id=?",
                (1 if blocked else 0, discord_id),
            )
            await conn.commit()

    async def replace_moodle_events(self, discord_id: int, events: list[dict[str, Any]]) -> int:
        conn = self._require()
        now = utcnow_iso()
        async with self._lock:
            cursor = await conn.execute(
                """
                SELECT uid, dtstart, reminded_json, hidden
                FROM events
                WHERE discord_id=? AND source='moodle'
                """,
                (discord_id,),
            )
            existing = {row["uid"]: row for row in await cursor.fetchall()}
            new_uids = [event["uid"] for event in events]
            for event in events:
                old = existing.get(event["uid"])
                hidden = int(old["hidden"]) if old else 0
                if old and old["dtstart"] == event["dtstart"]:
                    reminded = old["reminded_json"]
                else:
                    reminded = "[]"
                await conn.execute(
                    """
                    INSERT INTO events (
                        discord_id, uid, summary, course, dtstart, dtend, source,
                        reminded_json, hidden, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'moodle', ?, ?, ?)
                    ON CONFLICT(discord_id, uid) DO UPDATE SET
                        summary=excluded.summary,
                        course=excluded.course,
                        dtstart=excluded.dtstart,
                        dtend=excluded.dtend,
                        source='moodle',
                        reminded_json=excluded.reminded_json,
                        hidden=excluded.hidden,
                        updated_at=excluded.updated_at
                    """,
                    (
                        discord_id,
                        event["uid"],
                        event["summary"][:300],
                        event.get("course"),
                        event["dtstart"],
                        event.get("dtend"),
                        reminded,
                        hidden,
                        now,
                    ),
                )
            if new_uids:
                placeholders = ",".join("?" * len(new_uids))
                await conn.execute(
                    f"""
                    DELETE FROM events
                    WHERE discord_id=? AND source='moodle' AND uid NOT IN ({placeholders})
                    """,
                    (discord_id, *new_uids),
                )
            else:
                await conn.execute(
                    "DELETE FROM events WHERE discord_id=? AND source='moodle'",
                    (discord_id,),
                )
            await conn.commit()
        return len(events)

    async def count_moodle_events(self, discord_id: int) -> int:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE discord_id=? AND source='moodle'",
                (discord_id,),
            )
            row = await cursor.fetchone()
        return int(row["n"])

    async def add_manual(
        self,
        discord_id: int,
        summary: str,
        course: str | None,
        dtstart: str,
    ) -> int:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                INSERT INTO events (
                    discord_id, uid, summary, course, dtstart, dtend, source,
                    reminded_json, hidden, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 'manual', '[]', 0, ?)
                """,
                (discord_id, f"manual-{uuid4()}", summary[:300], course, dtstart, utcnow_iso()),
            )
            await conn.commit()
            return int(cursor.lastrowid)

    async def get_event(self, discord_id: int, event_id: int) -> dict[str, Any] | None:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                "SELECT * FROM events WHERE id=? AND discord_id=?",
                (event_id, discord_id),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_manual(self, discord_id: int, event_id: int) -> bool:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                DELETE FROM events
                WHERE id=? AND discord_id=? AND source='manual'
                """,
                (event_id, discord_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def hide_event(self, discord_id: int, event_id: int) -> bool:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                UPDATE events SET hidden=1, updated_at=?
                WHERE id=? AND discord_id=?
                """,
                (utcnow_iso(), event_id, discord_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def events_between(self, discord_id: int, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                SELECT * FROM events
                WHERE discord_id=? AND hidden=0 AND dtstart>=? AND dtstart<?
                ORDER BY dtstart, id
                """,
                (discord_id, start_iso, end_iso),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def count_events(self, discord_id: int) -> int:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE discord_id=? AND hidden=0",
                (discord_id,),
            )
            row = await cursor.fetchone()
        return int(row["n"])

    async def users_with_calendar(self) -> list[dict[str, Any]]:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                SELECT discord_id, calendar_url
                FROM users
                WHERE calendar_url IS NOT NULL AND calendar_url != ''
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def upcoming_for_reminders(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                SELECT e.id, e.discord_id, e.summary, e.course, e.dtstart, e.reminded_json,
                       u.remind_hours, u.dm_blocked
                FROM events e
                JOIN users u ON u.discord_id = e.discord_id
                WHERE e.hidden=0 AND e.dtstart>=? AND e.dtstart<?
                """,
                (start_iso, end_iso),
            )
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["reminded"] = _reminded(item.get("reminded_json"))
            result.append(item)
        return result

    async def mark_reminded(self, event_id: int, thresholds: list[float]) -> None:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute("SELECT reminded_json FROM events WHERE id=?", (event_id,))
            row = await cursor.fetchone()
            if row is None:
                return
            merged = set(_reminded(row["reminded_json"]))
            merged.update(round(float(item), 4) for item in thresholds)
            await conn.execute(
                "UPDATE events SET reminded_json=? WHERE id=?",
                (json.dumps(sorted(merged)), event_id),
            )
            await conn.commit()

    async def admin_overview(self) -> list[dict[str, Any]]:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                """
                SELECT
                    u.discord_id,
                    u.username,
                    CASE WHEN u.calendar_url IS NULL OR u.calendar_url = '' THEN 0 ELSE 1 END AS has_calendar,
                    u.last_sync_at,
                    u.last_sync_ok,
                    u.last_error,
                    u.dm_blocked,
                    (
                        SELECT COUNT(*) FROM events e
                        WHERE e.discord_id=u.discord_id AND e.hidden=0
                    ) AS event_count
                FROM users u
                ORDER BY u.username COLLATE NOCASE
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def broadcast_targets(self) -> list[int]:
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(
                "SELECT discord_id FROM users WHERE dm_enabled=1 AND dm_blocked=0"
            )
            rows = await cursor.fetchall()
        return [int(row["discord_id"]) for row in rows]


_db: Database | None = None


async def init_db(path: str) -> Database:
    global _db
    _db = Database(path)
    await _db.connect()
    return _db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("database is not initialized")
    return _db
