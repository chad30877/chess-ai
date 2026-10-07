"""唯讀對局紀錄索引：共用批次與非批次棋局，僅驗證過的摘要提供比較統計。"""

import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite
from pathlib import Path

from engine.replay.comparison_catalog import ComparisonSummary, load_comparison
from engine.replay.replay_catalog import _inside
from engine.storage.data_ids import date_key


def recorded_text(value):
    return value if isinstance(value, str) and value else None


def recorded_seconds(value):
    try:
        if isinstance(value, bool) or value is None or value == "":
            return None
        number = float(value)
        return number if isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RecordGame:
    game_id: str
    started_at: str | None
    white: str | None
    black: str | None
    result: str | None
    status: str | None
    termination: str | None
    elapsed_seconds: float | None
    path: Path | None
    issue: str = ""
    candidate_color: str | None = None
    outcome: str | None = None

    @property
    def date(self):
        return date_key(self.started_at)

    @property
    def result_kind(self):
        if self.status in ("failed", "stopped", "truncated") or self.result == "*":
            return "unfinished"
        return {"1-0": "win", "1/2-1/2": "draw", "0-1": "loss"}.get(self.result, "unknown")


@dataclass(frozen=True)
class RecordSummary:
    key: str
    batch_id: str
    name: str
    kind: str
    status: str | None
    created_at: str | None
    settings: dict | None
    games: tuple[RecordGame, ...]
    error: str = ""
    comparison: ComparisonSummary | None = None

    @property
    def dates(self):
        return {game.date for game in self.games} or {date_key(self.created_at)}

    @property
    def elapsed_seconds(self):
        if not self.games or any(game.elapsed_seconds is None for game in self.games):
            return None
        return sum(game.elapsed_seconds for game in self.games)

    @property
    def counts(self):
        return {kind: sum(game.result_kind == kind for game in self.games)
                for kind in ("win", "draw", "loss", "unfinished", "unknown")}

    def games_on(self, date):
        return self.games if date is None else tuple(game for game in self.games if game.date == date)


def _game(row, path, issue=""):
    return RecordGame(str(row.get("game_id") or "編號未記錄"), recorded_text(row.get("started_at")),
                      recorded_text(row.get("white_player")), recorded_text(row.get("black_player")),
                      recorded_text(row.get("result")), recorded_text(row.get("status")),
                      recorded_text(row.get("termination")), recorded_seconds(row.get("elapsed_seconds")), path, issue)


def load_batch_record(manifest_path):
    batch = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in (1, 2):
        raise ValueError("批次資訊損壞或版本不支援")
    saved = manifest["counts"]["saved_games"]
    if type(saved) is not int or saved < 0:
        raise ValueError("已發布局數無效")
    settings = manifest.get("settings")
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("保存設定損壞")
    issues = [str(manifest["error"])] if manifest.get("error") else []
    games, seen = [], set()
    try:
        with _inside(batch, manifest["files"]["games"]).open(encoding="utf-8", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if index >= saved:
                    break
                if not row.get("game_id") or row["game_id"] in seen:
                    issues.append(f"第 {index + 1} 筆棋局編號缺漏或重複")
                    continue
                seen.add(row["game_id"])
                issue = ""
                path = None
                try:
                    path = _inside(batch, row["replay_path"])
                    if not path.is_file():
                        path, issue = None, "棋譜缺漏"
                except (ValueError, TypeError, KeyError):
                    issue = "棋譜路徑損壞或越出批次目錄"
                game = _game(row, path, issue)
                if game.result not in (None, "1-0", "0-1", "1/2-1/2", "*"):
                    game = replace(game, issue="結果欄位損壞；" + issue)
                games.append(game)
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        issues.append(f"棋局索引無法完整讀取：{exc}")
    if len(games) != saved:
        issues.append(f"已發布 {saved} 局，僅可讀取 {len(games)} 筆棋局摘要")
    comparison = None
    kind = "batch"
    if ("comparison" in (settings or {}) or "comparison" in manifest.get("files", {})
            or (batch / "comparison.json").exists()):
        kind = "comparison_unavailable"
        try:
            comparison = load_comparison(manifest_path)
            indexed = {game.game_id: game for game in comparison.games}
            games = [replace(game, candidate_color=indexed[game.game_id].candidate_color,
                             outcome=indexed[game.game_id].outcome,
                             elapsed_seconds=indexed[game.game_id].elapsed_seconds) for game in games]
            kind = "comparison"
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, csv.Error) as exc:
            comparison = None
            issues.append(f"比較摘要缺漏或損壞，未套用比較統計：{exc}")
    return RecordSummary(str(batch.resolve()), str(manifest.get("batch_id") or batch.name),
                         str(manifest.get("name") or ""), kind, recorded_text(manifest.get("status")),
                         recorded_text(manifest.get("created_at")), settings, tuple(games), "；".join(issues), comparison)


def load_standalone_record(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("moves_uci"), list) or "initial_fen" not in data:
        raise ValueError("棋譜結構損壞")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("棋譜資訊損壞")
    row = dict(metadata, result=data.get("result"))
    settings = {key: metadata[key] for key in ("strategies", "rules", "seed", "interval_seconds", "max_plies")
                if key in metadata}
    return RecordSummary(str(path.resolve()), "非批次", path.name, "standalone",
                         recorded_text(metadata.get("status")), recorded_text(metadata.get("started_at")),
                         settings or None, (_game(row, path),))


class RecordsCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.refresh()

    def refresh(self):
        self.entries = []
        for path in sorted((self.root / "batches").glob("*")):
            if not path.is_dir():
                continue
            self._read(path / "manifest.json", load_batch_record, "batch", path.name)
        for path in sorted((self.root / "replays").glob("*.json")):
            self._read(path, load_standalone_record, "standalone", path.name)
        def recent(entry):
            times = [game.started_at for game in entry.games] or [entry.created_at]
            recorded = [datetime.fromisoformat(value).timestamp() for value in times
                        if date_key(value) != "日期不詳"]
            return max(recorded, default=float("-inf")), entry.key
        self.entries.sort(key=recent, reverse=True)

    def _read(self, path, loader, kind, label):
        try:
            self.entries.append(loader(path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, csv.Error) as exc:
            owner = path.parent if kind == "batch" else path
            self.entries.append(RecordSummary(str(owner.resolve()), label if kind == "batch" else "非批次",
                                "" if kind == "batch" else label, kind, None, None, None, (),
                                f"資料缺漏或損壞：{exc}"))

    @property
    def dates(self):
        return sorted({date for entry in self.entries for date in entry.dates},
                      key=lambda date: (date != "日期不詳", date), reverse=True)

    def on_date(self, date):
        return self.entries if date is None else [entry for entry in self.entries if date in entry.dates]

    def get(self, key):
        return next((entry for entry in self.entries if entry.key == key), None)
