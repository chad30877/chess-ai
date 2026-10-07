"""實際 spawn 子程序的重現、亂序、停止、暫停與保存驗證。"""

from concurrent.futures import ThreadPoolExecutor
import csv
import json
import multiprocessing
from pathlib import Path
import tempfile
from threading import Event
from time import sleep
from contextlib import nullcontext
import unittest
from unittest.mock import patch

import chess

from engine.evaluation.config import EvaluationConfig
from engine.replay.comparison_catalog import load_comparison
from engine.replay.replay_catalog import ReplayCatalog
from engine.replay.replay_loader import load_replay_json
from engine.sessions.batch_run import BatchRun, BatchSettings
from engine.sessions.comparison_run import ComparisonRun
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, run_evaluation_comparison
from engine.sessions.parallel_batch import actual_workers, run_parallel
from tests.helpers.executors import ManualExecutor


EARLY = "7k/8/8/8/8/8/8/KR6 w - - 149 75"
TERMINAL = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def delayed_work(work):
    from engine.sessions.batch_workers import run_work
    if work["number"] == 1:
        sleep(0.4)
    run_work(work)


def fail_second_color(work):
    from engine.sessions import batch_workers
    original = batch_workers.play_game
    def play(number, *args, **kwargs):
        if number == 2:
            raise RuntimeError("第二色受控失敗")
        return original(number, *args, **kwargs)
    with patch.object(batch_workers, "play_game", play):
        batch_workers.run_work(work)


def slow_general_work(work):
    from engine.sessions import batch_workers
    class SlowPlayer:
        def choose_move(self, board):
            sleep(0.08)
            return next(iter(board.legal_moves))
    with patch.object(batch_workers, "general_player", side_effect=lambda *args: SlowPlayer()):
        batch_workers.run_work(work)


