"""驗證兩種模式的共用派發、進度、控制能力與失敗處理。"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.evaluation.config import EvaluationConfig
from engine.replay.comparison_catalog import ComparisonCatalog
from engine.replay.replay_loader import load_replay_json
from engine.sessions.batch_execution import start_batch
from engine.sessions.batch_run import BatchSettings
from engine.sessions.evaluation_comparison import ComparisonParticipant
from tests.helpers.executors import ManualExecutor


class BatchExecutionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "batches"
        self.executor = ManualExecutor()

    def start(self, mode):
        settings = (BatchSettings(games=2, max_plies=0) if mode == "general" else
                    dict(baseline=ComparisonParticipant.alphabeta("baseline", EvaluationConfig()),
                         candidate=ComparisonParticipant.alphabeta("candidate", EvaluationConfig()),
                         initial_fens=("7k/8/8/8/8/8/8/K7 w - - 0 1",), repetitions=1))
        return start_batch(mode, settings, self.root, self.executor)

    def test_both_modes_publish_common_progress_and_durable_replays(self):
        for mode in ("general", "evaluation"):
            with self.subTest(mode=mode):
                run = self.start(mode)
                self.executor.finish()
                state = run.snapshot()
                self.assertEqual(state["status"], "completed")
                self.assertEqual(state["saved_games"], 2)
                self.assertEqual((state["completed_games"], state["unfinished"]),
                                 (0, 2) if mode == "general" else (2, 0))
                replay = load_replay_json(state["last_replay"])
                self.assertEqual(replay["result"], "*" if mode == "general" else "1/2-1/2")
                manifest = json.loads((Path(state["path"]) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["counts"]["saved_games"], 2)
                self.assertEqual(manifest["settings"]["workers"], 1)
                if mode == "general":
                    self.assertNotIn("comparison", manifest["settings"])
                    self.assertNotIn("paired_score_rate", state)
                    self.assertEqual(ComparisonCatalog(self.root.parent).entries, [])
                else:
                    self.assertEqual(state["completed_pairs"], 1)
                    self.assertEqual(state["paired_score_rate"], 0.5)

    def test_queued_stop_and_pause_capabilities_publish_final_manifest(self):
        for mode in ("general", "evaluation"):
            with self.subTest(mode=mode):
                run = self.start(mode)
                run.pause()
                self.assertEqual(run.snapshot()["status"], "paused" if mode == "general" else "running")
                run.stop()
                run.resume()
                self.assertEqual(run.snapshot()["status"], "stopping")
                self.executor.finish()
                state = run.snapshot()
                self.assertEqual((state["status"], state["saved_games"]), ("stopped", 0))
                manifest = json.loads((Path(state["path"]) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "stopped")

    def test_preflight_failures_are_reported_through_common_worker(self):
        for mode, target in (("general", "engine.sessions.batch_run.BatchRun._create_player"),
                             ("evaluation", "engine.sessions.evaluation_comparison.ComparisonParticipant.settings_snapshot")):
            with self.subTest(mode=mode), patch(target, side_effect=ValueError("無法建立玩家")):
                run = self.start(mode)
                self.executor.finish()
                self.assertEqual(run.snapshot()["status"], "failed")
                self.assertIn("無法建立玩家", run.snapshot()["error"])
                self.assertEqual(run.snapshot()["path"], "")
                self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
