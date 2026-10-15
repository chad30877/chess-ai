"""根分枝程序搜尋；協調端只派工，每個程序持有自己的有界置換表。"""

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import replace
from math import inf
import multiprocessing
import sys
from time import monotonic
from uuid import uuid4

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
_worker_state = None
_STATS = ('nodes_searched', 'cutoff_count', 'transposition_hits', 'transposition_stores',
          'pvs_scouts', 'pvs_researches', 'aspiration_searches', 'aspiration_researches')


def _initialize(event):
    global _worker_event
    _worker_event = event


def _branch(token, evaluator_spec, options, capacity, board, move, depth, alpha, beta, deadline):
    global _worker_state
    if _worker_state is None or _worker_state[0] != token:
        kind, config = evaluator_spec
        config = EvaluationConfig.from_dict(config)
        evaluator = (HandcraftedEvaluator(config=config) if kind == 'handcrafted'
                     else MaterialEvaluator(weights=config.piece_values))
        searcher = AlphaBetaSearcher(evaluator, **options)
        table = TranspositionTable(capacity=capacity) if searcher.use_transposition_table else None
        _worker_state = token, searcher, table
    _, searcher, table = _worker_state
    context = _SearchContext(deadline, _worker_event.is_set, table)
    board.push(move)
    stopped = None
    try:
        result = searcher._search_recursive(board, depth - 1, alpha, beta, 1, context)
    except _SearchStopped as exc:
        stopped = exc.reason
        result = SearchResult(move, 0)
    return replace(result, best_move=move, depth_reached=context.depth_reached,
                   stop_reason=stopped, **{name: getattr(context, name) for name in _STATS})


class ParallelRootSearch:
    def __init__(self, owner):
        self.owner = owner
        evaluator = owner.evaluator
        if type(evaluator) is HandcraftedEvaluator:
            kind = 'handcrafted'
        elif type(evaluator) is MaterialEvaluator:
            kind = 'material'
        else:
            raise ValueError(f'Unsupported evaluator for process search: {type(evaluator).__name__}')
        self.evaluator_spec = kind, evaluator.config.to_dict()
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
        token = uuid4().hex
        options = {name: getattr(owner, name) for name in (
            'claim_draw', 'move_ordering', 'quiescence_depth', 'use_transposition_table',
            'use_pvs', 'aspiration_window')}
        workers = min(owner.search_workers, len(moves), 61 if sys.platform == 'win32' else owner.search_workers)
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=workers, mp_context=self.context,
                                            initializer=_initialize, initargs=(self.event,))
        def check():
            if self.event.is_set() or (limits.stop_requested is not None and limits.stop_requested()):
                raise _SearchStopped('cancelled')
            if deadline is not None and monotonic() >= deadline:
                raise _SearchStopped('timeout')
        try:
            for depth in range(1, limits.max_depth + 1):
                check()
                ordered = sorted(moves, key=lambda move: move != last.best_move)
                pending = {}
                index = 0
                best = None
                alpha, beta = -inf, inf
                # 首分枝先建立界限，其餘分枝才並行，減少完整視窗的重複工作。
                while index < len(ordered) or pending:
                    check()
                    bound = 1 if best is None else workers
                    while index < len(ordered) and len(pending) < bound:
                        move = ordered[index]; index += 1
                        future = self.pool.submit(_branch, token, self.evaluator_spec, options,
                                                  limits.transposition_capacity, board.copy(stack=True),
                                                  move, depth, alpha, beta, deadline)
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
                                alpha = best.score
                            else:
                                beta = best.score
                stats['nodes_searched'] += 1
                last = replace(best, completed_depth=depth, depth_reached=reached, **stats)
            return last
        except _SearchStopped as exc:
            self.close()
            return replace(last, stop_reason=exc.reason, depth_reached=reached, **stats)
        except BaseException:
            self.close()
            raise
