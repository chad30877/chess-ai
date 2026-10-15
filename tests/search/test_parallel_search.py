import unittest
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from time import monotonic, sleep
import chess
from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.search.types import CHECKMATE_SCORE

class ParallelSearchTests(unittest.TestCase):
    def test_spawn_finds_mate_with_original_root_distance_and_preserves_board(self):
        board = chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1')
        original = board.fen()
        searcher = AlphaBetaSearcher(MaterialEvaluator(), search_workers=2)
        try:
            result = searcher.search(board, SearchLimits(max_depth=2))
            after = board.copy(); after.push(result.best_move)
            self.assertTrue(after.is_checkmate())
            self.assertEqual(result.score, CHECKMATE_SCORE - 1)
            self.assertEqual(result.completed_depth, 2)
            self.assertEqual(board.fen(), original)
        finally:
            searcher.close()

    def test_spawn_uses_full_repetition_history_in_child_branch(self):
        board = chess.Board('6nk/8/8/8/8/8/Q7/KN6 w - - 0 1')
        cycle = ('b1c3', 'g8f6', 'c3b1', 'f6g8')
        for move in cycle * 3 + cycle[:3]:
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        searcher = AlphaBetaSearcher(MaterialEvaluator(), search_workers=2, quiescence_depth=0)
        try:
            result = searcher.search(board, SearchLimits(max_depth=1))
            self.assertEqual(result.best_move.uci(), 'f6g8')
            self.assertEqual(result.score, 0)
            self.assertEqual((board.fen(), board.move_stack), before)
            without_history = searcher.search(chess.Board(board.fen()), SearchLimits(max_depth=1))
            self.assertGreater(without_history.score, 0)
        finally:
            searcher.close()

    def test_stop_and_timeout_return_completed_iterations_and_pool_can_restart(self):
        searcher = AlphaBetaSearcher(MaterialEvaluator(), search_workers=2, quiescence_depth=0)
        before = {child.pid for child in multiprocessing.active_children()}
        try:
            searcher.search(chess.Board(), SearchLimits(max_depth=1))
            deadline = monotonic() + .2
            result = searcher.search(chess.Board(), SearchLimits(
                max_depth=10, stop_requested=lambda: monotonic() >= deadline))
            self.assertEqual(result.stop_reason, 'cancelled')
            self.assertGreaterEqual(result.completed_depth, 1)
            self.assertLess(result.completed_depth, 10)
            self.assertEqual(result.score, 0)
            self.assertTrue({child.pid for child in multiprocessing.active_children()} <= before)
            timed = searcher.search(chess.Board(), SearchLimits(max_depth=10, time_ms=1))
            self.assertEqual(timed.stop_reason, 'timeout')
            restarted = searcher.search(chess.Board(), SearchLimits(max_depth=1))
            self.assertEqual(restarted.completed_depth, 1)
        finally:
            searcher.close()
        self.assertTrue({child.pid for child in multiprocessing.active_children()} <= before)

    def test_worker_process_failure_is_reported_and_other_workers_join(self):
        before = {child.pid for child in multiprocessing.active_children()}
        searcher = AlphaBetaSearcher(MaterialEvaluator(), search_workers=2, quiescence_depth=0)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(searcher.search, chess.Board(), SearchLimits(max_depth=10))
                deadline = monotonic() + 10
                children = []
                while not children and monotonic() < deadline:
                    children = [child for child in multiprocessing.active_children() if child.pid not in before]
                    sleep(.01)
                self.assertTrue(children, '搜尋應建立真實程序')
                children[0].terminate()
                with self.assertRaises(BrokenProcessPool):
                    future.result(timeout=10)
        finally:
            searcher.close()
        self.assertTrue({child.pid for child in multiprocessing.active_children()} <= before)

    def test_process_search_rejects_custom_evaluator_without_replacing_it(self):
        class CustomMaterial(MaterialEvaluator):
            def evaluate(self, board):
                return 123.0
        searcher = AlphaBetaSearcher(CustomMaterial(), search_workers=2)
        try:
            with self.assertRaisesRegex(ValueError, 'Unsupported evaluator'):
                searcher.search(chess.Board())
        finally:
            searcher.close()
