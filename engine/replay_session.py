"""Replay session utilities for move-by-move navigation."""

import chess


class ReplaySession:
    """Store replay positions and provide navigation over plies."""

    def __init__(self, initial_fen: str, moves_uci: list[str]) -> None:
        board = chess.Board(initial_fen)

        self.positions: list[str] = [initial_fen]
        self.current_ply = 0

        for move_uci in moves_uci:
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                raise ValueError(f"Illegal move for replay session: {move_uci}")
            board.push(move)
            self.positions.append(board.fen())

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
