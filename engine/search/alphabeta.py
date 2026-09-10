"""Alpha-beta search scaffold."""

from math import inf

import chess

from engine.game import get_legal_moves
from engine.interfaces import Evaluator
from engine.search.ordering import order_moves
from engine.search.terminal import terminal_score
from engine.search.types import SearchLimits, SearchResult


class AlphaBetaSearcher:
    """Alpha-beta searcher driven by an injected evaluator."""

    def __init__(
        self,
        evaluator: Evaluator,
        limits: SearchLimits | None = None,
        default_max_depth: int = 1,
        claim_draw: bool = False,
        move_ordering: bool = True,
        quiescence_depth: int = 4,
    ) -> None:
        if limits is not None and default_max_depth != 1:
            raise ValueError("Pass either limits or default_max_depth, not both.")
        if not isinstance(claim_draw, bool):
            raise ValueError("claim_draw must be a boolean.")
        if not isinstance(move_ordering, bool):
            raise ValueError("move_ordering must be a boolean.")
        if (
            isinstance(quiescence_depth, bool)
            or not isinstance(quiescence_depth, int)
            or quiescence_depth < 0
        ):
            raise ValueError("quiescence_depth must be a non-negative integer.")

        self.evaluator = evaluator
        self.default_limits = limits if limits is not None else SearchLimits(max_depth=default_max_depth)
        self.claim_draw = claim_draw
        self.move_ordering = move_ordering
        self.quiescence_depth = quiescence_depth

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
        score = terminal_score(
            board,
            ply_from_root=current_depth,
            claim_draw=self.claim_draw,
        )
        if score is not None:
            return SearchResult(
                best_move=None,
                score=score,
                depth_reached=current_depth,
                nodes_searched=1,
                cutoff_count=0,
            )
        if depth <= 0:
            if self.quiescence_depth == 0:
                return SearchResult(
                    best_move=None,
                    score=self.evaluator.evaluate(board),
                    depth_reached=current_depth,
                    nodes_searched=1,
                    cutoff_count=0,
                )
            return self._quiescence(
                board=board,
                alpha=alpha,
                beta=beta,
                current_depth=current_depth,
                remaining_depth=self.quiescence_depth,
            )

        legal_moves = get_legal_moves(board)
        if self.move_ordering:
            legal_moves = order_moves(board, legal_moves)
        is_maximizing = board.turn == chess.WHITE
        best_move: chess.Move | None = None
        best_score = -inf if is_maximizing else inf
        depth_reached = current_depth
        nodes_searched = 1
        cutoff_count = 0

        for move in legal_moves:
            next_board = board.copy(stack=True)
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

    def _quiescence(
        self,
        board: chess.Board,
        alpha: float,
        beta: float,
        current_depth: int,
        remaining_depth: int,
    ) -> SearchResult:
        """Extend captures/promotions and require legal evasions while in check."""

        terminal = terminal_score(
            board,
            ply_from_root=current_depth,
            claim_draw=self.claim_draw,
        )
        if terminal is not None:
            return SearchResult(
                best_move=None,
                score=terminal,
                depth_reached=current_depth,
                nodes_searched=1,
                cutoff_count=0,
            )

        in_check = board.is_check()
        if remaining_depth <= 0 and not in_check:
            return SearchResult(
                best_move=None,
                score=self.evaluator.evaluate(board),
                depth_reached=current_depth,
                nodes_searched=1,
                cutoff_count=0,
            )

        is_maximizing = board.turn == chess.WHITE
        best_move: chess.Move | None = None
        nodes_searched = 1
        cutoff_count = 0
        depth_reached = current_depth

        if in_check:
            best_score = -inf if is_maximizing else inf
            candidate_moves = get_legal_moves(board)
        else:
            best_score = self.evaluator.evaluate(board)
            if is_maximizing:
                if best_score >= beta:
                    return SearchResult(
                        None, best_score, current_depth, nodes_searched, 1,
                    )
                alpha = max(alpha, best_score)
            else:
                if best_score <= alpha:
                    return SearchResult(
                        None, best_score, current_depth, nodes_searched, 1,
                    )
                beta = min(beta, best_score)
            candidate_moves = [
                move
                for move in get_legal_moves(board)
                if board.is_capture(move) or move.promotion is not None
            ]

        if self.move_ordering:
            candidate_moves = order_moves(board, candidate_moves)

        for move in candidate_moves:
            next_board = board.copy(stack=True)
            next_board.push(move)
            if remaining_depth <= 0:
                child_result = SearchResult(
                    best_move=None,
                    score=self._evaluate_leaf(next_board, current_depth + 1),
                    depth_reached=current_depth + 1,
                    nodes_searched=1,
                    cutoff_count=0,
                )
            else:
                child_result = self._quiescence(
                    board=next_board,
                    alpha=alpha,
                    beta=beta,
                    current_depth=current_depth + 1,
                    remaining_depth=remaining_depth - 1,
                )

            nodes_searched += child_result.nodes_searched
            cutoff_count += child_result.cutoff_count
            depth_reached = max(depth_reached, child_result.depth_reached)

            if is_maximizing and child_result.score > best_score:
                best_move = move
                best_score = child_result.score
            elif (not is_maximizing) and child_result.score < best_score:
                best_move = move
                best_score = child_result.score

            if is_maximizing:
                alpha = max(alpha, best_score)
            else:
                beta = min(beta, best_score)
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
        score = terminal_score(
            board,
            ply_from_root=current_depth,
            claim_draw=self.claim_draw,
        )
        return score if score is not None else self.evaluator.evaluate(board)
