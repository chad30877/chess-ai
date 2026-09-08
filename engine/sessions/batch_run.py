"""Background batch execution with cooperative pause and durable per-game saves."""

import random
from dataclasses import dataclass
from pathlib import Path
from threading import Condition
from time import monotonic

import chess

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

    def __post_init__(self):
        if self.white not in ("Random", "Greedy") or self.black not in ("Random", "Greedy"):
            raise ValueError("Batch players must be AI strategies")
        if self.games <= 0 or self.interval < 0 or (self.max_plies is not None and self.max_plies < 0):
            raise ValueError("Invalid batch count or execution limit")


class BatchRun:
    def __init__(self, settings: BatchSettings, root: Path, executor):
        self.settings = settings
        self.root = root
        self._condition = Condition()
        self._paused = self._stopped = False
        self._state = dict(status="running", current_game=0, saved_games=0,
                           requested_games=settings.games, batch_id="", error="")
        self.future = executor.submit(self._run)

    def snapshot(self):
        with self._condition:
            return dict(self._state)

    def pause(self):
        with self._condition:
            if self._state["status"] == "running":
                self._paused = True
                self._state["status"] = "paused"
                self._condition.notify_all()

    def resume(self):
        with self._condition:
            if self._paused and not self._stopped:
                self._paused = False
                self._state["status"] = "running"
                self._condition.notify_all()

    def stop(self):
        with self._condition:
            if self._state["status"] in ("running", "paused"):
                self._stopped = True
                self._state["status"] = "stopping"
                self._condition.notify_all()

    def _control(self):
        with self._condition:
            while self._paused and not self._stopped:
                self._condition.wait()
            return not self._stopped

    def _interval(self):
        remaining = self.settings.interval
        with self._condition:
            while remaining > 0 and not self._stopped:
                if self._paused:
                    self._condition.wait()
                    continue
                start = monotonic()
                self._condition.wait(timeout=remaining)
                remaining -= monotonic() - start
        return self._control()

    def _run(self):
        s = self.settings
        settings = dict(initial_fen=s.initial_fen, rules={"claim_draw": s.claim_draw},
                        strategies={"white": strategy_config(s.white), "black": strategy_config(s.black)},
                        color_assignment="fixed", interval_seconds=s.interval, workers=1)
        if s.max_plies is not None:
            settings["max_plies"] = s.max_plies
        try:
            with BatchWriter(self.root, name=None, tags=[], settings={"num_games": s.games, **settings}) as writer:
                with self._condition:
                    self._state["batch_id"] = writer.batch_id
                classes = {"Random": RandomPlayer, "Greedy": GreedyPlayer}
                for number in range(1, s.games + 1):
                    if not self._control():
                        break
                    with self._condition:
                        self._state["current_game"] = number
                    seed = random.SystemRandom().randrange(2**63)
                    rng = random.Random(seed)
                    game = play_game(number, classes[s.white](rng=rng), classes[s.black](rng=rng),
                                     s.white, s.black, initial_fen=s.initial_fen,
                                     claim_draw=s.claim_draw, max_plies=s.max_plies, control=self._control)
                    writer.add_game(game, seed=seed)
                    with self._condition:
                        self._state["saved_games"] = number
                    if number < s.games and not self._interval():
                        break
                if self._stopped:
                    writer.manifest["status"] = "stopped"
            with self._condition:
                self._state["status"] = writer.manifest["status"]
        except Exception as exc:
            with self._condition:
                self._state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
