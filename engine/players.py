"""Player implementations."""

import random
from collections.abc import Mapping

import chess

from engine.evaluator import MaterialEvaluator
from engine.game import get_legal_moves
from engine.interfaces import Evaluator, Player


class RandomPlayer(Player):
    """A player that picks one legal move uniformly at random."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal_moves = get_legal_moves(board)
        if not legal_moves:
            raise ValueError("No legal moves available in this position.")
        if self.rng is not None:
            return self.rng.choice(legal_moves)
        return random.choice(legal_moves)


class GreedyPlayer(Player):
    """One-ply player that selects the best move according to an evaluator."""

    def __init__(
        self,
        evaluator: Evaluator | None = None,
        weights: Mapping[int | str, float] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if evaluator is not None and weights is not None:
            raise ValueError("Pass either evaluator or weights, not both.")

        self.evaluator = evaluator if evaluator is not None else MaterialEvaluator(weights=weights)
        self.rng = rng

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal_moves = get_legal_moves(board)
        if not legal_moves:
            raise ValueError("No legal moves available in this position.")

        is_white_to_move = board.turn == chess.WHITE
        best_score = None
        best_moves: list[chess.Move] = []

        for move in legal_moves:
            next_board = board.copy(stack=False)
            next_board.push(move)
            score = self.evaluator.evaluate(next_board)

            if best_score is None:
                best_score = score
                best_moves = [move]
                continue

            if is_white_to_move and score > best_score:
                best_score = score
                best_moves = [move]
            elif (not is_white_to_move) and score < best_score:
                best_score = score
                best_moves = [move]
            elif score == best_score:
                best_moves.append(move)

        if self.rng is not None:
            return self.rng.choice(best_moves)
        return random.choice(best_moves)
