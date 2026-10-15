"""One live game, independent of pygame and batch storage."""

import random
from concurrent.futures import Executor, Future
from dataclasses import dataclass, replace
from threading import Event

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.game import create_board, get_legal_moves, get_outcome, make_move
from engine.storage.data_ids import now_iso
from engine.strategy_config import strategy_config
from engine.players import AlphaBetaPlayer, GreedyPlayer, RandomPlayer
from engine.search import SearchLimits
from engine.search.transposition import DEFAULT_TRANSPOSITION_CAPACITY


@dataclass(frozen=True)
class LiveSettings:
    white: str = "Random"
    black: str = "Greedy"
    seed: int = 42
    interval: float = 1.0
    initial_fen: str = chess.STARTING_FEN
    claim_draw: bool = False
    max_plies: int | None = None
    white_evaluation: EvaluationConfig | None = None
    black_evaluation: EvaluationConfig | None = None
    search_depth: int = 2
    search_workers: int = 1
    transposition_capacity: int = DEFAULT_TRANSPOSITION_CAPACITY

    def __post_init__(self):
        SearchLimits(max_depth=self.search_depth, transposition_capacity=self.transposition_capacity)
        players = ("Random", "Greedy", "AlphaBeta", "Human")
        if self.white not in players or self.black not in players:
            raise ValueError("Unsupported player")
        if self.interval < 0 or (self.max_plies is not None and self.max_plies < 0):
            raise ValueError("Execution limits must be non-negative")
        if isinstance(self.search_depth, bool) or not isinstance(self.search_depth, int) or self.search_depth < 1:
            raise ValueError("search_depth must be a positive integer")
        if isinstance(self.search_workers, bool) or not isinstance(self.search_workers, int) or self.search_workers < 1:
            raise ValueError("search_workers must be a positive integer")
        if self.white_evaluation is not None and not isinstance(self.white_evaluation, EvaluationConfig):
            raise ValueError("white_evaluation must be an EvaluationConfig")
        if self.black_evaluation is not None and not isinstance(self.black_evaluation, EvaluationConfig):
            raise ValueError("black_evaluation must be an EvaluationConfig")
        evaluated_players = ("Greedy", "AlphaBeta")
        if self.white not in evaluated_players and self.white_evaluation is not None:
            raise ValueError("white_evaluation is only valid for an evaluated player")
        if self.black not in evaluated_players and self.black_evaluation is not None:
            raise ValueError("black_evaluation is only valid for an evaluated player")


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
        evaluations = {
            chess.WHITE: settings.white_evaluation,
            chess.BLACK: settings.black_evaluation,
        }
        self.players = {
            color: self._create_player(
                name, rng, evaluations[color], settings.claim_draw, settings.search_depth, settings.search_workers,
                settings.transposition_capacity,
            ) if name != "Human" else None
            for color, name in ((chess.WHITE, settings.white), (chess.BLACK, settings.black))
        }
        self._search_stop = Event()
        self._pending: Future | None = None
        self._pending_position: tuple[str, int] | None = None
        self._step_requested = False
        self._next_due = 0.0

    @staticmethod
    def _create_player(
        name: str,
        rng: random.Random,
        evaluation: EvaluationConfig | None,
        claim_draw: bool,
        search_depth: int,
        search_workers: int = 1,
        transposition_capacity: int = DEFAULT_TRANSPOSITION_CAPACITY,
    ) -> RandomPlayer | GreedyPlayer | AlphaBetaPlayer:
        if name == "Random":
            return RandomPlayer(rng=rng)
        if name == "Greedy":
            return GreedyPlayer(config=evaluation, rng=rng, claim_draw=claim_draw)
        if name == "AlphaBeta":
            config = evaluation if evaluation is not None else EvaluationConfig()
            return AlphaBetaPlayer.from_evaluator(
                HandcraftedEvaluator(config=config),
                limits=SearchLimits(max_depth=search_depth, transposition_capacity=transposition_capacity),
                claim_draw=claim_draw,
                search_workers=search_workers,
            )
        raise ValueError(f"Unsupported AI player: {name}")

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

    def _close_players(self):
        for player in self.players.values():
            if isinstance(player, AlphaBetaPlayer):
                player.searcher.close()

    def cancel_pending(self) -> None:
        self._search_stop.set()
        pending = self._pending
        for player in self.players.values():
            if isinstance(player, AlphaBetaPlayer):
                player.searcher.cancel()
        if pending is not None:
            pending.cancel()
            pending.add_done_callback(lambda _: self._close_players())
        else:
            self._close_players()
        self._pending = None
        self._pending_position = None
        self._step_requested = False

    def _choose_move(self, board, player):
        if isinstance(player, AlphaBetaPlayer):
            result = player.searcher.search(board, replace(
                player.searcher.default_limits, stop_requested=self._search_stop.is_set))
            if result.best_move is None:
                raise ValueError("No legal move available")
            return result.best_move
        return player.choose_move(board)

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
            self._close_players()

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
                self._pending = executor.submit(self._choose_move, self.board.copy(stack=True),
                                                self.players[self.board.turn])
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
            "strategies": {
                "white": strategy_config(self.settings.white, self.players[chess.WHITE]),
                "black": strategy_config(self.settings.black, self.players[chess.BLACK]),
            },
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
