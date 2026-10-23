"""一般批次的固定顏色政策與逐局保存，背景控制使用共用執行機制。"""

import random
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from engine.sessions.batch_execution import BatchExecution
from engine.sessions.batch_workers import general_player, own_player
from engine.sessions.evaluation_comparison import _ControlledPlayer
from engine.search import SearchLimits
from engine.search.transposition import DEFAULT_TRANSPOSITION_CAPACITY
from engine.sessions.parallel_batch import actual_workers, run_parallel

import chess

from engine.evaluation.config import EvaluationConfig
from engine.storage.batch_storage import BatchWriter
from engine.players import AlphaBetaPlayer, GreedyPlayer, RandomPlayer
from engine.sessions.self_play import play_game
from engine.strategy_config import strategy_config


@dataclass(frozen=True)
class BatchSettings:
    white: str = "Random"
    black: str = "Greedy"
    games: int = 20
    interval: float = 0.0  # Delay between games, never between plies.
    initial_fen: str = chess.STARTING_FEN
    claim_draw: bool = False
    max_plies: int | None = None
    white_evaluation: EvaluationConfig | None = None
    black_evaluation: EvaluationConfig | None = None
    workers: int = 1
    base_seed: int | None = None
    search_depth: int = 2
    search_workers: int = 1
    transposition_capacity: int = DEFAULT_TRANSPOSITION_CAPACITY

    def __post_init__(self):
        actual_workers(self.workers, self.games)
        SearchLimits(max_depth=self.search_depth, transposition_capacity=self.transposition_capacity)
        if isinstance(self.search_workers, bool) or not isinstance(self.search_workers, int) or self.search_workers < 1:
            raise ValueError("搜尋 worker 數需為正整數")
        if self.base_seed is not None and (isinstance(self.base_seed, bool)
                or not isinstance(self.base_seed, int) or self.base_seed < 0):
            raise ValueError("base_seed 必須為非負整數")
        if self.white not in ("Random", "Greedy", "AlphaBeta") or self.black not in ("Random", "Greedy", "AlphaBeta"):
            raise ValueError("Batch players must be AI strategies")
        if self.games <= 0 or self.interval < 0 or (self.max_plies is not None and self.max_plies < 0):
            raise ValueError("Invalid batch count or execution limit")
        if self.white_evaluation is not None and not isinstance(self.white_evaluation, EvaluationConfig):
            raise ValueError("white_evaluation must be an EvaluationConfig")
        if self.black_evaluation is not None and not isinstance(self.black_evaluation, EvaluationConfig):
            raise ValueError("black_evaluation must be an EvaluationConfig")
        if self.white not in ("Greedy", "AlphaBeta") and self.white_evaluation is not None:
            raise ValueError("white_evaluation is only valid for Greedy or AlphaBeta")
        if self.black not in ("Greedy", "AlphaBeta") and self.black_evaluation is not None:
            raise ValueError("black_evaluation is only valid for Greedy or AlphaBeta")


