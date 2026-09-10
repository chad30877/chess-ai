"""Alpha-beta search scaffold."""

from collections.abc import Callable
from dataclasses import dataclass
from math import inf
from time import monotonic

import chess

from engine.game import get_legal_moves
from engine.interfaces import Evaluator
from engine.search.ordering import order_moves
from engine.search.terminal import terminal_score
from engine.search.transposition import (
    BoundType,
    TranspositionEntry,
    TranspositionKey,
    TranspositionTable,
    classify_bound,
    make_transposition_key,
)
from engine.search.types import SearchLimits, SearchResult


class _SearchStopped(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _SearchContext:
    deadline: float | None
    stop_requested: Callable[[], bool] | None
    transposition_table: TranspositionTable | None
    nodes_searched: int = 0
    cutoff_count: int = 0
    depth_reached: int = 0
    transposition_hits: int = 0
    transposition_stores: int = 0

    def enter_node(self, current_depth: int) -> None:
        self.nodes_searched += 1
        self.depth_reached = max(self.depth_reached, current_depth)
        if self.stop_requested is not None and self.stop_requested():
            raise _SearchStopped("cancelled")
        if self.deadline is not None and monotonic() >= self.deadline:
            raise _SearchStopped("timeout")

    def record_cutoff(self) -> None:
        self.cutoff_count += 1

    def probe_transposition(
        self,
        key: TranspositionKey,
    ) -> TranspositionEntry | None:
        if self.transposition_table is None:
            return None
        entry = self.transposition_table.probe(key)
        if entry is not None:
            self.transposition_hits += 1
        return entry

    def store_transposition(
        self,
        key: TranspositionKey,
        entry: TranspositionEntry,
    ) -> None:
        if (
            self.transposition_table is not None
            and self.transposition_table.store(key, entry)
        ):
            self.transposition_stores += 1


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
        use_transposition_table: bool = True,
    ) -> None:
        if limits is not None and default_max_depth != 1:
            raise ValueError("Pass either limits or default_max_depth, not both.")
        if not isinstance(claim_draw, bool):
            raise ValueError("claim_draw must be a boolean.")
        if not isinstance(move_ordering, bool):
            raise ValueError("move_ordering must be a boolean.")
        if not isinstance(use_transposition_table, bool):
            raise ValueError("use_transposition_table must be a boolean.")
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
        self.use_transposition_table = use_transposition_table

    def search(self, board: chess.Board, limits: SearchLimits | None = None) -> SearchResult:
        """Search by iterative deepening and return the last completed iteration."""
        resolved_limits = limits if limits is not None else self.default_limits
        deadline = (
            monotonic() + resolved_limits.time_ms / 1000
            if resolved_limits.time_ms is not None
            else None
        )
        root_terminal = terminal_score(board, claim_draw=self.claim_draw)
        if root_terminal is not None:
            return SearchResult(
                best_move=None,
                score=root_terminal,
                depth_reached=0,
                nodes_searched=1,
                cutoff_count=0,
                completed_depth=0,
            )

        legal_moves = get_legal_moves(board)
        if self.move_ordering:
            legal_moves = order_moves(board, legal_moves)
        fallback = SearchResult(
            best_move=legal_moves[0] if legal_moves else None,
            score=self.evaluator.evaluate(board),
            depth_reached=0,
            nodes_searched=0,
            cutoff_count=0,
            completed_depth=0,
        )
        context = _SearchContext(
            deadline=deadline,
            stop_requested=resolved_limits.stop_requested,
            transposition_table=(
                TranspositionTable() if self.use_transposition_table else None
            ),
        )
        last_completed = fallback

        for target_depth in range(1, resolved_limits.max_depth + 1):
            try:
                iteration = self._search_recursive(
                    board=board,
                    depth=target_depth,
                    alpha=-inf,
                    beta=inf,
                    current_depth=0,
                    context=context,
                )
            except _SearchStopped as stopped:
                return SearchResult(
                    best_move=last_completed.best_move,
                    score=last_completed.score,
                    depth_reached=context.depth_reached,
                    nodes_searched=context.nodes_searched,
                    cutoff_count=context.cutoff_count,
                    transposition_hits=context.transposition_hits,
                    transposition_stores=context.transposition_stores,
                    completed_depth=last_completed.completed_depth,
                    stop_reason=stopped.reason,
                )
            last_completed = SearchResult(
                best_move=iteration.best_move,
                score=iteration.score,
                depth_reached=context.depth_reached,
                nodes_searched=context.nodes_searched,
                cutoff_count=context.cutoff_count,
                transposition_hits=context.transposition_hits,
                transposition_stores=context.transposition_stores,
                completed_depth=target_depth,
            )

        return last_completed

    def _search_recursive(
        self,
        board: chess.Board,
        depth: int,
        alpha: float,
        beta: float,
        current_depth: int,
        context: _SearchContext | None = None,
    ) -> SearchResult:
        """Return the best result reachable from this node via alpha-beta."""
        if context is not None:
            context.enter_node(current_depth)
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

        original_alpha = alpha
        original_beta = beta
        table_key: TranspositionKey | None = None
        preferred_move: chess.Move | None = None
        if context is not None and context.transposition_table is not None:
            table_key = make_transposition_key(
                board,
                ply_from_root=current_depth,
            )
            entry = context.probe_transposition(table_key)
            if entry is not None:
                preferred_move = entry.best_move
                if entry.depth >= max(depth, 0):
                    if entry.bound is BoundType.EXACT:
                        return SearchResult(
                            best_move=entry.best_move,
                            score=entry.score,
                            depth_reached=current_depth,
                            nodes_searched=1,
                            cutoff_count=0,
                        )
                    if entry.bound is BoundType.LOWER:
                        alpha = max(alpha, entry.score)
                    else:
                        beta = min(beta, entry.score)
                    if alpha >= beta:
                        context.record_cutoff()
                        return SearchResult(
                            best_move=entry.best_move,
                            score=entry.score,
                            depth_reached=current_depth,
                            nodes_searched=1,
                            cutoff_count=1,
                        )

        if depth <= 0:
            if self.quiescence_depth == 0:
                result = SearchResult(
                    best_move=None,
                    score=self.evaluator.evaluate(board),
                    depth_reached=current_depth,
                    nodes_searched=1,
                    cutoff_count=0,
                )
            else:
                result = self._quiescence(
                    board=board,
                    alpha=alpha,
                    beta=beta,
                    current_depth=current_depth,
                    remaining_depth=self.quiescence_depth,
                    context=context,
                    count_current=False,
                )
            self._store_transposition_result(
                context=context,
                key=table_key,
                depth=0,
                result=result,
                original_alpha=original_alpha,
                original_beta=original_beta,
            )
            return result

        legal_moves = get_legal_moves(board)
        if self.move_ordering:
            legal_moves = order_moves(
                board,
                legal_moves,
                preferred_move=preferred_move,
            )
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
                context=context,
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
                if context is not None:
                    context.record_cutoff()
                break

        result = SearchResult(
            best_move=best_move,
            score=best_score,
            depth_reached=depth_reached,
            nodes_searched=nodes_searched,
            cutoff_count=cutoff_count,
        )
        self._store_transposition_result(
            context=context,
            key=table_key,
            depth=depth,
            result=result,
            original_alpha=original_alpha,
            original_beta=original_beta,
        )
        return result

    def _quiescence(
        self,
        board: chess.Board,
        alpha: float,
        beta: float,
        current_depth: int,
        remaining_depth: int,
        context: _SearchContext | None = None,
        count_current: bool = True,
    ) -> SearchResult:
        """Extend captures/promotions and require legal evasions while in check."""

        if context is not None and count_current:
            context.enter_node(current_depth)

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
                    if context is not None:
                        context.record_cutoff()
                    return SearchResult(
                        None, best_score, current_depth, nodes_searched, 1,
                    )
                alpha = max(alpha, best_score)
            else:
                if best_score <= alpha:
                    if context is not None:
                        context.record_cutoff()
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
                if context is not None:
                    context.enter_node(current_depth + 1)
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
                    context=context,
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
                if context is not None:
                    context.record_cutoff()
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

    @staticmethod
    def _store_transposition_result(
        *,
        context: _SearchContext | None,
        key: TranspositionKey | None,
        depth: int,
        result: SearchResult,
        original_alpha: float,
        original_beta: float,
    ) -> None:
        if context is None or key is None:
            return
        context.store_transposition(
            key,
            TranspositionEntry(
                depth=max(depth, 0),
                score=result.score,
                bound=classify_bound(
                    result.score,
                    original_alpha,
                    original_beta,
                ),
                best_move=result.best_move,
            ),
        )
