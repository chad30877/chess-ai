"""Read published comparison summaries without loading positions or replay moves."""

import csv
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from engine.replay.replay_catalog import _inside
from engine.sessions.evaluation_comparison import comparison_progress


@dataclass(frozen=True)
class ComparisonGame:
    game_id: str
    candidate_color: str
    candidate_index: int
    candidate_label: str
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
    completed_pairs: int
    incomplete_pairs: int
    paired_score_rate: float | None
    candidate_summaries: tuple[dict, ...]
    error: str

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
    if comparison["schema_version"] not in (1, 2, 3) or comparison["kind"] != "evaluation":
        raise ValueError("不支援的比較版本或類型")
    if comparison["batch_id"] != manifest["batch_id"]:
        raise ValueError("比較與批次編號不一致")
    settings = manifest["settings"]["comparison"]
    participants = comparison["participants"]
    raw_participants = participants
    if comparison["schema_version"] == 3:
        if not isinstance(participants.get("baseline"), dict) or not isinstance(participants.get("candidates"), list) or len(participants["candidates"]) < 2:
            raise ValueError("多候選比較設定缺漏")
        participants = {"baseline": participants["baseline"], "candidates": participants["candidates"],
                        "candidate": participants["candidates"][0]}
    budget = comparison["budget"]
    if raw_participants != settings["participants"] or budget != settings["budget"]:
        raise ValueError("比較與批次的實際設定不一致")
    for side in (("baseline", *[f"candidate_{i + 1}" for i in range(len(participants["candidates"]))])
                 if comparison["schema_version"] == 3 else ("candidate", "baseline")):
        participant = (participants["baseline"] if side == "baseline" else
                       participants["candidates"][int(side.split("_")[1]) - 1]
                       if comparison["schema_version"] == 3 else participants[side])
        if not isinstance(participant["label"], str) or not participant["label"]:
            raise ValueError("缺少參與者名稱")
        if not isinstance(participant.get("strategy"), str):
            raise ValueError("缺少玩家策略")
        if participant["strategy"] != "Random" and not isinstance(participant.get("evaluator"), dict):
            raise ValueError("缺少實際評分設定")
        if participant["strategy"] == "AlphaBeta" and not isinstance(participant.get("search"), dict):
            raise ValueError("缺少實際搜尋設定")
    if comparison["schema_version"] == 3:
        evaluated = participants["candidates"]
        if any(item["strategy"] != evaluated[0]["strategy"] for item in evaluated[1:]):
            raise ValueError("多候選策略不一致")
        if evaluated[0]["strategy"] == "AlphaBeta" and any(
                item.get("search") != evaluated[0].get("search") for item in evaluated[1:]):
            raise ValueError("多候選搜尋條件不一致")
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
    count_by_candidate = [{"win": 0, "draw": 0, "loss": 0, "unfinished": 0}
                          for _ in range(len(participants.get("candidates", [None])))]
    for pair in comparison["pairs"]:
        candidate_index = pair.get("candidate_index", 0)
        if type(candidate_index) is not int or not 0 <= candidate_index < len(count_by_candidate):
            raise ValueError("無效的候選編號")
        candidate_participant = (participants["candidates"][candidate_index]
                                 if comparison["schema_version"] == 3 else participants["candidate"])
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
            for side, participant in (("candidate", candidate_participant), ("baseline", participants["baseline"])):
                if row[game[f"{side}_color"] + "_player"] != participant["label"]:
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
            games.append(ComparisonGame(game_id, color, candidate_index, candidate_participant["label"], outcome, result, game["termination"], elapsed,
                                        path if path.is_file() else None))
            count_by_candidate[candidate_index][outcome] += 1
    if seen != set(indexed):
        raise ValueError("比較摘要未涵蓋所有已發布棋局")
    expected_all = []
    for counts in count_by_candidate:
        expected = {"wins": counts["win"], "draws": counts["draw"], "losses": counts["loss"],
                    "unfinished": counts["unfinished"]}
        expected["completed_games"] = expected["wins"] + expected["draws"] + expected["losses"]
        expected["score"] = expected["wins"] + 0.5 * expected["draws"]
        expected_all.append(expected)
    for side in (("candidates", "baseline") if comparison["schema_version"] == 3 else ("candidate", "baseline")):
        stats_values = comparison["stats"][side] if side == "candidates" else [comparison["stats"][side]]
        if not isinstance(stats_values, list):
            stats_values = [stats_values]
        for stats in stats_values:
            if any(type(stats[key]) is not int or stats[key] < 0
                   for key in ("wins", "draws", "losses", "unfinished", "completed_games")):
                raise ValueError("無效的勝負統計")
    if comparison["schema_version"] == 3:
        if comparison["stats"]["candidates"] != expected_all:
            raise ValueError("候選方統計與逐局結果不一致")
        combined = {key: sum(stat[key] for stat in expected_all) for key in
                    ("wins", "draws", "losses", "unfinished", "completed_games", "score")}
        baseline = {**combined, "wins": combined["losses"], "losses": combined["wins"],
                    "score": combined["losses"] + 0.5 * combined["draws"]}
    else:
        if comparison["stats"]["candidate"] != expected_all[0]:
            raise ValueError("候選方統計與逐局結果不一致")
        baseline = {**expected_all[0], "wins": expected_all[0]["losses"],
                    "losses": expected_all[0]["wins"], "score": expected_all[0]["losses"] + 0.5 * expected_all[0]["draws"]}
    if comparison["stats"]["baseline"] != baseline:
        raise ValueError("基準方統計與逐局結果不一致")
    progress = comparison_progress([p for p in comparison["pairs"] if p.get("candidate_index", 0) == 0])
    summaries = []
    for index, (participant, counts) in enumerate(zip(
            participants.get("candidates", [participants["candidate"]]), count_by_candidate)):
        candidate_progress = comparison_progress([p for p in comparison["pairs"]
                                                   if p.get("candidate_index", 0) == index])
        summaries.append({"label": participant["label"], "wins": counts["win"], "draws": counts["draw"],
                          "losses": counts["loss"], "unfinished": counts["unfinished"],
                          "completed_pairs": candidate_progress["completed_pairs"],
                          "incomplete_pairs": candidate_progress["incomplete_pairs"],
                          "paired_score_rate": candidate_progress["paired_score_rate"]})
    return ComparisonSummary(manifest["batch_id"], str(manifest.get("name", "")),
                             manifest["status"], participants, budget, tuple(games),
                             count_by_candidate[0]["win"], count_by_candidate[0]["draw"], count_by_candidate[0]["loss"], count_by_candidate[0]["unfinished"],
                             progress["completed_pairs"], progress["incomplete_pairs"], progress["paired_score_rate"],
                             tuple(summaries),
                             str(manifest.get("error", "")))


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
