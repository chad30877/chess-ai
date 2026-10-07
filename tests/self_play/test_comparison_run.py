"""驗證比較進度、停止、失敗保存及背景搜尋取消。"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event
import tempfile
import unittest
from unittest.mock import patch

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.replay.comparison_catalog import load_comparison
from engine.sessions.comparison_run import ComparisonRun
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, run_evaluation_comparison
from engine.sessions.self_play import play_game
from engine.search import AlphaBetaSearcher
from engine.replay.replay_loader import load_replay_json
from tests.helpers.executors import ManualExecutor


WIN = "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"


class ComparisonRunTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        search = ComparisonSearchConfig(depth_plies=2)
        self.options = dict(baseline=ComparisonParticipant.alphabeta("baseline", EvaluationConfig(), search=search),
                            candidate=ComparisonParticipant.alphabeta("candidate", EvaluationConfig(phase_enabled=True), search=search),
                            initial_fens=(WIN,), repetitions=2, batch_root=self.root / "batches", base_seed=42)

    def test_progress_advances_rate_only_after_both_games_complete(self):
        states = []
        result = run_evaluation_comparison(**self.options, progress=states.append)
        saved = {state["saved_games"]: state for state in states}
        self.assertIsNone(saved[1]["paired_score_rate"])
        self.assertEqual(saved[1]["incomplete_pairs"], 1)
        self.assertEqual(saved[2]["paired_score_rate"], 0.5)
        self.assertEqual(saved[2]["completed_pairs"], 1)
        self.assertEqual(saved[4]["completed_pairs"], 2)
        self.assertEqual(states[-1]["status"], "completed")
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(summary.completed_pairs, 2)
        self.assertEqual(summary.incomplete_pairs, 0)

    def test_stop_between_colors_preserves_orphan_without_scoring_pair(self):
        stop = Event()
        def progress(state):
            if state["saved_games"] == 1:
                stop.set()
        result = run_evaluation_comparison(**self.options, control=lambda: not stop.is_set(), progress=progress)
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(summary.status, "stopped")
        self.assertEqual(len(summary.games), 1)
        self.assertEqual(summary.losses, 1)
        self.assertEqual(summary.unfinished, 0)
        self.assertEqual(summary.incomplete_pairs, 1)
        self.assertIsNone(summary.paired_score_rate)

    def test_stop_after_complete_pair_does_not_start_next_pair(self):
        stop = Event()
        result = run_evaluation_comparison(**self.options, control=lambda: not stop.is_set(),
                    progress=lambda state: stop.set() if state["saved_games"] == 2 else None)
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(len(summary.games), 2)
        self.assertEqual(summary.completed_pairs, 1)
        self.assertEqual(summary.incomplete_pairs, 0)

    def test_queued_stop_still_publishes_empty_stopped_batch(self):
        executor = ManualExecutor()
        run = ComparisonRun(self.options, executor)
        run.stop()
        self.assertEqual(run.snapshot()["status"], "stopping")
        executor.finish()
        state = run.snapshot()
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(state["saved_games"], 0)
        summary = load_comparison(Path(state["path"]) / "manifest.json")
        self.assertEqual(summary.games, ())
        self.assertIsNone(summary.paired_score_rate)

    def test_real_worker_stop_reaches_search_and_preserves_actual_settings(self):
        options = {**self.options, "initial_fens": (chess.STARTING_FEN,)}
        entered, release = Event(), Event()
        evaluate = HandcraftedEvaluator.evaluate
        def blocking(evaluator, board):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("測試未釋放 evaluator")
            return evaluate(evaluator, board)
        with ThreadPoolExecutor(max_workers=1) as executor, patch.object(HandcraftedEvaluator, "evaluate", blocking):
            run = ComparisonRun(options, executor)
            try:
                self.assertTrue(entered.wait(5))
                run.stop()
            finally:
                release.set()
            run.future.result(timeout=5)
        state = run.snapshot()
        self.assertEqual(state["status"], "stopped")
        self.assertEqual((state["saved_games"], state["unfinished"], state["incomplete_pairs"]), (1, 1, 1))
        summary = load_comparison(Path(state["path"]) / "manifest.json")
        self.assertEqual(summary.games[0].termination, "user_stop")
        self.assertEqual(summary.games[0].result, "*")
        self.assertEqual(summary.participants["candidate"]["search"]["max_depth"], 2)
        replay = json.loads(summary.games[0].path.read_text(encoding="utf-8"))
        self.assertEqual(replay["initial_fen"], chess.STARTING_FEN)
        self.assertEqual(replay["moves_uci"], [])

    def test_failure_after_first_game_keeps_published_result_and_error(self):
        executor = ManualExecutor()
        run = ComparisonRun(self.options, executor)
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("模擬第二局搜尋失敗")
            return play_game(*args, **kwargs)
        with patch("engine.sessions.evaluation_comparison.play_game", side_effect=fail_second):
            executor.finish()
        state = run.snapshot()
        self.assertEqual(state["status"], "failed")
        self.assertIn("第二局", state["error"])
        summary = load_comparison(Path(state["path"]) / "manifest.json")
        self.assertEqual(summary.status, "failed")
        self.assertEqual(len(summary.games), 1)
        self.assertIsNone(summary.paired_score_rate)
        self.assertTrue(summary.games[0].path.is_file())

    def test_stop_after_a_move_saves_legal_replay_and_preserves_search_board(self):
        stop = Event()
        search = AlphaBetaSearcher.search
        def stop_second(searcher, board, **kwargs):
            initial_fen, history = board.fen(), list(board.move_stack)
            if history:
                stop.set()
            result = search(searcher, board, **kwargs)
            self.assertEqual(board.fen(), initial_fen)
            self.assertEqual(board.move_stack, history)
            return result
        with patch.object(AlphaBetaSearcher, "search", stop_second):
            result = run_evaluation_comparison(**{**self.options, "initial_fens": (chess.STARTING_FEN,)},
                                               control=lambda: not stop.is_set())
        summary = load_comparison(result.path / "manifest.json")
        replay = load_replay_json(str(summary.games[0].path))
        self.assertEqual(len(replay["moves_uci"]), 1)
        self.assertEqual(replay["result"], "*")
        self.assertEqual(replay["metadata"]["termination"], "user_stop")
        self.assertEqual(summary.incomplete_pairs, 1)

    def test_truncated_pairs_are_not_scored_as_draws(self):
        result = run_evaluation_comparison(**{**self.options, "initial_fens": (chess.STARTING_FEN,), "max_plies": 0})
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(summary.unfinished, 4)
        self.assertEqual(summary.draws, 0)
        self.assertEqual(summary.incomplete_pairs, 2)
        self.assertIsNone(summary.paired_score_rate)


if __name__ == "__main__":
    unittest.main()
