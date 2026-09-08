"""Replay session utilities for move-by-move navigation."""

import chess

from engine.game import create_board, get_outcome, get_result, make_move


class ReplaySession:
    """Store replay positions and provide navigation over plies."""

    def __init__(
        self, initial_fen: str, moves_uci: list[str], *, claim_draw: bool = False
    ) -> None:
        board = create_board(initial_fen)
        self.claim_draw = claim_draw

        self.positions: list[str] = [initial_fen]
        self.current_ply = 0

        for move_uci in moves_uci:
            move = chess.Move.from_uci(move_uci)
            make_move(board, move)
            self.positions.append(board.fen())

        # Keep one complete history; FEN snapshots are only a display cache.
        self._final_board = board

    def current_board(self) -> chess.Board:
        board = self._final_board.copy(stack=True)
        while len(board.move_stack) > self.current_ply:
            board.pop()
        return board

    def current_outcome(self) -> chess.Outcome | None:
        return get_outcome(self.current_board(), claim_draw=self.claim_draw)

    def current_result(self) -> str:
        return get_result(self.current_board(), claim_draw=self.claim_draw)

    def first(self) -> None:
        self.current_ply = 0

    def last(self) -> None:
        self.current_ply = self.total_ply()

    def next(self) -> None:
        if self.current_ply < self.total_ply():
            self.current_ply += 1

    def prev(self) -> None:
        if self.current_ply > 0:
            self.current_ply -= 1

    def goto_ply(self, i: int) -> None:
        if not 0 <= i <= self.total_ply():
            raise IndexError(f"ply out of range: {i}")
        self.current_ply = i

    def current_fen(self) -> str:
        return self.positions[self.current_ply]

    def total_ply(self) -> int:
        return len(self.positions) - 1
