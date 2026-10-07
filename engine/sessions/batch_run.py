"""一般批次的固定顏色政策與逐局保存，背景控制使用共用執行機制。"""

import random
from dataclasses import dataclass
from pathlib import Path
from engine.sessions.batch_execution import BatchExecution

import chess

from engine.evaluation.config import EvaluationConfig
from engine.storage.batch_storage import BatchWriter
from engine.players import GreedyPlayer, RandomPlayer
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

    def __post_init__(self):
        if self.white not in ("Random", "Greedy") or self.black not in ("Random", "Greedy"):
            raise ValueError("Batch players must be AI strategies")
        if self.games <= 0 or self.interval < 0 or (self.max_plies is not None and self.max_plies < 0):
            raise ValueError("Invalid batch count or execution limit")
        if self.white_evaluation is not None and not isinstance(self.white_evaluation, EvaluationConfig):
            raise ValueError("white_evaluation must be an EvaluationConfig")
        if self.black_evaluation is not None and not isinstance(self.black_evaluation, EvaluationConfig):
            raise ValueError("black_evaluation must be an EvaluationConfig")
        if self.white != "Greedy" and self.white_evaluation is not None:
            raise ValueError("white_evaluation is only valid for Greedy")
        if self.black != "Greedy" and self.black_evaluation is not None:
            raise ValueError("black_evaluation is only valid for Greedy")


class BatchRun(BatchExecution):
    def __init__(self, settings: BatchSettings, root: Path, executor):
        self.settings = settings
        self.root = root
        super().__init__(executor, requested_games=settings.games)

    def _interval(self):
        return self._wait_interval(self.settings.interval)

    def _execute(self):
        s = self.settings
        templates = {
            "white": self._create_player(
                s.white, random.Random(0), s.white_evaluation, s.claim_draw,
            ),
            "black": self._create_player(
                s.black, random.Random(0), s.black_evaluation, s.claim_draw,
            ),
        }
        settings = dict(initial_fen=s.initial_fen, rules={"claim_draw": s.claim_draw},
                        strategies={"white": strategy_config(s.white, templates["white"]),
                                    "black": strategy_config(s.black, templates["black"])},
                        color_assignment="fixed", interval_seconds=s.interval, workers=1)
        if s.max_plies is not None:
            settings["max_plies"] = s.max_plies
        with BatchWriter(self.root, name=None, tags=[], settings={"num_games": s.games, **settings}) as writer:
            self._progress(dict(batch_id=writer.batch_id, path=str(writer.path)))
            for number in range(1, s.games + 1):
                if not self._control():
                    break
                self._progress(dict(current_game=number))
                seed = random.SystemRandom().randrange(2**63)
                rng = random.Random(seed)
                game = play_game(
                    number,
                    self._create_player(s.white, rng, s.white_evaluation, s.claim_draw),
                    self._create_player(s.black, rng, s.black_evaluation, s.claim_draw),
                    s.white, s.black, initial_fen=s.initial_fen,
                    claim_draw=s.claim_draw, max_plies=s.max_plies, control=self._control,
                )
                game_id = writer.add_game(game, seed=seed)
                counts = writer.manifest["counts"]
                self._progress(dict(saved_games=counts["saved_games"],
                                    completed_games=counts["completed_games"],
                                    unfinished=counts["saved_games"] - counts["completed_games"],
                                    last_replay=str(writer.path / "replays" / f"{game_id}.json")))
                if number < s.games and not self._interval():
                    break
            if self._stopped:
                writer.manifest["status"] = "stopped"
        self._progress(dict(status=writer.manifest["status"]))
        return writer.path

    @staticmethod
    def _create_player(
        name: str,
        rng: random.Random,
        evaluation: EvaluationConfig | None,
        claim_draw: bool,
    ) -> RandomPlayer | GreedyPlayer:
        if name == "Random":
            return RandomPlayer(rng=rng)
        if name == "Greedy":
            return GreedyPlayer(config=evaluation, rng=rng, claim_draw=claim_draw)
        raise ValueError(f"Unsupported batch player: {name}")
