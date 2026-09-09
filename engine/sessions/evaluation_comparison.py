"""Paired, color-swapped comparisons for handcrafted evaluation settings."""

from dataclasses import dataclass
from pathlib import Path
import random
from time import perf_counter

import chess

from engine.evaluation.config import EvaluationConfig
from engine.players import GreedyPlayer, RandomPlayer
from engine.sessions.self_play import PlayedGame, play_game
from engine.storage.batch_storage import BatchWriter
from engine.strategy_config import strategy_config


COMPARISON_SCHEMA_VERSION = 1
FIXED_DEPTH_BUDGET = {"mode": "fixed_depth", "depth_plies": 1}


@dataclass(frozen=True)
class ComparisonParticipant:
    """One named side of a comparison and the strategy it actually uses."""

    label: str
    strategy: str
    evaluation_config: EvaluationConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Comparison participant label must not be empty")
        object.__setattr__(self, "label", self.label.strip())
        if self.strategy not in ("greedy", "random"):
            raise ValueError("Comparison participant strategy must be greedy or random")
        if self.strategy == "greedy" and not isinstance(self.evaluation_config, EvaluationConfig):
            raise ValueError("Greedy comparison participant requires an EvaluationConfig")
        if self.strategy == "random" and self.evaluation_config is not None:
            raise ValueError("Random comparison participant cannot have evaluation settings")

    @classmethod
    def greedy(cls, label: str, config: EvaluationConfig) -> "ComparisonParticipant":
        return cls(label=label, strategy="greedy", evaluation_config=config)

    @classmethod
    def random_baseline(cls, label: str = "Random") -> "ComparisonParticipant":
        return cls(label=label, strategy="random")

    def create_player(self, rng: random.Random):
        if self.strategy == "greedy":
            return GreedyPlayer(config=self.evaluation_config, rng=rng)
        return RandomPlayer(rng=rng)

    def settings_snapshot(self) -> dict:
        player = self.create_player(random.Random(0))
        strategy_name = "Greedy" if self.strategy == "greedy" else "Random"
        return {"label": self.label, **strategy_config(strategy_name, player)}


