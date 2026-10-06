"""Read published comparison summaries without loading positions or replay moves."""

import csv
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from engine.replay.replay_catalog import _inside


@dataclass(frozen=True)
class ComparisonGame:
    game_id: str
    candidate_color: str
    outcome: str
    result: str
    termination: str
    elapsed_seconds: float
    path: Path | None


@dataclass(frozen=True)
class ComparisonSummary:
    batch_id: str
    name: str
    status: str
    participants: dict
    budget: dict
    games: tuple[ComparisonGame, ...]
    wins: int
    draws: int
    losses: int
    unfinished: int

    @property
    def score_rate(self) -> float | None:
        completed = self.wins + self.draws + self.losses
        return (self.wins + 0.5 * self.draws) / completed if completed else None

    @property
    def elapsed_seconds(self) -> float:
        return sum(game.elapsed_seconds for game in self.games)


def load_comparison(manifest_path: Path) -> ComparisonSummary:
    """Reject inconsistent summaries; missing replays leave results viewable."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch = manifest_path.parent
    if manifest["schema_version"] not in (1, 2):
        raise ValueError("不支援的批次版本")
    comparison = json.loads(_inside(batch, manifest["files"]["comparison"]).read_text(encoding="utf-8"))
    if comparison["schema_version"] not in (1, 2) or comparison["kind"] != "evaluation":
        raise ValueError("不支援的比較版本或類型")
    if comparison["batch_id"] != manifest["batch_id"]:
        raise ValueError("比較與批次編號不一致")
    settings = manifest["settings"]["comparison"]
    participants = comparison["participants"]
    budget = comparison["budget"]
    if participants != settings["participants"] or budget != settings["budget"]:
        raise ValueError("比較與批次的實際設定不一致")
    for side in ("candidate", "baseline"):
        participant = participants[side]
        if not isinstance(participant["label"], str) or not participant["label"]:
            raise ValueError("缺少參與者名稱")
        if not isinstance(participant.get("strategy"), str):
            raise ValueError("缺少玩家策略")
        if participant["strategy"] != "Random" and not isinstance(participant.get("evaluator"), dict):
            raise ValueError("缺少實際評分設定")
        if participant["strategy"] == "AlphaBeta" and not isinstance(participant.get("search"), dict):
            raise ValueError("缺少實際搜尋設定")
    if budget["mode"] != "fixed_depth" or type(budget["depth_plies"]) is not int or budget["depth_plies"] < 1:
        raise ValueError("不支援或無效的搜尋預算")
    saved = manifest["counts"]["saved_games"]
    if type(saved) is not int or saved < 0:
        raise ValueError("無效的已保存局數")
    with _inside(batch, manifest["files"]["games"]).open(encoding="utf-8", newline="") as stream:
        rows = []
        for row in csv.DictReader(stream):
            if len(rows) >= saved:
                break
            rows.append(row)
    indexed = {row["game_id"]: row for row in rows}
    if len(indexed) != saved:
        raise ValueError("已發布的棋局清單缺漏或重複")
    games = []
    seen = set()
    counts = {"win": 0, "draw": 0, "loss": 0, "unfinished": 0}
    for pair in comparison["pairs"]:
        pair_games = pair["games"]
        if not isinstance(pair_games, list) or not 1 <= len(pair_games) <= 2:
            raise ValueError("無效的配對棋局數")
        if len({game["candidate_color"] for game in pair_games}) != len(pair_games):
            raise ValueError("配對未交換候選方顏色")
        for game in pair["games"]:
            game_id = game["game_id"]
            if game_id in seen or game_id not in indexed:
                raise ValueError("比較棋局缺漏或重複")
            seen.add(game_id)
            row = indexed[game_id]
            color = game["candidate_color"]
            if color not in ("white", "black") or game["baseline_color"] != ("black" if color == "white" else "white"):
                raise ValueError("無效的配對顏色")
            for key in ("result", "status", "termination"):
                if game[key] != row[key]:
                    raise ValueError("比較結果與棋局摘要不一致")
            for side in ("candidate", "baseline"):
                if row[game[f"{side}_color"] + "_player"] != participants[side]["label"]:
                    raise ValueError("棋局玩家與比較設定不一致")
            result = game["result"]
            if result not in ("1-0", "0-1", "1/2-1/2", "*"):
                raise ValueError("無效的棋局結果")
            outcome = "unfinished"
            if game["status"] == "completed" and result != "*":
                outcome = "draw" if result == "1/2-1/2" else (
                    "win" if (result == "1-0") == (color == "white") else "loss")
            if game["candidate_outcome"] != outcome:
                raise ValueError("候選方勝負標記不一致")
            elapsed = game["elapsed_seconds"]
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not isfinite(elapsed) or elapsed < 0:
                raise ValueError("無效的對局耗時")
            path = _inside(batch, row["replay_path"])
            games.append(ComparisonGame(game_id, color, outcome, result, game["termination"], elapsed,
                                        path if path.is_file() else None))
            counts[outcome] += 1
    if seen != set(indexed):
        raise ValueError("比較摘要未涵蓋所有已發布棋局")
    expected = {"wins": counts["win"], "draws": counts["draw"], "losses": counts["loss"],
                "unfinished": counts["unfinished"]}
    expected["completed_games"] = expected["wins"] + expected["draws"] + expected["losses"]
    expected["score"] = expected["wins"] + 0.5 * expected["draws"]
    for side in ("candidate", "baseline"):
        stats = comparison["stats"][side]
        if any(type(stats[key]) is not int or stats[key] < 0
               for key in ("wins", "draws", "losses", "unfinished", "completed_games")):
            raise ValueError("無效的勝負統計")
    if comparison["stats"]["candidate"] != expected:
        raise ValueError("候選方統計與逐局結果不一致")
    baseline = {**expected, "wins": expected["losses"], "losses": expected["wins"],
                "score": expected["losses"] + 0.5 * expected["draws"]}
    if comparison["stats"]["baseline"] != baseline:
        raise ValueError("基準方統計與逐局結果不一致")
    return ComparisonSummary(manifest["batch_id"], str(manifest.get("name", "")),
                             manifest["status"], participants, budget, tuple(games),
                             counts["win"], counts["draw"], counts["loss"], counts["unfinished"])


class ComparisonCatalog:
    def __init__(self, root: Path):
        self.root = root
        self.refresh()

    def refresh(self):
        self.entries: list[ComparisonSummary] = []
        self.errors: list[str] = []
        for path in sorted((self.root / "batches").glob("*/manifest.json"), reverse=True):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if not (manifest.get("settings", {}).get("comparison")
                        or "comparison" in manifest.get("files", {}) or (path.parent / "comparison.json").exists()):
                    continue
                self.entries.append(load_comparison(path))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error) as exc:
                self.errors.append(f"{path.parent.name}：比較資料缺漏或損壞（{exc}）")
