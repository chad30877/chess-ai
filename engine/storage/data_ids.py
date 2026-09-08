"""Taipei timestamps and persistent, process-safe daily serial numbers."""

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="microseconds")


def date_key(timestamp: str) -> str:
    try:
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is None:
            return "日期不詳"
        return value.astimezone(TAIPEI).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "日期不詳"


def allocate_id(data_root: Path, kind: str, timestamp: str) -> str:
    """IDs are never reused, including after a failed/abandoned write."""
    if kind not in ("game", "batch"):
        raise ValueError("kind must be game or batch")
    day = date_key(timestamp).replace("-", "")
    if not re.fullmatch(r"\d{8}", day):
        raise ValueError("A timestamp with a timezone is required")
    data_root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data_root / ".sequences.sqlite3", timeout=15)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS counters (kind TEXT, day TEXT, value INTEGER, PRIMARY KEY(kind, day))")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM counters WHERE kind=? AND day=?", (kind, day)).fetchone()
        if row is None:
            # Recover safely if a data directory was copied without its counter file.
            suffix = r"\.json" if kind == "game" else ""
            pattern = re.compile(rf"{day}_(\d+){suffix}$")
            existing = (data_root.rglob(f"{day}_*.json") if kind == "game"
                        else (p for p in data_root.rglob(f"{day}_*") if p.is_dir()))
            maximum = max((int(m.group(1)) for p in existing if (m := pattern.fullmatch(p.name))), default=0)
        else:
            maximum = row[0]
        number = maximum + 1
        db.execute("INSERT OR REPLACE INTO counters VALUES (?, ?, ?)", (kind, day, number))
    return f"{day}_{number:0{6 if kind == 'game' else 4}d}"
