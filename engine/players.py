"""Player implementations."""

import random
from collections.abc import Mapping

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.game import get_legal_moves
from engine.interfaces import Evaluator, Player
from engine.search import AlphaBetaSearcher, terminal_score
from engine.search.types import SearchLimits, Searcher


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
        config: EvaluationConfig | None = None,
        rng: random.Random | None = None,
        claim_draw: bool = False,
    ) -> None:
        if sum(value is not None for value in (evaluator, weights, config)) > 1:
            raise ValueError("Pass only one of evaluator, weights, or config.")
        if not isinstance(claim_draw, bool):
            raise ValueError("claim_draw must be a boolean.")

        self.evaluator = evaluator if evaluator is not None else HandcraftedEvaluator(
            weights=weights, config=config,
        )
        self.rng = rng
        self.claim_draw = claim_draw

    def choose_move(self, board: chess.Board) -> chess.Move:
        if terminal_score(board, claim_draw=self.claim_draw) is not None:
            raise ValueError("No legal moves available in this position.")
        legal_moves = get_legal_moves(board)
        if not legal_moves:
            raise ValueError("No legal moves available in this position.")

        is_white_to_move = board.turn == chess.WHITE
        best_score = None
        best_moves: list[chess.Move] = []

        for move in legal_moves:
            next_board = board.copy(stack=True)
            next_board.push(move)
            score = terminal_score(
                next_board,
                ply_from_root=1,
                claim_draw=self.claim_draw,
            )
            if score is None:
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


class AlphaBetaPlayer(Player):
    """A player that delegates move selection to a searcher."""

    def __init__(self, searcher: Searcher) -> None:
        self.searcher = searcher

    @classmethod
    def from_evaluator(
        cls,
        evaluator: Evaluator,
        *,
        limits: SearchLimits | None = None,
        default_max_depth: int = 1,
        claim_draw: bool = False,
        move_ordering: bool = True,
        quiescence_depth: int = 4,
        use_transposition_table: bool = True,
        use_pvs: bool = True,
        aspiration_window: float | None = 1.0,
    ) -> "AlphaBetaPlayer":
        """Build a player whose searcher owns the injected evaluator."""

        return cls(
            searcher=AlphaBetaSearcher(
                evaluator=evaluator,
                limits=limits,
                default_max_depth=default_max_depth,
                claim_draw=claim_draw,
                move_ordering=move_ordering,
                quiescence_depth=quiescence_depth,
                use_transposition_table=use_transposition_table,
                use_pvs=use_pvs,
                aspiration_window=aspiration_window,
            )
        )

    def choose_move(self, board: chess.Board) -> chess.Move:
        result = self.searcher.search(board)
        if result.best_move is None:
            raise ValueError("No legal move available in this position.")
        return result.best_move
