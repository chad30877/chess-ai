"""One live game, independent of pygame and batch storage."""

import random
from concurrent.futures import Executor, Future
from dataclasses import dataclass

import chess

from engine.game import create_board, get_legal_moves, get_outcome, make_move
from engine.data_ids import now_iso
from engine.strategy_config import strategy_config
from engine.players import GreedyPlayer, RandomPlayer


@dataclass(frozen=True)
class LiveSettings:
    white: str = "Random"
    black: str = "Greedy"
    seed: int = 42
    interval: float = 1.0
    initial_fen: str = chess.STARTING_FEN
    claim_draw: bool = False
    max_plies: int | None = None

    def __post_init__(self):
        if self.white not in ("Random", "Greedy", "Human") or self.black not in ("Random", "Greedy", "Human"):
            raise ValueError("Unsupported player")
        if self.interval < 0 or (self.max_plies is not None and self.max_plies < 0):
            raise ValueError("Execution limits must be non-negative")


class LiveSession:
    """The UI thread owns the board; workers receive history-preserving copies."""

    def __init__(self, settings: LiveSettings):
        self.settings = settings
        self.board = create_board(settings.initial_fen)
        self.initial_fen = self.board.fen()
        self.status = "ready"
        self.started_at = ""
        self.finished_at = ""
        self.result = "*"
        self.termination = ""
        self.error = ""
        self.move_items: list[dict] = []
        rng = random.Random(settings.seed)
        classes = {"Random": RandomPlayer, "Greedy": GreedyPlayer}
        self.players = {
            color: classes[name](rng=rng) if name != "Human" else None
            for color, name in ((chess.WHITE, settings.white), (chess.BLACK, settings.black))
        }
        self._pending: Future | None = None
        self._pending_position: tuple[str, int] | None = None
        self._step_requested = False
        self._next_due = 0.0

    @property
    def active(self) -> bool:
        return self.status in ("running", "paused")

    @property
    def human_turn(self) -> bool:
        return self.status == "running" and self.players[self.board.turn] is None

    @property
    def thinking(self) -> bool:
        return self._pending is not None and not self._pending.done()

    def start(self, now: float = 0.0) -> None:
        if self.status != "ready":
            return
        self.status = "running"
        self.started_at = now_iso()
        self._next_due = now + self.settings.interval
        self._check_ending()

    def pause(self) -> None:
        if self.status == "running":
            self.status = "paused"
            self._step_requested = False

    def resume(self) -> None:
        if self.status == "paused":
            self.status = "running"
            self._step_requested = False

    def request_step(self) -> None:
        if self.status == "paused" and self.players[self.board.turn] is not None:
            self._step_requested = True

    def cancel_pending(self) -> None:
        # A running worker may finish, but it only owns its board copy and player.
        if self._pending is not None:
            self._pending.cancel()
        self._pending = None
        self._pending_position = None
        self._step_requested = False

    def stop(self) -> None:
        if self.active:
            self.status, self.result, self.termination = "stopped", "*", "user_stop"
            self.finished_at = now_iso()
        self.cancel_pending()

    def _check_ending(self) -> None:
        outcome = get_outcome(self.board, claim_draw=self.settings.claim_draw)
        if outcome is not None:
            self.status, self.result = "completed", outcome.result()
            self.termination = outcome.termination.name.lower()
        elif self.settings.max_plies is not None and len(self.move_items) >= self.settings.max_plies:
            self.status, self.result, self.termination = "truncated", "*", "max_plies"

        if self.status in ("completed", "truncated"):
            self.finished_at = now_iso()

    def _apply(self, move: chess.Move, now: float) -> None:
        if move not in get_legal_moves(self.board):
            raise ValueError(f"Illegal move: {move}")
        item = {"ply": len(self.move_items) + 1, "move_no": self.board.fullmove_number,
                "side": "w" if self.board.turn else "b", "uci": move.uci(),
                "san": self.board.san(move)}
        make_move(self.board, move)
        self.move_items.append(item)
        self._next_due = now + self.settings.interval
        self._step_requested = False
        self._check_ending()

    def play_human(self, move: chess.Move, now: float = 0.0) -> None:
        if not self.human_turn:
            raise ValueError("It is not the human player's turn")
        self._apply(move, now)

    def legal_from(self, square: chess.Square) -> list[chess.Move]:
        if not self.human_turn:
            return []
        return [move for move in get_legal_moves(self.board) if move.from_square == square]

    def tick(self, now: float, executor: Executor) -> None:
        """Poll without blocking; a paused result waits until resume or one-step."""
        if not self.active or (self.status == "paused" and not self._step_requested):
            return
        if self.players[self.board.turn] is None:
            return
        try:
            if self._pending is None:
                if not self._step_requested and now < self._next_due:
                    return
                self._pending_position = (self.board.fen(), len(self.board.move_stack))
                self._pending = executor.submit(self.players[self.board.turn].choose_move,
                                                self.board.copy(stack=True))
            if self._pending.done():
                move = self._pending.result()
                if self._pending_position != (self.board.fen(), len(self.board.move_stack)):
                    raise ValueError("Position changed while AI was thinking")
                self._pending = None
                self._pending_position = None
                self._apply(move, now)
        except Exception as exc:
            self.cancel_pending()
            self.status, self.result, self.termination = "failed", "*", "ai_error"
            self.error = f"{type(exc).__name__}: {exc}"
            self.finished_at = now_iso()

    def replay_payload(self) -> dict:
        metadata = {
            "white_player": self.settings.white, "black_player": self.settings.black,
            "seed": self.settings.seed, "started_at": self.started_at,
            "status": self.status, "rules": {"claim_draw": self.settings.claim_draw},
            "strategies": {"white": strategy_config(self.settings.white),
                           "black": strategy_config(self.settings.black)},
            "interval_seconds": self.settings.interval,
        }
        if self.finished_at:
            metadata["finished_at"] = self.finished_at
        if self.termination:
            metadata["termination"] = self.termination
        if self.settings.max_plies is not None:
            metadata["max_plies"] = self.settings.max_plies
        if self.error:
            metadata["error"] = self.error
        return {"schema_version": 2, "initial_fen": self.initial_fen,
                "moves_uci": [item["uci"] for item in self.move_items],
                "result": self.result, "metadata": metadata}
