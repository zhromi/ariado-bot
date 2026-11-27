from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from bot.calendar_sync import SyncError, parse_ics, validate_calendar_url
from bot.db import Database
from bot.timeutils import (
    format_almaty,
    newly_crossed,
    parse_iso,
    parse_remind_hours,
    parse_user_deadline,
)

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//RU
BEGIN:VEVENT
UID:evt-1@test
DTSTART:20261105T090000Z
DTEND:20261105T100000Z
SUMMARY:Lab 1
CATEGORIES:Python
END:VEVENT
BEGIN:VEVENT
UID:allday@test
DTSTART;VALUE=DATE:20261106
SUMMARY:Essay
END:VEVENT
END:VCALENDAR
"""


class LogicTests(unittest.TestCase):
    def test_url_rules(self) -> None:
        self.assertIsNone(validate_calendar_url("https://lms.astanait.edu.kz/calendar/export_execute.php?userid=1&authtoken=abc"))
        self.assertIsNotNone(validate_calendar_url("http://lms.astanait.edu.kz/calendar/export.php"))
        self.assertIsNotNone(validate_calendar_url("https://user:pass@lms.astanait.edu.kz/a.ics"))
        self.assertIsNotNone(validate_calendar_url("https://lms.astanait.edu.kz/a ics"))

    def test_parse_ics(self) -> None:
        events = parse_ics(ICS)
        self.assertEqual(len(events), 2)
        by_uid = {event["uid"]: event for event in events}
        self.assertEqual(by_uid["evt-1@test"]["dtstart"], "2026-11-05T09:00:00+00:00")
        self.assertEqual(by_uid["evt-1@test"]["course"], "Python")
        allday = parse_iso(by_uid["allday@test"]["dtstart"])
        self.assertEqual(format_almaty(allday), "06.11 00:00")

    def test_bad_ics_does_not_look_like_events(self) -> None:
        with self.assertRaises(SyncError):
            parse_ics(b"<html>nope</html>")

    def test_deadline_and_reminders(self) -> None:
        when = parse_user_deadline("2026-11-20", "18:30")
        self.assertIsNotNone(when)
        self.assertEqual(format_almaty(when), "20.11 18:30")
        self.assertIsNone(parse_user_deadline("20.11.2026", None))
        self.assertEqual(parse_remind_hours("24, 1"), [24.0, 1.0])
        self.assertEqual(parse_remind_hours("0.05"), [0.05])
        self.assertIsNone(parse_remind_hours("0,-1"))
        self.assertEqual(newly_crossed(20, [24, 1], set()), [24])
        self.assertEqual(newly_crossed(0.5, [24, 1], {24}), [1])
        self.assertEqual(newly_crossed(0.5, [24, 1], set()), [1, 24])
        self.assertEqual(newly_crossed(-0.1, [24, 1], set()), [])

    def test_database_snapshot(self) -> None:
        asyncio.run(self._database_snapshot())

    async def _database_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(str(Path(folder) / "bot.db"))
            await db.connect()
            await db.touch_user(7, "Ram")
            first = parse_ics(ICS)
            await db.replace_moodle_events(7, first)
            manual_id = await db.add_manual(7, "Read chapter", "Math", "2026-11-07T18:00:00+00:00")
            rows = await db.events_between(7, "2026-11-01T00:00:00+00:00", "2026-12-01T00:00:00+00:00")
            self.assertEqual(len(rows), 3)
            moodle = next(row for row in rows if row["uid"] == "evt-1@test")
            await db.mark_reminded(moodle["id"], [24])
            await db.hide_event(7, moodle["id"])

            changed = []
            for event in first:
                if event["uid"] == "evt-1@test":
                    start = parse_iso(event["dtstart"]) + timedelta(hours=2)
                    event = {**event, "dtstart": start.isoformat()}
                if event["uid"] != "allday@test":
                    changed.append(event)
            await db.replace_moodle_events(7, changed)

            kept = await db.get_event(7, manual_id)
            self.assertEqual(kept["source"], "manual")
            hidden = await db.get_event(7, moodle["id"])
            self.assertEqual(hidden["hidden"], 1)
            self.assertEqual(hidden["reminded_json"], "[]")
            gone = [row for row in await db.events_between(7, "2020-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00") if row["uid"] == "allday@test"]
            self.assertEqual(gone, [])
            overview = await db.admin_overview()
            self.assertNotIn("calendar_url", overview[0])
            await db.close()


if __name__ == "__main__":
    unittest.main()