class BatchRun(BatchExecution):
    def __init__(self, settings: BatchSettings, root: Path, executor):
        self.settings = settings
        self.root = root
        super().__init__(executor, requested_games=settings.games, waiting_work=settings.games,
                         requested_workers=settings.workers,
                         actual_workers=actual_workers(settings.workers, settings.games))

    def _interval(self):
        return self._wait_interval(self.settings.interval)

    def _execute(self):
        s = self.settings
        workers = actual_workers(s.workers, s.games)
        base_seed = s.base_seed if s.base_seed is not None else random.SystemRandom().randrange(2**63)
        with ExitStack() as stack:
            templates = {}
            for side in ("white", "black"):
                templates[side] = own_player(stack, self._create_player(
                    getattr(s, side), random.Random(0), getattr(s, side + "_evaluation"), s.claim_draw,
                    s.search_depth, s.search_workers, s.transposition_capacity))
            settings = dict(initial_fen=s.initial_fen, rules={"claim_draw": s.claim_draw},
                            strategies={side: strategy_config(getattr(s, side), templates[side])
                                        for side in ("white", "black")},
                            color_assignment="fixed", interval_seconds=s.interval, workers=workers,
                            requested_workers=s.workers, base_seed=base_seed,
                            seed_derivation="base_seed + work_number - 1", publication_order="arrival")
        if s.max_plies is not None:
            settings["max_plies"] = s.max_plies
        with BatchWriter(self.root, name=None, tags=[], settings={"num_games": s.games, **settings}) as writer:
            self._progress(dict(batch_id=writer.batch_id, path=str(writer.path)))
            def save(number, game, seed, elapsed):
                logical_number = game.game_id
                game = replace(game, game_id=writer.manifest["counts"]["saved_games"] + 1)
                game_id = writer.add_game(game, seed=seed,
                                          execution=dict(work_number=number, game_number=logical_number))
                counts = writer.manifest["counts"]
                self._progress(dict(saved_games=counts["saved_games"],
                                    completed_games=counts["completed_games"],
                                    unfinished=counts["saved_games"] - counts["completed_games"],
                                    last_replay=str(writer.path / "replays" / f"{game_id}.json")))

            if workers > 1:
                player_settings = dict(search_depth=s.search_depth, search_workers=s.search_workers,
                                       transposition_capacity=s.transposition_capacity, white=s.white, black=s.black, claim_draw=s.claim_draw, max_plies=s.max_plies,
                                       white_evaluation=s.white_evaluation.to_dict() if s.white_evaluation else None,
                                       black_evaluation=s.black_evaluation.to_dict() if s.black_evaluation else None)
                stopped = run_parallel(work_count=s.games, workers=workers,
                                       make_work=lambda n: dict(number=n, kind="general", seed=base_seed + n - 1,
                                                                initial_fen=s.initial_fen, settings=player_settings),
                                       on_game=save, progress=self._progress, control=self._dispatch_control,
                                       paused=self._is_paused, bind_control=self._bind_process_control, interval=s.interval)
                if stopped:
                    writer.manifest["status"] = "stopped"
            else:
                self._run_serial(writer, base_seed, save)
        self._progress(dict(status=writer.manifest["status"]))
        return writer.path

    def _run_serial(self, writer, base_seed, save):
        s = self.settings
        for number in range(1, s.games + 1):
            if not self._control():
                break
            self._progress(dict(current_game=number, waiting_work=s.games - number, running_work=1))
            seed = base_seed + number - 1
            rng = random.Random(seed)
            with ExitStack() as stack:
                players = []
                for side in ("white", "black"):
                    player = own_player(stack, self._create_player(getattr(s, side), rng,
                        getattr(s, side + "_evaluation"), s.claim_draw, s.search_depth,
                        s.search_workers, s.transposition_capacity))
                    players.append(_ControlledPlayer(player, self._dispatch_control))
                game = play_game(number, *players, s.white, s.black, initial_fen=s.initial_fen,
                                 claim_draw=s.claim_draw, max_plies=s.max_plies, control=self._control,
                                 progress=lambda state: self._progress(dict(active_games={number: state})))
            self._progress(dict(active_games={}))
            save(number, game, seed, 0)
            self._progress(dict(running_work=0, finished_work=number, finished_games=number))
            if number < s.games and not self._interval():
                break
        if self._stopped:
            writer.manifest["status"] = "stopped"


    @staticmethod
    def _create_player(
        name: str,
        rng: random.Random,
        evaluation: EvaluationConfig | None,
        claim_draw: bool,
        search_depth=2, search_workers=1, transposition_capacity=DEFAULT_TRANSPOSITION_CAPACITY,
    ) -> RandomPlayer | GreedyPlayer | AlphaBetaPlayer:
        return general_player(name, rng, evaluation, claim_draw, search_depth, search_workers, transposition_capacity)
