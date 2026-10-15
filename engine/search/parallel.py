"""根分枝程序搜尋；協調端只派工，每個程序持有自己的有界置換表。"""

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import replace
from math import inf, isfinite, nextafter
import multiprocessing
import sys
from time import monotonic

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.game import get_legal_moves
from engine.search.alphabeta import AlphaBetaSearcher, _SearchContext, _SearchStopped
from engine.search.ordering import order_moves
from engine.search.terminal import terminal_score
from engine.search.transposition import TranspositionTable
from engine.search.types import SearchResult

_worker_event = None
_STATS = ('nodes_searched', 'cutoff_count', 'transposition_hits', 'transposition_stores',
          'pvs_scouts', 'pvs_researches', 'aspiration_searches', 'aspiration_researches')


def _initialize(event):
    global _worker_event
    _worker_event = event


def _branch(evaluator_spec, options, capacity, board, move, depth, alpha, beta, deadline, scout):
    kind, config = evaluator_spec
    config = EvaluationConfig.from_dict(config)
    evaluator = (HandcraftedEvaluator(config=config) if kind == 'handcrafted'
                 else MaterialEvaluator(weights=config.piece_values))
    searcher = AlphaBetaSearcher(evaluator, **options)
    table = TranspositionTable(capacity=capacity) if searcher.use_transposition_table else None
    context = _SearchContext(deadline, _worker_event.is_set, table)
    maximizing = board.turn == chess.WHITE
    board.push(move)
    stopped = None
    try:
        scout_alpha, scout_beta = alpha, beta
        if scout:
            context.record_pvs_scout()
            if maximizing:
                scout_beta = nextafter(alpha, inf)
            else:
                scout_alpha = nextafter(beta, -inf)
        result = searcher._search_recursive(board, depth - 1, scout_alpha, scout_beta, 1, context)
        if scout and alpha < result.score < beta:
            context.record_pvs_research()
            result = searcher._search_recursive(board, depth - 1, alpha, beta, 1, context)
    except _SearchStopped as exc:
        stopped = exc.reason
        result = SearchResult(move, 0)
    return replace(result, best_move=move, depth_reached=context.depth_reached,
                   stop_reason=stopped, **{name: getattr(context, name) for name in _STATS})


class ParallelRootSearch:
    def __init__(self, owner):
        self.owner = owner
        self.context = multiprocessing.get_context('spawn')
        self.event = self.context.Event()
        self.pool = None

    def cancel(self):
        self.event.set()

    def close(self):
        self.cancel()
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None

    def search(self, board, limits):
        owner = self.owner
        evaluator = owner.evaluator
        if type(evaluator) is HandcraftedEvaluator:
            kind = 'handcrafted'
        elif type(evaluator) is MaterialEvaluator:
            kind = 'material'
        else:
            raise ValueError(f'Unsupported evaluator for process search: {type(evaluator).__name__}')
        self.evaluator_spec = kind, evaluator.config.to_dict()
        started = monotonic()
        deadline = started + limits.time_ms / 1000 if limits.time_ms is not None else None
        terminal = terminal_score(board, claim_draw=owner.claim_draw)
        if terminal is not None:
            return SearchResult(None, terminal, nodes_searched=1)
        moves = get_legal_moves(board)
        if owner.move_ordering:
            moves = order_moves(board, moves)
        last = SearchResult(moves[0], owner.evaluator.evaluate(board))
        stats = dict.fromkeys(_STATS, 0)
        reached = 0
        self.event.clear()
        options = {name: getattr(owner, name) for name in (
            'claim_draw', 'move_ordering', 'quiescence_depth', 'use_transposition_table',
            'use_pvs', 'aspiration_window')}
        workers = min(owner.search_workers, 61 if sys.platform == 'win32' else owner.search_workers)
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=workers, mp_context=self.context,
                                            initializer=_initialize, initargs=(self.event,))
        def check():
            if self.event.is_set() or (limits.stop_requested is not None and limits.stop_requested()):
                raise _SearchStopped('cancelled')
            if deadline is not None and monotonic() >= deadline:
                raise _SearchStopped('timeout')
        def iteration(depth, alpha, beta):
            nonlocal reached
            ordered = sorted(moves, key=lambda move: move != last.best_move)
            pending = {}
            index = 0
            best = None
            # 首分枝先建立界限，其餘分枝才並行，減少完整視窗的重複工作。
            while index < len(ordered) or pending:
                check()
                bound = 1 if best is None else workers
                while index < len(ordered) and len(pending) < bound:
                    move = ordered[index]; index += 1
                    future = self.pool.submit(_branch, self.evaluator_spec, options,
                                              limits.transposition_capacity, board.copy(stack=True),
                                              move, depth, alpha, beta, deadline,
                                              owner.use_pvs and best is not None and isfinite(alpha if board.turn else beta))
                    pending[future] = move
                done, _ = wait(pending, timeout=.01, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.pop(future)
                    result = future.result()
                    for name in _STATS:
                        stats[name] += getattr(result, name)
                    reached = max(reached, result.depth_reached)
                    if result.stop_reason:
                        raise _SearchStopped(result.stop_reason)
                    if best is None or (result.score > best.score if board.turn else result.score < best.score):
                        best = result
                        if board.turn:
                            alpha = max(alpha, best.score)
                        else:
                            beta = min(beta, best.score)
                if alpha >= beta:
                    # 既有在途任務要收完，才可開始下一個視窗或迭代。
                    index = len(ordered)
            stats['nodes_searched'] += 1
            return best

        try:
            for depth in range(1, limits.max_depth + 1):
                check()
                window = owner.aspiration_window
                if last.completed_depth > 0 and window is not None:
                    alpha, beta = last.score - window, last.score + window
                    stats['aspiration_searches'] += 1
                else:
                    alpha, beta = -inf, inf
                best = iteration(depth, alpha, beta)
                if (alpha != -inf or beta != inf) and (best.score <= alpha or best.score >= beta):
                    stats['aspiration_researches'] += 1
                    best = iteration(depth, -inf, inf)
                last = replace(best, completed_depth=depth, depth_reached=reached, **stats)
            return last
        except _SearchStopped as exc:
            self.close()
            return replace(last, stop_reason=exc.reason, depth_reached=reached, **stats)
        except BaseException:
            self.close()
            raise
