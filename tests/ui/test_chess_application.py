"""Exercise pygame events and rendered controls without requiring a desktop."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import chess
import pygame

from apps.chess_application import APP_SIZE, HEADER_HEIGHT, ChessApplication
from engine.sessions.live_session import LiveSession, LiveSettings
from engine.replay.replay_loader import load_replay_json
from tests.helpers.executors import ManualExecutor
from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import ComparisonParticipant, run_evaluation_comparison
from engine.sessions.comparison_run import ComparisonRun


class ChessApplicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode(APP_SIZE)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        project_patch = patch("apps.chess_application.PROJECT_ROOT", self.project)
        project_patch.start()
        self.addCleanup(project_patch.stop)
        self.executor = ManualExecutor()
        self.app = ChessApplication(self.screen, executor=self.executor, now=lambda: 100)
        self.app.batch_workers = 1
        self.addCleanup(self.app.close)

    def click(self, action):
        self.app.render()
        button = next(b for b in self.app.buttons if b.action == action)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center))

    def square_click(self, square):
        x, y = self.app.board_view._square_to_screen(square, self.app.flipped)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x + 40, y + 40)))

    def test_startup_has_home_and_three_modes_without_default_game(self):
        self.app.render()
        self.assertEqual(self.app.mode, "home")
        self.assertIsNone(self.app.replay)
        self.assertIsNone(self.app.live)
        self.assertEqual({b.action for b in self.app.buttons},
                         {"mode:auto", "mode:human", "mode:records"})
        self.click("mode:auto")
        self.assertIsNone(self.app.live)
        self.click("white")
        self.assertEqual(self.app.white, "Greedy")
        self.click("start")
        self.assertEqual(self.app.batch.snapshot()["status"], "running")
        self.app.render()
        self.assertNotIn("white", {b.action for b in self.app.buttons})

    def test_explicit_replay_and_keyboard_navigation(self):
        app = ChessApplication(self.screen, "data/replays/sample_replay.json", executor=self.executor)
        self.addCleanup(app.close)
        self.assertEqual(app.mode, "replay")
        self.assertEqual(app.replay.total_ply(), 6)
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_END))
        self.assertEqual(app.replay.current_ply, 6)
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
        self.assertEqual(app.replay.current_ply, 5)
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_HOME))
        self.assertEqual(app.replay.current_ply, 0)

    def test_batch_pause_resume_stop_shows_only_progress(self):
        self.click("mode:auto")
        self.click("start")
        self.assertIsNone(self.app.live)
        with patch.object(self.app.board_view, "render", side_effect=AssertionError("No board in batch")):
            self.app.render()
        self.click("pause")
        self.assertEqual(self.app.batch.snapshot()["status"], "paused")
        self.click("pause")
        self.assertEqual(self.app.batch.snapshot()["status"], "running")
        self.click("stop")
        self.executor.finish()
        self.assertEqual(self.app.batch.snapshot()["status"], "stopped")
        self.assertEqual(self.app.batch.snapshot()["saved_games"], 0)

    def test_confirmation_cancel_restores_running_and_confirm_returns_home(self):
        self.click("mode:human")
        self.click("start")
        game = self.app.live
        self.click("home")
        self.assertEqual(game.status, "paused")
        self.app.handle_event(pygame.event.Event(pygame.QUIT))
        self.click("cancel")
        self.assertEqual(game.status, "running")
        self.click("home")
        self.click("confirm")
        self.assertEqual(self.app.mode, "home")
        self.assertEqual(game.status, "stopped")

    def test_batch_leave_waits_for_manifest_and_cancel_resumes(self):
        self.click("mode:auto")
        self.click("start")
        batch = self.app.batch
        self.click("home")
        self.assertEqual(batch.snapshot()["status"], "paused")
        self.click("cancel")
        self.assertEqual(batch.snapshot()["status"], "running")
        self.click("home")
        self.click("confirm")
        self.assertEqual(self.app.mode, "auto")
        self.assertEqual(self.app.pending_leave, "home")
        self.executor.finish()
        self.app.tick()
        self.assertEqual(self.app.mode, "home")
        path = self.project / "data/batches" / batch.snapshot()["batch_id"] / "manifest.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "stopped")

    def test_restart_drops_old_result_and_stays_in_setup(self):
        self.click("mode:human")
        self.app.dispatch("color")
        self.app.interval = 0
        self.click("start")
        old = self.app.live
        self.app.tick()
        self.executor.jobs[0][0].set_running_or_notify_cancel()
        self.click("restart")
        self.click("confirm")
        self.assertIsNone(self.app.live)
        self.assertEqual(self.app.mode, "human")
        self.click("start")
        self.executor.finish(0)
        self.assertEqual(self.app.live.board.fen(), chess.STARTING_FEN)
        self.assertEqual(old.board.fen(), chess.STARTING_FEN)

    def test_human_clicks_legal_targets_and_blocks_opponent_turn(self):
        self.click("mode:human")
        self.click("start")
        self.square_click(chess.E2)
        self.assertEqual(self.app.selected, chess.E2)
        self.square_click(chess.E5)
        self.assertEqual(len(self.app.live.move_items), 0)
        self.square_click(chess.E2)
        self.square_click(chess.E4)
        self.assertEqual(self.app.live.move_items[0]["uci"], "e2e4")
        self.square_click(chess.E7)
        self.square_click(chess.E5)
        self.assertEqual(len(self.app.live.move_items), 1)

    def test_black_selection_flips_board_and_schedules_white_ai(self):
        self.click("mode:human")
        self.click("color")
        self.assertTrue(self.app.flipped)
        self.app.interval = 0
        self.click("start")
        self.assertFalse(self.app.live.human_turn)
        self.square_click(chess.E7)
        self.assertIsNone(self.app.selected)
        self.app.tick()
        self.executor.finish()
        self.app.tick()
        self.assertTrue(self.app.live.human_turn)

    def test_square_mapping_in_both_orientations_and_outside_board(self):
        view = self.app.board_view
        for flipped in (False, True):
            for square in chess.SQUARES:
                x, y = view._square_to_screen(square, flipped)
                self.assertEqual(view.screen_to_square((x + 40, y + 40), flipped), square)
        x, y, size = view.origin_x, view.origin_y, view.board_pixels
        for pos in ((x - 1, y), (x, y - 1), (x + size, y), (x, y + size)):
            self.assertIsNone(view.screen_to_square(pos))

    def test_promotion_requires_choice_and_supports_underpromotion(self):
        self.app.new_setup("human")
        self.app.live = LiveSession(LiveSettings(white="Human", initial_fen="7k/P7/8/8/8/8/8/7K w - - 0 1"))
        self.app.live.start()
        self.square_click(chess.A7)
        self.square_click(chess.A8)
        self.assertEqual(len(self.app.promotions), 4)
        self.assertEqual(len(self.app.live.move_items), 0)
        self.click("cancel_promotion")
        self.square_click(chess.A7)
        self.square_click(chess.A8)
        self.click("promote:2")
        self.assertEqual(self.app.live.board.piece_at(chess.A8).piece_type, chess.KNIGHT)
        self.assertEqual(self.app.live.status, "completed")

    def test_stopped_game_export_is_unique_and_roundtrips(self):
        self.click("mode:human")
        self.click("start")
        self.square_click(chess.E2)
        self.square_click(chess.E4)
        self.click("stop")
        expected_fen = self.app.live.board.fen()
        with tempfile.TemporaryDirectory() as directory:
            with patch("apps.chess_application.PROJECT_ROOT", Path(directory)):
                first = self.app.export_game()
                second = self.app.export_game()
            self.assertEqual(first, second)
            self.assertRegex(first.name, r"^\d{8}_\d{6}\.json$")
            data = load_replay_json(str(first))
            self.assertEqual(data["result"], "*")
            self.assertEqual(data["metadata"]["termination"], "user_stop")
            self.click("review")
            self.assertEqual(self.app.replay_data["metadata"]["game_id"], first.stem)
            self.assertTrue(self.app.open_replay(first))
            self.app.replay.last()
            self.assertEqual(self.app.replay.current_fen(), expected_fen)

    def test_review_current_game_preserves_history_without_disk_write(self):
        self.click("mode:human")
        self.click("start")
        self.square_click(chess.E2)
        self.square_click(chess.E4)
        self.click("stop")
        self.click("review")
        self.assertTrue(self.app.replay_is_local_game)
        self.click("last")
        self.assertEqual(self.app.replay.current_fen(), self.app.live.board.fen())
        self.click("open")
        self.assertIsNone(self.app.records_view)

    def test_catalog_navigation_invalid_json_and_sample_remain_usable(self):
        folder = self.project / "data/replays"
        folder.mkdir(parents=True)
        sample = json.loads(Path("data/replays/sample_replay.json").read_text(encoding="utf-8"))
        sample["metadata"].update(started_at="2026-09-09T12:34:56+08:00", game_id="20260909_000001")
        valid = folder / "20260909_000001.json"
        valid.write_text(json.dumps(sample), encoding="utf-8")
        (folder / "bad.json").write_text("{", encoding="utf-8")
        self.click("mode:records")
        self.assertEqual(len(self.app.records_view.catalog.entries), 2)
        self.click("records_dates")
        self.click("records_date:1")
        self.assertEqual(self.app.records_view.date, "2026-09-09")
        self.click("records_entry:0")
        # 索引建立後棋譜消失，仍保留來源清單與先前回放。
        valid.unlink()
        self.click("records_game:0")
        self.assertIn("無法開啟", self.app.records_view.message)
        valid.write_text(json.dumps(sample), encoding="utf-8")
        self.click("records_game:0")
        self.assertEqual(self.app.replay.total_ply(), 6)
        self.click("records_results")
        self.assertEqual(self.app.records_view.date, "2026-09-09")
        self.assertEqual(self.app.records_view.selected_game, "20260909_000001")
        self.app.dispatch("sample")
        self.assertEqual(self.app.replay.total_ply(), 6)

    def test_numeric_batch_settings_and_native_resize(self):
        self.click("mode:auto")
        self.click("count")
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text="37"))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertEqual(self.app.game_count, 37)
        self.click("interval")
        self.app.numeric_text = "-1"
        self.click("start")
        self.assertIsNone(self.app.batch)
        self.app.numeric_text = "0.25"
        self.app._commit_number()
        self.assertEqual(self.app.batch_interval, 0.25)
        self.app.resize(pygame.Surface((1800, 1536)))
        self.assertEqual(self.app.board_view.piece_images["wk"].get_size(), (160, 160))
        bounds = self.app.board_view.piece_images["wk"].get_bounding_rect()
        self.assertGreater(bounds.width, 160 * 0.6)
        self.assertAlmostEqual(bounds.centerx, 80, delta=8)
        self.app.render()
        start = next(b for b in self.app.buttons if b.action == "start")
        self.assertEqual(start.rect.width, 1200)

    def test_shared_worker_field_default_validation_and_capacity(self):
        app = ChessApplication(self.screen, executor=self.executor)
        self.addCleanup(app.close)
        self.assertEqual(app.batch_workers, 4)
        self.prepare_comparison_configs()
        self.click("mode:auto")
        self.click("workers")
        self.app.numeric_text = "0"
        self.click("start")
        self.assertIsNone(self.app.batch)
        self.assertIn("同時對戰場數", self.app.message)
        self.app.numeric_text = "8"
        self.app._commit_number()
        self.click("batch_mode:evaluation")
        self.assertEqual(self.app.batch_workers, 8)
        self.enter_comparison_field("max_plies", "0")
        self.click("start")
        self.executor.finish()
        state = self.app.batch.snapshot()
        self.assertEqual((state["requested_workers"], state["actual_workers"]), (8, 1))
        self.assertEqual((state["finished_games"], state["saved_games"]), (2, 2))
        manifest = json.loads((Path(state["path"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["settings"]["requested_workers"], manifest["settings"]["workers"]), (8, 1))

    def test_invalid_cli_replay_shows_error_screen(self):
        app = ChessApplication(self.screen, "missing-replay.json", executor=self.executor)
        self.addCleanup(app.close)
        app.render()
        self.assertEqual(app.mode, "replay")
        self.assertIsNone(app.replay)
        self.assertIn("無法開啟", app.message)

    def comparison_batch(self, **kwargs):
        return run_evaluation_comparison(
            baseline=ComparisonParticipant.alphabeta("stable", EvaluationConfig()),
            candidate=ComparisonParticipant.alphabeta("phase", EvaluationConfig(phase_enabled=True)),
            initial_fens=["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"],
            batch_root=self.project / "data/batches", **kwargs,
        )

    def test_records_results_settings_and_replay_return(self):
        result = self.comparison_batch(repetitions=3)
        self.click("mode:records")
        self.click("records_entry:0")
        view = self.app.records_view
        self.assertEqual(view.summary.batch_id, result.path.name)
        self.assertEqual(view.summary.comparison.score_rate, 0.5)
        self.click("records_settings:candidate")
        self.assertTrue(view.summary.comparison.participants["candidate"]["evaluator"]["phase"]["enabled"])
        self.click("records_next")
        self.assertGreater(view.settings_offset, 0)
        self.click("records_back")
        self.click("records_next")
        self.assertEqual(view.offset, 1)
        self.click("records_game:5")
        self.assertEqual(self.app.mode, "replay")
        self.assertEqual(self.app.replay_data["metadata"]["game_id"], view.summary.games[5].game_id)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(self.app.mode, "records")
        self.assertIs(self.app.records_view, view)
        self.assertEqual(view.offset, 1)
        self.click("records_back")
        self.assertIsNone(view.summary)
        self.click("home")
        self.assertIsNone(self.app.records_view)

    def test_comparison_empty_missing_summary_and_refresh(self):
        self.click("mode:records")
        self.assertEqual(self.app.records_view.catalog.entries, [])
        result = self.comparison_batch()
        (result.path / "comparison.json").unlink()
        self.click("records_refresh")
        entry = self.app.records_view.catalog.entries[0]
        self.assertEqual(entry.kind, "comparison_unavailable")
        self.assertEqual(len(entry.games), 2)
        self.assertIsNone(entry.comparison)
        self.click("records_entry:0")
        self.click("records_game:0")
        self.assertEqual(self.app.mode, "replay")
        self.click("records_results")
        self.assertIn("比較摘要缺漏或損壞", self.app.records_view.summary.error)

    def test_comparison_missing_and_invalid_replays_keep_result_screen(self):
        result = self.comparison_batch()
        self.click("mode:records")
        self.click("records_entry:0")
        first = self.app.records_view.summary.games[0]
        first.path.write_text("{", encoding="utf-8")
        self.click("records_game:0")
        self.assertEqual(self.app.mode, "records")
        self.assertIn("無法開啟棋譜", self.app.records_view.message)
        first.path.unlink()
        self.click("records_back")
        self.click("records_refresh")
        self.click("records_entry:0")
        self.app.render()
        button = next(b for b in self.app.buttons if b.action == "records_game:0")
        self.assertFalse(button.enabled)
        self.assertEqual(self.app.records_view.summary.comparison.score_rate, 0.5)

    def test_comparison_candidate_labels_zero_score_and_resizing(self):
        run_evaluation_comparison(
            baseline=ComparisonParticipant.greedy("stable", EvaluationConfig()),
            candidate=ComparisonParticipant.greedy("candidate", EvaluationConfig()),
            batch_root=self.project / "data/batches", max_plies=0,
        )
        self.click("mode:records")
        self.click("records_entry:0")
        self.assertIsNone(self.app.records_view.summary.comparison.score_rate)
        for size in ((900, 768), APP_SIZE, (1800, 1536)):
            with self.subTest(size=size):
                self.app.resize(pygame.Surface(size))
                with patch.object(self.app, "text", wraps=self.app.text) as labels:
                    self.app.render()
                self.assertTrue(any("得分率：無資料" in str(call.args[0]) for call in labels.call_args_list))
                for button in self.app.buttons:
                    self.assertTrue(self.app.screen.get_rect().contains(button.rect))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertIsNone(self.app.records_view.summary)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(self.app.mode, "home")

    def standalone_records(self, count=1, *, metadata=None, moves=None):
        folder = self.project / "data/replays"
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            payload = {"initial_fen": chess.STARTING_FEN, "moves_uci": moves or [], "result": "*",
                       "metadata": metadata or {"game_id": f"plain-{index}", "started_at": "2026-09-09T12:00:00+08:00"}}
            (folder / f"plain-{index}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_records_restore_date_list_page_selection_and_settings_after_playback(self):
        self.standalone_records(8)
        self.click("mode:records")
        self.click("records_dates")
        self.click("records_date:1")
        self.click("records_next")
        view = self.app.records_view
        self.assertEqual(view.offset, 3)
        self.click("records_entry:7")
        selected = view.selected
        self.click("records_settings:all")
        self.click("records_back")
        self.click("records_game:0")
        self.click("records_results")
        self.assertEqual(view.selected, selected)
        self.assertEqual(view.selected_game, view.summary.games[0].game_id)
        self.click("records_back")
        self.assertEqual((view.date, view.offset, view.highlight_key), ("2026-09-09", 3, selected))
        self.app.render()
        self.assertTrue(next(b for b in self.app.buttons if b.action == "records_entry:7").primary)

    def test_general_batch_uses_common_summary_without_candidate_statistics(self):
        from engine.sessions.batch_run import BatchRun, BatchSettings
        run = BatchRun(BatchSettings(games=2, max_plies=0, white="Greedy", black="Random"),
                       self.project / "data/batches", self.executor)
        self.app.batch = run
        self.executor.finish()
        self.click("mode:records")
        self.click("records_entry:0")
        view = self.app.records_view
        with patch.object(self.app, "draw_label", wraps=self.app.draw_label) as labels:
            self.app.render()
        text = "\n".join(str(call.args[1]) for call in labels.call_args_list)
        self.assertIn("白方：Greedy", text)
        self.assertIn("黑方：Random", text)
        self.assertIn("未完成 2", text)
        self.assertIn("耗時：未記錄", text)
        self.assertNotIn("候選", text)
        self.assertNotIn("得分率", text)
        self.click("records_settings:all")
        self.assertEqual(view.summary.settings["color_assignment"], "fixed")
        self.click("records_back")
        self.click("records_game:0")
        self.click("records_results")
        self.assertIs(self.app.records_view, view)

    def test_standalone_missing_information_and_illegal_moves_preserve_existing_replay(self):
        self.standalone_records(metadata={"game_id": "unknown"}, moves=["e2e5"])
        self.app.dispatch("sample")
        original = self.app.replay
        self.click("open")
        self.click("records_entry:0")
        with patch.object(self.app, "draw_label", wraps=self.app.draw_label) as labels:
            self.app.render()
        text = "\n".join(str(call.args[1]) for call in labels.call_args_list)
        self.assertIn("白方：未記錄", text)
        self.assertIn("黑方：未記錄", text)
        self.assertIn("耗時：未記錄", text)
        self.click("records_settings:all")
        with patch.object(self.app, "draw_label", wraps=self.app.draw_label) as labels:
            self.app.render()
        self.assertTrue(any('"設定": "未記錄"' in str(call.args[1]) for call in labels.call_args_list))
        self.click("records_back")
        self.click("records_game:0")
        self.assertEqual(self.app.mode, "records")
        self.assertIs(self.app.replay, original)
        self.assertIn("Illegal move", self.app.records_view.message)
        self.assertEqual(self.app.records_view.selected_game, "unknown")

    def test_records_lookup_during_batch_returns_progress_without_dropping_worker(self):
        self.standalone_records()
        self.click("mode:auto")
        self.click("start")
        run = self.app.batch
        self.app.open_replay(self.project / "data/replays/plain-0.json", return_to="batch")
        self.click("open")
        view = self.app.records_view
        self.app.render()
        self.assertFalse(next(b for b in self.app.buttons if b.action == "comparison_new").enabled)
        self.app.dispatch("comparison_new")
        self.assertIs(self.app.batch, run)
        self.click("records_entry:0")
        self.click("records_game:0")
        self.click("records_results")
        self.click("records_back")
        self.click("records_back")
        self.assertEqual(self.app.mode, "auto")
        self.assertIs(self.app.batch, run)
        self.assertFalse(run.future.done())
        self.assertEqual(run.snapshot()["status"], "running")

    def test_missing_standalone_result_is_not_replaced_by_loader_default_in_display(self):
        folder = self.project / "data/replays"
        folder.mkdir(parents=True)
        (folder / "missing-result.json").write_text(json.dumps({
            "initial_fen": chess.STARTING_FEN, "moves_uci": []}), encoding="utf-8")
        self.click("mode:records")
        self.click("records_entry:0")
        self.click("records_game:0")
        with patch.object(self.app, "draw_label", wraps=self.app.draw_label) as labels:
            self.app.render()
        self.assertTrue(any("結果：未記錄" in str(call.args[1]) for call in labels.call_args_list))

    def test_valid_comparison_can_inspect_full_saved_batch_settings(self):
        self.comparison_batch()
        self.click("mode:records")
        self.click("records_entry:0")
        self.click("records_settings:all")
        settings = self.app.records_view.summary.settings["comparison"]
        self.assertIn("base_seed", settings)
        self.assertIn("initial_fens", settings)

    def prepare_comparison_configs(self):
        folder = self.project / "configs/evaluation"
        folder.mkdir(parents=True)
        (folder / "stable.json").write_text(json.dumps(EvaluationConfig().to_dict()), encoding="utf-8")
        (folder / "example_tapered.json").write_text(json.dumps(EvaluationConfig(phase_enabled=True).to_dict()), encoding="utf-8")

    def enter_comparison_field(self, key, value):
        self.click(f"comparison_field:{key}")
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=value))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))

    def test_comparison_setup_background_save_and_results(self):
        self.prepare_comparison_configs()
        (self.project / "openings.txt").write_text("# 測試開局\n7k/6Q1/5K2/8/8/8/8/8 b - - 0 1\n", encoding="utf-8")
        self.click("mode:records")
        self.click("comparison_new")
        self.enter_comparison_field("openings", "openings.txt")
        self.enter_comparison_field("depth", "3")
        self.enter_comparison_field("repetitions", "2")
        self.enter_comparison_field("seed", "42")
        self.enter_comparison_field("name", "UI 比較")
        self.enter_comparison_field("tags", "smoke,phase")
        self.click("start")
        run = self.app.batch
        self.assertFalse(run.future.done())
        self.app.render()
        self.assertNotIn("start", {b.action for b in self.app.buttons})
        self.assertIn("stop", {b.action for b in self.app.buttons})
        # 啟動後修改來源檔，不應改變已解析的實際玩家設定。
        (self.project / "configs/evaluation/example_tapered.json").write_text("{}", encoding="utf-8")
        self.executor.finish()
        self.assertEqual(run.snapshot()["completed_pairs"], 2)
        self.click("batch_results")
        summary = self.app.records_view.summary
        self.assertEqual(summary.name, "UI 比較")
        self.assertEqual(summary.comparison.budget["depth_plies"], 3)
        self.assertTrue(summary.comparison.participants["candidate"]["evaluator"]["phase"]["enabled"])
        manifest = json.loads((Path(run.snapshot()["path"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["settings"]["comparison"]["base_seed"], 42)
        self.assertIn("phase", manifest["tags"])

    def test_shared_batch_entry_switches_fields_and_shortcut_preselects_mode(self):
        self.prepare_comparison_configs()
        self.click("mode:auto")
        self.click("white")
        self.app.game_count = 7
        self.app.batch_interval = 0.25
        self.click("batch_mode:evaluation")
        self.assertEqual(self.app.mode, "auto")
        self.enter_comparison_field("depth", "3")
        self.app.render()
        actions = {b.action for b in self.app.buttons}
        self.assertNotIn("white", actions)
        self.assertNotIn("count", actions)
        self.assertNotIn("comparison_start", actions)
        self.click("batch_mode:general")
        self.assertEqual((self.app.white, self.app.game_count, self.app.batch_interval), ("Greedy", 7, 0.25))
        self.click("batch_mode:evaluation")
        self.assertEqual(self.app.evaluation_fields.options()["baseline"].search_config.depth_plies, 3)
        self.click("home")
        self.click("mode:records")
        self.assertFalse(hasattr(self.app.records_view, "setup"))
        self.click("comparison_new")
        self.assertEqual((self.app.mode, self.app.batch_mode), ("auto", "evaluation"))
        self.assertIsNone(self.app.records_view)
        self.enter_comparison_field("max_plies", "0")
        self.click("start")
        self.app.render()
        self.assertNotIn("pause", {b.action for b in self.app.buttons})
        self.assertNotIn("batch_mode:general", {b.action for b in self.app.buttons})
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        self.assertEqual(self.app.batch.snapshot()["status"], "running")
        self.executor.finish()
        self.click("restart")
        self.assertEqual((self.app.mode, self.app.batch_mode), ("auto", "evaluation"))

    def test_settings_diff_uses_saved_settings_after_source_changes(self):
        self.comparison_batch()
        self.click("mode:records")
        self.click("records_entry:0")
        self.prepare_comparison_configs()
        (self.project / "configs/evaluation/example_tapered.json").write_text("{}", encoding="utf-8")
        self.click("records_settings:diff")
        with patch.object(self.app, "draw_label", wraps=self.app.draw_label) as labels:
            self.app.render()
        text = "\n".join(str(call.args[1]) for call in labels.call_args_list)
        self.assertIn('"phase"', text)
        self.assertIn('"基準": false', text)
        self.assertIn('"候選": true', text)
        self.assertNotIn('"label"', text)
        self.click("records_back")
        self.assertIsNone(self.app.records_view.settings_side)

    def test_comparison_setup_invalid_inputs_create_no_batch(self):
        self.prepare_comparison_configs()
        self.click("mode:records")
        self.click("comparison_new")
        for field, value in (("depth", "0"), ("seed", "-1"), ("repetitions", "0"),
                             ("openings", "missing.txt"), ("max_plies", "-1")):
            with self.subTest(field=field):
                setup = self.app.evaluation_fields
                original = setup.values[field]
                self.enter_comparison_field(field, value)
                self.click("start")
                self.assertIsNone(self.app.batch)
                self.assertIn("無法開始", self.app.message)
                self.assertFalse((self.project / "data/batches").exists())
                setup.values[field] = original
        self.click("comparison_file:baseline")
        self.assertEqual(self.app.evaluation_fields.baseline.name, "example_tapered.json")
        for size in ((900, 768), APP_SIZE, (1800, 1536)):
            self.app.resize(pygame.Surface(size))
            self.app.render()
            self.assertTrue(all(self.app.screen.get_rect().contains(button.rect) for button in self.app.buttons))

    def test_comparison_leave_cancel_and_confirm_wait_for_save(self):
        self.prepare_comparison_configs()
        self.click("mode:records")
        self.click("comparison_new")
        self.click("start")
        run = self.app.batch
        self.click("home")
        self.assertEqual(run.snapshot()["status"], "running")
        self.click("cancel")
        self.assertIsNone(self.app.confirm_action)
        self.app.handle_event(pygame.event.Event(pygame.QUIT))
        self.click("confirm")
        self.assertTrue(self.app.running)
        self.assertEqual(self.app.pending_leave, "quit")
        self.assertEqual(run.snapshot()["status"], "stopping")
        self.executor.finish()
        self.app.tick()
        self.assertFalse(self.app.running)
        self.assertEqual(run.snapshot()["status"], "stopped")

    def test_comparison_watch_saved_game_during_run_and_stop(self):
        self.prepare_comparison_configs()
        (self.project / "openings.txt").write_text("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", encoding="utf-8")
        self.click("mode:records")
        self.click("comparison_new")
        self.enter_comparison_field("openings", "openings.txt")
        self.click("start")
        progress = ComparisonRun._progress
        watched = False
        def watch(run, state):
            nonlocal watched
            progress(run, state)
            if state["saved_games"] == 1 and not watched:
                watched = True
                self.click("batch_watch")
                self.assertEqual(self.app.mode, "replay")
                self.click("batch_progress")
                self.click("stop")
        with patch.object(ComparisonRun, "_progress", watch):
            self.executor.finish()
        self.assertTrue(watched)
        run = self.app.batch
        self.assertEqual(run.snapshot()["status"], "stopped")
        self.click("batch_results")
        self.assertEqual(self.app.records_view.summary.comparison.incomplete_pairs, 1)
        self.assertIsNone(self.app.records_view.summary.comparison.paired_score_rate)

    def test_comparison_worker_error_is_visible_and_saved(self):
        self.prepare_comparison_configs()
        self.click("mode:records")
        self.click("comparison_new")
        self.click("start")
        with patch("engine.sessions.evaluation_comparison.play_game", side_effect=RuntimeError("測試搜尋錯誤")):
            self.executor.finish()
        self.assertEqual(self.app.batch.snapshot()["status"], "failed")
        self.assertIn("測試搜尋錯誤", self.app.batch.snapshot()["error"])
        self.click("batch_results")
        summary = self.app.records_view.summary
        self.assertEqual(summary.status, "failed")
        self.assertIn("測試搜尋錯誤", summary.error)
        self.assertEqual(summary.games, ())


if __name__ == "__main__":
    unittest.main()
