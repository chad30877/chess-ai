"""Alpha-beta search scaffold."""

from math import inf

import chess

from engine.game import get_legal_moves
from engine.interfaces import Evaluator
from engine.search.types import CHECKMATE_SCORE, DRAW_SCORE, SearchLimits, SearchResult


class AlphaBetaSearcher:
    """Alpha-beta searcher driven by an injected evaluator."""

    def __init__(
        self,
        evaluator: Evaluator,
        limits: SearchLimits | None = None,
        default_max_depth: int = 1,
    ) -> None:
        if limits is not None and default_max_depth != 1:
            raise ValueError("Pass either limits or default_max_depth, not both.")

        self.evaluator = evaluator
        self.default_limits = limits if limits is not None else SearchLimits(max_depth=default_max_depth)

    def search(self, board: chess.Board, limits: SearchLimits | None = None) -> SearchResult:
        """Search the position with depth-limited alpha-beta.

        Time controls will be added in later tasks.
        """
        resolved_limits = limits if limits is not None else self.default_limits
        return self._search_recursive(
            board=board,
            depth=resolved_limits.max_depth,
            alpha=-inf,
            beta=inf,
            current_depth=0,
        )

    def _search_recursive(
        self,
        board: chess.Board,
        depth: int,
        alpha: float,
        beta: float,
        current_depth: int,
    ) -> SearchResult:
        """Return the best result reachable from this node via alpha-beta."""
        if depth <= 0 or board.is_game_over():
            return SearchResult(
                best_move=None,
                score=self._evaluate_leaf(board, current_depth),
                depth_reached=current_depth,
                nodes_searched=1,
                cutoff_count=0,
            )

        legal_moves = get_legal_moves(board)
        is_maximizing = board.turn == chess.WHITE
        best_move: chess.Move | None = None
        best_score = -inf if is_maximizing else inf
        depth_reached = current_depth
        nodes_searched = 1
        cutoff_count = 0

        for move in legal_moves:
            next_board = board.copy(stack=False)
            next_board.push(move)
            child_result = self._search_recursive(
                board=next_board,
                depth=depth - 1,
                alpha=alpha,
                beta=beta,
                current_depth=current_depth + 1,
            )

            nodes_searched += child_result.nodes_searched
            depth_reached = max(depth_reached, child_result.depth_reached)
            cutoff_count += child_result.cutoff_count

            if best_move is None:
                best_move = move
                best_score = child_result.score
            elif is_maximizing and child_result.score > best_score:
                best_move = move
                best_score = child_result.score
            elif (not is_maximizing) and child_result.score < best_score:
                best_move = move
                best_score = child_result.score

            if is_maximizing:
                alpha = max(alpha, best_score)
            else:
                beta = min(beta, best_score)

            # Once the window closes, no later sibling can improve the parent result.
            if alpha >= beta:
                cutoff_count += 1
                break

        return SearchResult(
            best_move=best_move,
            score=best_score,
            depth_reached=depth_reached,
            nodes_searched=nodes_searched,
            cutoff_count=cutoff_count,
        )

    def _evaluate_leaf(self, board: chess.Board, current_depth: int = 0) -> float:
        """Evaluate a leaf node with shared terminal-scoring rules."""

        if board.is_checkmate():
            mate_score = CHECKMATE_SCORE - current_depth
            return mate_score if board.turn == chess.BLACK else -mate_score

        if (
            board.is_stalemate()
            or board.is_insufficient_material()
            or board.is_seventyfive_moves()
            or board.is_fivefold_repetition()
        ):
            return DRAW_SCORE

        return self.evaluator.evaluate(board)