def crashing_work(work):
    import os
    os._exit(7)


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class ParallelBatchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "batches"

    def options(self, **kwargs):
        search = ComparisonSearchConfig(depth_plies=2)
        return dict(baseline=ComparisonParticipant.alphabeta("baseline", EvaluationConfig(), search=search),
                    candidate=ComparisonParticipant.alphabeta("candidate", EvaluationConfig(phase_enabled=True), search=search),
                    initial_fens=(EARLY, chess.STARTING_FEN), repetitions=2, max_plies=3,
                    base_seed=31, batch_root=self.root, **kwargs)

    def replay_signatures(self, path):
        result = {}
        games = rows(path / "games.csv")
        self.assertEqual([int(row["game_number"]) for row in games], list(range(1, len(games) + 1)))
        self.assertEqual(len({row["game_id"] for row in games}), len(games))
        for row in games:
            replay = load_replay_json(str(path / row["replay_path"]))
            board = chess.Board(replay["initial_fen"])
            for uci in replay["moves_uci"]:
                move = chess.Move.from_uci(uci)
                self.assertIn(move, board.legal_moves)
                board.push(move)
            number = replay["metadata"]["execution"]["game_number"]
            result[number] = (int(row["seed"]), row["white_player"], row["black_player"], replay["moves_uci"],
                              row["result"], row["termination"])
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["saved_games"], len(games))
        return result

    def test_worker_count_validation_and_cpu_work_limits(self):
        with patch("engine.sessions.parallel_batch.os.cpu_count", return_value=6):
            self.assertEqual(actual_workers(8, 20), 6)
            self.assertEqual(actual_workers(4, 2), 2)
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                actual_workers(value, 4)

    def test_general_single_and_multiple_processes_match_fixed_work_seeds(self):
        paths = []
        for workers in (1, 4):
            executor = ManualExecutor()
            run = BatchRun(BatchSettings(white="Greedy", black="Random", games=6, workers=workers,
                           max_plies=5, base_seed=42, white_evaluation=EvaluationConfig(phase_enabled=True)),
                           self.root, executor)
            executor.finish()
            self.assertEqual(run.snapshot()["status"], "completed", run.snapshot())
            self.assertEqual((run.snapshot()["waiting_work"], run.snapshot()["running_work"], run.snapshot()["finished_work"]),
                             (0, 0, 6))
            path = Path(run.snapshot()["path"])
            paths.append(path)
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["settings"]["requested_workers"], workers)
            self.assertEqual(manifest["settings"]["workers"], actual_workers(workers, 6))
            self.assertNotIn("comparison", manifest["settings"])
        self.assertEqual(self.replay_signatures(paths[0]), self.replay_signatures(paths[1]))
        self.assertEqual(len(ReplayCatalog(self.root.parent).entries), 12)

    def test_comparison_single_and_multiple_processes_match_pairs_and_early_terminal(self):
        paths = []
        for workers in (1, 4):
            result = run_evaluation_comparison(**self.options(workers=workers))
            paths.append(result.path)
            summary = load_comparison(result.path / "manifest.json")
            self.assertEqual((summary.completed_pairs, summary.incomplete_pairs), (2, 2))
            data = json.loads((result.path / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual([pair["seed"] for pair in data["pairs"]], [31, 32, 33, 34])
            for pair in data["pairs"]:
                self.assertEqual({game["candidate_color"] for game in pair["games"]}, {"white", "black"})
        self.assertEqual(self.replay_signatures(paths[0]), self.replay_signatures(paths[1]))

    def test_out_of_order_results_publish_contiguous_prefix_immediately(self):
        states = []
        def progress(state):
            if state["saved_games"]:
                summary = load_comparison(Path(state["path"]) / "manifest.json")
                self.assertEqual(len(summary.games), state["saved_games"])
                states.append(state.copy())
        options = self.options(workers=2)
        options.update(initial_fens=(TERMINAL,), repetitions=2, progress=progress)
        with patch("engine.sessions.parallel_batch.run_work", delayed_work):
            result = run_evaluation_comparison(**options)
        stored = rows(result.path / "games.csv")
        first = load_replay_json(str(result.path / stored[0]["replay_path"]))
        self.assertEqual(first["metadata"]["execution"]["work_number"], 2)
        self.assertIn(1, [s["saved_games"] for s in states])
        self.assertTrue(any(s["saved_games"] == 1 and s["incomplete_pairs"] == 1 for s in states))
        self.replay_signatures(result.path)

    def test_stop_running_comparison_saves_interrupted_games_and_no_new_pairs(self):
        stopped = Event()
        states = []
        def progress(state):
            states.append(state.copy())
            if state["current_game"] >= 1:
                stopped.set()
        options = self.options(workers=2)
        options.update(initial_fens=(chess.STARTING_FEN,), repetitions=8, max_plies=None,
                       progress=progress, control=lambda: not stopped.is_set())
        result = run_evaluation_comparison(**options)
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(summary.status, "stopped")
        self.assertGreaterEqual(len(summary.games), 1)
        self.assertLessEqual(len(summary.games), 2)
        self.assertTrue(any(game.termination == "user_stop" for game in summary.games))
        self.assertIsNone(summary.paired_score_rate)
        self.assertGreater(states[-1]["waiting_work"], 0)
        self.assertEqual(states[-1]["running_work"], 0)
        self.replay_signatures(result.path)

    def test_general_pause_resume_and_stop_do_not_deadlock_or_start_new_work(self):
        started = Event()
        original = BatchRun._progress
        def progress(run, state):
            original(run, state)
            if state.get("current_game", 0) >= 1:
                started.set()
        with patch("engine.sessions.parallel_batch.run_work", slow_general_work), \
                patch.object(BatchRun, "_progress", progress), ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(white="Random", black="Random", games=8, workers=2, base_seed=42), self.root, executor)
            try:
                self.assertTrue(started.wait(10))
                run.pause()
                sleep(0.2)
                self.assertEqual(run.snapshot()["status"], "paused")
                self.assertEqual(run.snapshot()["saved_games"], 0)
                run.resume()
                sleep(0.2)
                run.pause()
                run.stop()
            finally:
                run.stop()
            run.future.result(timeout=10)
        self.assertEqual(run.snapshot()["status"], "stopped")
        self.assertLessEqual(run.snapshot()["saved_games"], 2)
        self.assertGreaterEqual(run.snapshot()["saved_games"], 1)
        signatures = self.replay_signatures(Path(run.snapshot()["path"]))
        self.assertTrue(all(value[-1] == "user_stop" for value in signatures.values()))

    def test_pair_failure_preserves_first_color_and_drains_other_work(self):
        options = self.options(workers=2)
        options.update(initial_fens=(TERMINAL,), repetitions=8)
        executor = ManualExecutor()
        run = ComparisonRun(options, executor)
        with patch("engine.sessions.parallel_batch.run_work", fail_second_color):
            executor.finish()
        state = run.snapshot()
        self.assertEqual(state["status"], "failed")
        self.assertIn("第二色受控失敗", state["error"])
        summary = load_comparison(Path(state["path"]) / "manifest.json")
        self.assertGreaterEqual(len(summary.games), 1)
        self.assertEqual(summary.completed_pairs, 0)
        self.assertIsNone(summary.paired_score_rate)
        self.replay_signatures(Path(state["path"]))

    def test_save_failure_and_abrupt_process_exit_release_resources(self):
        work = dict(kind="general", seed=42, initial_fen=TERMINAL,
                    settings=dict(white="Random", black="Random", white_evaluation=None,
                                  black_evaluation=None, claim_draw=False, max_plies=0))
        for target, callback in ((None, lambda *args: (_ for _ in ()).throw(OSError("保存失敗"))),
                                 (crashing_work, lambda *args: None)):
            with self.subTest(target=target):
                context = patch("engine.sessions.parallel_batch.run_work", target) if target else nullcontext()
                with context, self.assertRaises(Exception):
                    run_parallel(work_count=10, workers=2, make_work=lambda n: dict(work, number=n),
                                 on_game=callback, progress=lambda state: None)
        self.assertEqual(multiprocessing.active_children(), [])

    def test_per_slot_interval_stop_does_not_dispatch_remaining_games(self):
        saved = Event()
        original = BatchRun._progress
        def progress(run, state):
            original(run, state)
            if state.get("saved_games", 0) >= 2:
                saved.set()
        with patch.object(BatchRun, "_progress", progress), ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(games=8, workers=2, interval=60, initial_fen=TERMINAL), self.root, executor)
            try:
                self.assertTrue(saved.wait(10))
                run.pause()
                run.resume()
                run.stop()
            finally:
                run.stop()
            run.future.result(timeout=10)
        self.assertEqual(run.snapshot()["saved_games"], 2)
        self.assertEqual(run.snapshot()["status"], "stopped")

    def test_windows_ui_main_guard_and_close_wait_for_children(self):
        import os
        import subprocess
        import sys
        import textwrap

        script = self.root.parent / "ui_spawn_check.py"
        script.write_text(textwrap.dedent(f'''
            import sys
            sys.path.insert(0, {str(Path.cwd())!r})
            import multiprocessing
            from pathlib import Path
            from time import monotonic, sleep
            import pygame
            from apps.chess_application import ChessApplication
            from engine.sessions.batch_run import BatchRun, BatchSettings

            if __name__ == "__main__":
                pygame.init()
                app = ChessApplication(pygame.display.set_mode((900, 768)))
                print("UI_CREATED", flush=True)
                app.batch = BatchRun(BatchSettings(white="Random", black="Random", games=100,
                                                  workers=2, base_seed=42), Path({str(self.root)!r}), app.executor)
                deadline = monotonic() + 10
                while not app.batch.snapshot()["current_game"] and monotonic() < deadline:
                    sleep(0.01)
                app.close()
                assert app.batch.future.done()
                assert app.batch.snapshot()["status"] == "stopped", app.batch.snapshot()
                assert not multiprocessing.active_children()
                print("CLOSED_AND_SAVED", flush=True)
                pygame.quit()
        '''), encoding="utf-8")
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
        completed = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.count("UI_CREATED"), 1)
        self.assertIn("CLOSED_AND_SAVED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
