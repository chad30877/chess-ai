"""Date/group/game lookup; batch indexes never load training positions."""

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from engine.data_ids import TAIPEI, date_key


@dataclass(frozen=True)
class ReplayEntry:
    date: str
    group: str
    group_label: str
    game_id: str
    started_at: str
    white: str
    black: str
    result: str
    status: str
    path: Path

    @property
    def time_label(self):
        if self.date == "日期不詳":
            return "時間不詳"
        return datetime.fromisoformat(self.started_at).astimezone(TAIPEI).strftime("%H:%M:%S")


def result_badges(result: str):
    """Outcome colors follow the winner, independently of piece color or strategy."""
    neutral, win, incomplete = (163, 175, 191), (108, 210, 158), (239, 184, 89)
    return {"1-0": (("勝", win), ("敗", neutral)),
            "0-1": (("敗", neutral), ("勝", win)),
            "1/2-1/2": (("和", neutral), ("和", neutral))}.get(
                result, (("未完成", incomplete), ("未完成", incomplete)))


def _inside(root: Path, relative: str):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Replay path leaves its batch")
    return path


class ReplayCatalog:
    PAGE_SIZE = 5

    def __init__(self, root: Path):
        self.root = root
        self.entries: list[ReplayEntry] = []
        self.date = self.group = None
        self.selected = None
        self.offset = 0
        self.error = ""
        self.refresh()

    def refresh(self):
        self.entries = []
        self.skipped = 0
        for manifest_path in sorted((self.root / "batches").glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("schema_version") not in (1, 2):
                    raise ValueError("Unknown batch version")
                batch = manifest_path.parent
                batch_id = str(manifest["batch_id"])
                label = batch_id + (" · " + manifest["name"] if manifest.get("name") else "")
                with _inside(batch, manifest["files"]["games"]).open(newline="", encoding="utf-8") as stream:
                    for index, row in enumerate(csv.DictReader(stream)):
                        if index >= int(manifest["counts"]["saved_games"]):
                            break
                        try:
                            path = _inside(batch, row["replay_path"])
                            if not path.is_file():
                                raise ValueError("Missing replay")
                            self._append(row, path, batch_id, label)
                        except (ValueError, TypeError, KeyError):
                            self.skipped += 1
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                self.skipped += 1
        for path in sorted((self.root / "replays").glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("moves_uci"), list) or "initial_fen" not in data:
                    raise ValueError("Not a replay")
                row = dict(data.get("metadata", {}))
                row["result"] = data.get("result", "*")
                self._append(row, path, "standalone", "非批次")
            except (OSError, ValueError, TypeError):
                self.skipped += 1
        self.entries.sort(key=lambda e: (
            datetime.fromisoformat(e.started_at).timestamp() if e.date != "日期不詳" else float("-inf"),
            e.game_id), reverse=True)
        self.offset = 0
        self.selected = None

    def _append(self, row, path, group, label):
        timestamp = row.get("started_at", "") or ""
        if not isinstance(timestamp, str):
            timestamp = ""
        self.entries.append(ReplayEntry(date_key(timestamp), group, label,
                            str(row.get("game_id", "編號不詳")), timestamp,
                            str(row.get("white_player", "未知")), str(row.get("black_player", "未知")),
                            str(row.get("result", "*")), str(row.get("status", "")), path))

    @property
    def level(self):
        return "date" if self.date is None else "group" if self.group is None else "game"

    def options(self):
        if self.level == "date":
            return sorted({e.date for e in self.entries}, key=lambda d: (d != "日期不詳", d), reverse=True)
        entries = [e for e in self.entries if e.date == self.date]
        if self.level == "group":
            return list(dict.fromkeys((e.group, e.group_label) for e in entries))
        return [e for e in entries if e.group == self.group]

    def choose(self, index):
        option = self.options()[index]
        if self.level == "date":
            self.date = option
        elif self.level == "group":
            self.group = option[0]
        else:
            self.selected = index
            return
        self.offset = 0
        self.selected = None

    def back(self):
        if self.group is not None:
            self.group = None
        else:
            self.date = None
        self.offset = 0
        self.selected = None

    def scroll(self, amount):
        self.offset = max(0, min(self.offset + amount, max(0, len(self.options()) - self.PAGE_SIZE)))

    def selected_entry(self):
        options = self.options()
        return options[self.selected] if self.level == "game" and self.selected is not None and self.selected < len(options) else None
