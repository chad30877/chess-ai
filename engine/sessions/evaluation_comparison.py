"""手工評分設定的成對比較、進度與合作式停止。"""

from dataclasses import dataclass, replace
from collections.abc import Callable
from pathlib import Path
import random
from time import perf_counter

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.players import AlphaBetaPlayer, GreedyPlayer, RandomPlayer
from engine.search import SearchLimits
from engine.sessions.self_play import PlayedGame, play_game
from engine.storage.batch_storage import BatchWriter, write_json_atomic
from engine.strategy_config import strategy_config


COMPARISON_SCHEMA_VERSION = 2
FIXED_DEPTH_BUDGET = {"mode": "fixed_depth", "depth_plies": 1}


@dataclass(frozen=True)
class ComparisonSearchConfig:
    """Shared fixed-depth Alpha-Beta settings for evaluation comparisons."""

    depth_plies: int = 2
    move_ordering: bool = True
    quiescence_depth: int = 4
    use_transposition_table: bool = True
    use_pvs: bool = True
    aspiration_window: float | None = 1.0

    def __post_init__(self) -> None:
        # Use the engine's own validators rather than a second set of rules.
        self.create_player(EvaluationConfig(), claim_draw=False)

    def create_player(self, config: EvaluationConfig, *, claim_draw: bool) -> AlphaBetaPlayer:
        return AlphaBetaPlayer.from_evaluator(
            HandcraftedEvaluator(config=config), limits=SearchLimits(max_depth=self.depth_plies),
            claim_draw=claim_draw, move_ordering=self.move_ordering,
            quiescence_depth=self.quiescence_depth, use_transposition_table=self.use_transposition_table,
            use_pvs=self.use_pvs, aspiration_window=self.aspiration_window,
        )


@dataclass(frozen=True)
class ComparisonParticipant:
    """One named side of a comparison and the strategy it actually uses."""

    label: str
    strategy: str
    evaluation_config: EvaluationConfig | None = None
    search_config: ComparisonSearchConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Comparison participant label must not be empty")
        object.__setattr__(self, "label", self.label.strip())
        if self.strategy not in ("greedy", "random", "alphabeta"):
            raise ValueError("Comparison participant strategy must be greedy, random or alphabeta")
        if self.strategy in ("greedy", "alphabeta") and not isinstance(self.evaluation_config, EvaluationConfig):
            raise ValueError("Evaluated comparison participant requires an EvaluationConfig")
        if self.strategy == "random" and self.evaluation_config is not None:
            raise ValueError("Random comparison participant cannot have evaluation settings")
        if self.strategy == "alphabeta":
            if not isinstance(self.search_config, ComparisonSearchConfig):
                raise ValueError("AlphaBeta participant requires a ComparisonSearchConfig")
        elif self.search_config is not None:
            raise ValueError("Only AlphaBeta participants can have search settings")

    @classmethod
    def greedy(cls, label: str, config: EvaluationConfig) -> "ComparisonParticipant":
        return cls(label=label, strategy="greedy", evaluation_config=config)

    @classmethod
    def random_baseline(cls, label: str = "Random") -> "ComparisonParticipant":
        return cls(label=label, strategy="random")

    @classmethod
    def alphabeta(
        cls, label: str, config: EvaluationConfig, *, search: ComparisonSearchConfig | None = None,
    ) -> "ComparisonParticipant":
        return cls(label, "alphabeta", config, search if search is not None else ComparisonSearchConfig())

    def create_player(self, rng: random.Random, *, claim_draw: bool = False):
        if self.strategy == "alphabeta":
            return self.search_config.create_player(self.evaluation_config, claim_draw=claim_draw)
        if self.strategy == "greedy":
            return GreedyPlayer(
                config=self.evaluation_config,
                rng=rng,
                claim_draw=claim_draw,
            )
        return RandomPlayer(rng=rng)

    def settings_snapshot(self, *, claim_draw: bool = False, player=None) -> dict:
        if player is None:
            player = self.create_player(random.Random(0), claim_draw=claim_draw)
        strategy_name = {"greedy": "Greedy", "random": "Random", "alphabeta": "AlphaBeta"}[self.strategy]
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


def comparison_progress(pairs: list[dict]) -> dict:
    """以完整且正常結束的配對計算累積得分，其餘配對分開列出。"""
    games = [game for pair in pairs for game in pair["games"]]
    complete = [pair for pair in pairs if len(pair["games"]) == 2
                and all(game["candidate_outcome"] != "unfinished" for game in pair["games"])]
    stats = _stats([game["candidate_outcome"] for pair in complete for game in pair["games"]])
    return dict(saved_games=len(games), completed_games=sum(game["candidate_outcome"] != "unfinished" for game in games),
                unfinished=sum(game["candidate_outcome"] == "unfinished" for game in games),
                completed_pairs=len(complete), incomplete_pairs=len(pairs) - len(complete),
                saved_pairs=sum(len(pair["games"]) == 2 for pair in pairs),
                paired_score_rate=stats.score / stats.completed_games if stats.completed_games else None)


