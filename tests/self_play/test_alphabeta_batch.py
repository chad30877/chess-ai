"""一般批次以真實搜尋程序驗證條件、發布與生命週期。"""
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import patch

from engine.storage.batch_storage import BatchWriter

try:
    import psutil
except ImportError:
    psutil = None

from engine.evaluation.config import EvaluationConfig
from engine.replay.records_catalog import load_batch_record
from engine.replay.replay_loader import load_replay_json
from engine.sessions.batch_run import BatchRun, BatchSettings
from tests.helpers.executors import ManualExecutor


POSITION = "7k/8/8/8/8/8/8/KR6 w - - 0 1"


def broken_search_branch(*args):
    import os
    os._exit(9)


def fail_second_work(work):
    from engine.sessions.batch_workers import run_work
    if work["number"] == 2:
        sleep(1)
        with patch("engine.search.parallel._branch", broken_search_branch):
            run_work(work)
    else:
        run_work(work)


@contextmanager
def observed_descendants():
    """只追蹤本測試程序的後代，避免把其他開發工作算入。"""
    descendants = {}
    stop = Event()
    def observe():
        while not stop.is_set():
            if psutil:
                for process in psutil.Process().children(recursive=True):
                    try:
                        descendants[process.pid] = process.create_time()
                    except psutil.NoSuchProcess:
                        pass
            stop.wait(.01)
    thread = Thread(target=observe)
    thread.start()
    try:
        yield descendants
    finally:
        stop.set()
        thread.join()
        if psutil:
            alive = []
            for pid, created in descendants.items():
                try:
                    if psutil.Process(pid).create_time() == created:
                        alive.append(pid)
                except psutil.NoSuchProcess:
                    pass
            if alive:
                raise AssertionError(f"搜尋後仍有後代程序：{alive}")


class AlphaBetaBatchTest(unittest.TestCase):
    def test_general_alphabeta_saves_each_game_with_actual_search_conditions(self):
        with tempfile.TemporaryDirectory() as folder:
            executor = ManualExecutor()
            run = BatchRun(BatchSettings(white="AlphaBeta", black="AlphaBeta", games=2,
                           workers=2, search_workers=2, search_depth=1,
                           transposition_capacity=23, max_plies=2, base_seed=37, initial_fen=POSITION,
                           white_evaluation=EvaluationConfig(phase_enabled=True)), Path(folder), executor)
            with observed_descendants(), patch("engine.sessions.parallel_batch.os.cpu_count", return_value=2):
                executor.finish()
            state = run.snapshot()
            self.assertEqual(state["status"], "completed", state)
            record = load_batch_record(Path(state["path"]) / "manifest.json")
            self.assertEqual(len(record.games), 2)
            self.assertEqual(record.settings["workers"], 2)
            self.assertTrue(record.settings["strategies"]["white"]["evaluator"]["phase"]["enabled"])
            self.assertFalse(record.settings["strategies"]["black"]["evaluator"]["phase"]["enabled"])
            for side in ("white", "black"):
                actual = record.settings["strategies"][side]
                self.assertEqual(actual["search"]["search_workers"], 2)
                self.assertEqual(actual["search"]["transposition_capacity"], 23)
                self.assertEqual(actual["search"]["max_depth"], 1)
            for game in record.games:
                replay = load_replay_json(str(game.path))
                self.assertEqual(len(replay["moves_uci"]), 2)
            self.assertEqual(multiprocessing.active_children(), [])

    def test_nested_stop_and_pause_keep_readable_results_and_close_descendants(self):
        with tempfile.TemporaryDirectory() as folder, observed_descendants() as descendants, ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(white="AlphaBeta", black="AlphaBeta", games=8,
                           workers=2, search_workers=2, search_depth=3, max_plies=100,
                           initial_fen=POSITION), Path(folder), executor)
            try:
                deadline = monotonic() + 15
                while monotonic() < deadline:
                    if (len(descendants) >= 4 if psutil else run.snapshot()["current_game"] >= 1):
                        break
                    sleep(.01)
                self.assertGreaterEqual(run.snapshot()["current_game"], 1)
                run.pause()
                self.assertEqual(run.snapshot()["status"], "paused")
                run.resume()
                run.pause()
                run.stop()
                run.future.result(timeout=20)
            finally:
                run.stop()
            state = run.snapshot()
            self.assertEqual(state["status"], "stopped", state)
            record = load_batch_record(Path(state["path"]) / "manifest.json")
            self.assertGreaterEqual(len(record.games), 1)
            self.assertLessEqual(len(record.games), 2)
            self.assertTrue(all(game.termination == "user_stop" for game in record.games))

    def test_nested_worker_and_save_failure_preserve_published_prefix(self):
        for failure in ("worker", "save"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder, observed_descendants():
                executor = ManualExecutor()
                original = BatchWriter.add_game
                def save(writer, game, *args, **kwargs):
                    if writer.manifest["counts"]["saved_games"] == 1:
                        raise OSError("受控保存失敗")
                    return original(writer, game, *args, **kwargs)
                target = (patch("engine.sessions.parallel_batch.run_work", fail_second_work)
                          if failure == "worker" else patch.object(BatchWriter, "add_game", save))
                run = BatchRun(BatchSettings(white="AlphaBeta", black="AlphaBeta", games=2,
                               workers=2, search_workers=2, search_depth=1, max_plies=1,
                               initial_fen=POSITION), Path(folder), executor)
                with target:
                    executor.finish()
                state = run.snapshot()
                self.assertEqual(state["status"], "failed", state)
                record = load_batch_record(Path(state["path"]) / "manifest.json")
                self.assertEqual(len(record.games), 1)
                self.assertTrue(record.games[0].path.is_file())
                self.assertEqual(len(load_replay_json(str(record.games[0].path))["moves_uci"]), 1)