@dataclass(frozen=True)
class ComparisonStats:
    wins: int = 0
    draws: int = 0
    losses: int = 0
    unfinished: int = 0

    @property
    def completed_games(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def score(self) -> float:
        return self.wins + self.draws * 0.5

    def to_dict(self) -> dict:
        return {
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "unfinished": self.unfinished,
            "completed_games": self.completed_games,
            "score": self.score,
        }


@dataclass(frozen=True)
class ComparisonResult:
    path: Path
    candidate_stats: ComparisonStats
    baseline_stats: ComparisonStats


def _normalized_positions(initial_fens: list[str] | tuple[str, ...]) -> list[str]:
    if not initial_fens:
        raise ValueError("At least one initial FEN is required")
    normalized = []
    for fen in initial_fens:
        try:
            board = chess.Board(fen)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid initial FEN: {fen}") from exc
        if not board.is_valid():
            raise ValueError(f"Invalid standard chess position: {fen}")
        normalized.append(board.fen())
    return normalized


def _game_outcome_for_candidate(game: PlayedGame, candidate_is_white: bool) -> str:
    if game.status != "completed" or game.result == "*":
        return "unfinished"
    if game.result == "1/2-1/2":
        return "draw"
    candidate_won = (game.result == "1-0") == candidate_is_white
    return "win" if candidate_won else "loss"


def _stats(outcomes: list[str]) -> ComparisonStats:
    return ComparisonStats(
        wins=outcomes.count("win"),
        draws=outcomes.count("draw"),
        losses=outcomes.count("loss"),
        unfinished=outcomes.count("unfinished"),
    )


def _baseline_stats(candidate: ComparisonStats) -> ComparisonStats:
    return ComparisonStats(
        wins=candidate.losses,
        draws=candidate.draws,
        losses=candidate.wins,
        unfinished=candidate.unfinished,
    )


def run_evaluation_comparison(
    *,
    baseline: ComparisonParticipant,
    candidate: ComparisonParticipant,
    initial_fens: list[str] | tuple[str, ...] = (chess.STARTING_FEN,),
    repetitions: int = 1,
    base_seed: int = 10_000,
    batch_root: Path = Path("data/batches"),
    name: str | None = None,
    tags: list[str] | None = None,
    claim_draw: bool = False,
    max_plies: int | None = None,
) -> ComparisonResult:
    """Run two games per position/repetition, swapping participant colors."""

    if not isinstance(baseline, ComparisonParticipant) or not isinstance(
        candidate, ComparisonParticipant,
    ):
        raise ValueError("baseline and candidate must be ComparisonParticipant values")
    if baseline.label == candidate.label:
        raise ValueError("Baseline and candidate labels must be different")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("repetitions must be greater than 0")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) or base_seed < 0:
        raise ValueError("base_seed must be a non-negative integer")
    if max_plies is not None and (
        isinstance(max_plies, bool) or not isinstance(max_plies, int) or max_plies < 0
    ):
        raise ValueError("max_plies must be non-negative")
    if not isinstance(claim_draw, bool):
        raise ValueError("claim_draw must be a boolean")
    positions = _normalized_positions(initial_fens)
    pair_count = len(positions) * repetitions
    participant_settings = {
        "baseline": baseline.settings_snapshot(),
        "candidate": candidate.settings_snapshot(),
    }
    settings = {
        "num_games": pair_count * 2,
        "comparison": {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "kind": "evaluation",
            "pairing": "same_position_color_swap",
            "participants": participant_settings,
            "budget": dict(FIXED_DEPTH_BUDGET),
            "base_seed": base_seed,
            "seed_derivation": "base_seed + pair_number - 1; reset for each color-swapped game",
            "initial_fens": positions,
            "repetitions": repetitions,
        },
        "rules": {"claim_draw": claim_draw},
        "color_assignment": "paired_swap",
        "workers": 1,
    }
    if max_plies is not None:
        settings["max_plies"] = max_plies

    pair_records = []
    candidate_outcomes: list[str] = []
    tagged = list(dict.fromkeys(["evaluation-comparison", *(tags or [])]))
    with BatchWriter(
        Path(batch_root), name=name, tags=tagged, settings=settings,
    ) as writer:
        pair_number = 0
        game_number = 0
        for position_index, initial_fen in enumerate(positions, 1):
            for repetition in range(1, repetitions + 1):
                pair_number += 1
                pair_seed = base_seed + pair_number - 1
                games = []
                arrangements = (
                    (baseline, candidate, False),
                    (candidate, baseline, True),
                )
                for white, black, candidate_is_white in arrangements:
                    game_number += 1
                    rng = random.Random(pair_seed)
                    started = perf_counter()
                    game = play_game(
                        game_number,
                        white.create_player(rng),
                        black.create_player(rng),
                        white.label,
                        black.label,
                        initial_fen=initial_fen,
                        claim_draw=claim_draw,
                        max_plies=max_plies,
                    )
                    elapsed_seconds = perf_counter() - started
                    stored_game_id = writer.add_game(game, seed=pair_seed)
                    outcome = _game_outcome_for_candidate(game, candidate_is_white)
                    candidate_outcomes.append(outcome)
                    games.append({
                        "game_number": game_number,
                        "game_id": stored_game_id,
                        "baseline_color": "black" if candidate_is_white else "white",
                        "candidate_color": "white" if candidate_is_white else "black",
                        "result": game.result,
                        "status": game.status,
                        "termination": game.termination,
                        "candidate_outcome": outcome,
                        "elapsed_seconds": elapsed_seconds,
                    })
                pair_records.append({
                    "pair_number": pair_number,
                    "position_index": position_index,
                    "repetition": repetition,
                    "initial_fen": initial_fen,
                    "seed": pair_seed,
                    "games": games,
                })

        candidate_stats = _stats(candidate_outcomes)
        baseline_stats = _baseline_stats(candidate_stats)
        comparison_payload = {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "batch_id": writer.batch_id,
            "kind": "evaluation",
            "budget": dict(FIXED_DEPTH_BUDGET),
            "participants": participant_settings,
            "pairs": pair_records,
            "stats": {
                "candidate": candidate_stats.to_dict(),
                "baseline": baseline_stats.to_dict(),
            },
            "note": "Small samples validate the comparison flow; they do not prove playing strength.",
        }
        comparison_filename = "comparison.json"
        writer.add_json_artifact("comparison", comparison_filename, comparison_payload)

    return ComparisonResult(
        path=writer.path,
        candidate_stats=candidate_stats,
        baseline_stats=baseline_stats,
    )