class _ControlledPlayer:
    """取消是單次搜尋的執行訊號，不修改或隱藏固定深度設定。"""

    def __init__(self, player, control):
        self.player, self.control = player, control

    def choose_move(self, board):
        if isinstance(self.player, AlphaBetaPlayer):
            searcher = self.player.searcher
            limits = replace(searcher.default_limits, stop_requested=lambda: not self.control())
            result = searcher.search(board, limits=limits)
            if result.best_move is None:
                raise ValueError("搜尋未返回合法走法")
            return result.best_move
        return self.player.choose_move(board)


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
    control: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> ComparisonResult:
    """交換黑白比較，支援進度通知、合作式停止與逐局保存。"""

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
    if any(callback is not None and not callable(callback) for callback in (control, progress)):
        raise ValueError("control 與 progress 必須可呼叫")
    positions = _normalized_positions(initial_fens)
    evaluated = [side for side in (baseline, candidate) if side.strategy != "random"]
    if len(evaluated) == 2 and (
        evaluated[0].strategy != evaluated[1].strategy
        or evaluated[0].search_config != evaluated[1].search_config
    ):
        raise ValueError("Evaluation comparisons require identical strategies and search settings")
    budget = dict(FIXED_DEPTH_BUDGET)
    pair_count = len(positions) * repetitions
    participant_settings = {
        "baseline": baseline.settings_snapshot(claim_draw=claim_draw),
        "candidate": candidate.settings_snapshot(claim_draw=claim_draw),
    }
    actual_searches = [settings["search"] for settings in participant_settings.values()
                       if settings["strategy"] == "AlphaBeta"]
    if actual_searches:
        if any(search != actual_searches[0] for search in actual_searches):
            raise ValueError("Actual AlphaBeta search settings must be identical")
        if actual_searches[0]["claim_draw"] != claim_draw:
            raise ValueError("Actual AlphaBeta draw policy must match game rules")
        budget["depth_plies"] = actual_searches[0]["max_depth"]
    settings = {
        "num_games": pair_count * 2,
        "comparison": {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "kind": "evaluation",
            "pairing": "same_position_color_swap",
            "participants": participant_settings,
            "budget": budget,
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
    tagged = list(dict.fromkeys(["evaluation-comparison", *(tags or [])]))
    stopped = False
    current_game = 0
    last_replay = None
    writer = BatchWriter(Path(batch_root), name=name, tags=tagged, settings=settings)

    def publish():
        outcomes = [game["candidate_outcome"] for pair in pair_records for game in pair["games"]]
        candidate_stats = _stats(outcomes)
        payload = {
            "schema_version": COMPARISON_SCHEMA_VERSION, "batch_id": writer.batch_id,
            "kind": "evaluation", "budget": budget, "participants": participant_settings,
            "pairs": pair_records,
            "stats": {"candidate": candidate_stats.to_dict(), "baseline": _baseline_stats(candidate_stats).to_dict()},
            "progress": comparison_progress(pair_records),
            "note": "小樣本只驗證比較流程，不能證明棋力提升。",
        }
        if "comparison" not in writer.manifest["files"]:
            writer.add_json_artifact("comparison", "comparison.json", payload)
        else:
            write_json_atomic(writer.path / "comparison.json", payload)
        return candidate_stats

    def notify(status="running"):
        if progress:
            progress(dict(batch_id=writer.batch_id, path=str(writer.path), status=status,
                          requested_games=pair_count * 2, requested_pairs=pair_count,
                          current_game=current_game, last_replay=last_replay,
                          **comparison_progress(pair_records)))

    with writer:
        try:
            publish()
            notify()
            pair_number = 0
            for position_index, initial_fen in enumerate(positions, 1):
                for repetition in range(1, repetitions + 1):
                    if control is not None and not control():
                        stopped = True
                        break
                    pair_number += 1
                    pair_seed = base_seed + pair_number - 1
                    pair = dict(pair_number=pair_number, position_index=position_index,
                                repetition=repetition, initial_fen=initial_fen, seed=pair_seed, games=[])
                    arrangements = ((baseline, candidate, False), (candidate, baseline, True))
                    for white, black, candidate_is_white in arrangements:
                        if control is not None and not control():
                            stopped = True
                            break
                        current_game += 1
                        notify()
                        rng = random.Random(pair_seed)
                        white_player = white.create_player(rng, claim_draw=claim_draw)
                        black_player = black.create_player(rng, claim_draw=claim_draw)
                        for participant, player in ((white, white_player), (black, black_player)):
                            key = "candidate" if participant is candidate else "baseline"
                            if participant.settings_snapshot(player=player) != participant_settings[key]:
                                raise ValueError("Actual player settings changed during comparison")
                        if control is not None:
                            white_player = _ControlledPlayer(white_player, control)
                            black_player = _ControlledPlayer(black_player, control)
                        started = perf_counter()
                        game_options = dict(initial_fen=initial_fen, claim_draw=claim_draw, max_plies=max_plies)
                        if control is not None:
                            game_options["control"] = control
                        game = play_game(current_game, white_player, black_player, white.label, black.label,
                                         **game_options)
                        elapsed_seconds = perf_counter() - started
                        stored_game_id = writer.add_game(game, seed=pair_seed)
                        outcome = _game_outcome_for_candidate(game, candidate_is_white)
                        if not pair["games"]:
                            pair_records.append(pair)
                        pair["games"].append(dict(
                            game_number=current_game, game_id=stored_game_id,
                            baseline_color="black" if candidate_is_white else "white",
                            candidate_color="white" if candidate_is_white else "black",
                            result=game.result, status=game.status, termination=game.termination,
                            candidate_outcome=outcome, elapsed_seconds=elapsed_seconds,
                        ))
                        last_replay = str(writer.path / "replays" / f"{stored_game_id}.json")
                        publish()
                        notify()
                        if game.termination == "user_stop":
                            stopped = True
                            break
                    if stopped:
                        break
                if stopped:
                    break
            if stopped:
                writer.manifest["status"] = "stopped"
        finally:
            # 即使當盤失敗，也發布先前成功保存的配對與棋局。
            candidate_stats = publish()
    notify(writer.manifest["status"])
    return ComparisonResult(writer.path, candidate_stats, _baseline_stats(candidate_stats))
