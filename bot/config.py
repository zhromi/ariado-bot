from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int | None
    admin_ids: frozenset[int]
    db_path: str


def _parse_id(value: str) -> int | None:
    value = value.strip()
    if not value or not value.isdigit():
        return None
    return int(value)


def load_settings() -> Settings:
    load_env()
    admins: set[int] = set()
    for piece in os.getenv("ADMIN_USER_IDS", "").split(","):
        parsed = _parse_id(piece)
        if parsed is not None:
            admins.add(parsed)
    return Settings(
        token=os.getenv("DISCORD_TOKEN", "").strip(),
        guild_id=_parse_id(os.getenv("GUILD_ID", "")),
        admin_ids=frozenset(admins),
        db_path=os.getenv("DB_PATH", str(ROOT / "data" / "bot.db")),
    )
