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
from engine.live_session import LiveSession, LiveSettings
from engine.replay_loader import load_replay_json
from test_live_session import ManualExecutor
from engine.replay_catalog import ReplayCatalog


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
        self.assertEqual({b.action for b in self.app.buttons}, {"mode:auto", "mode:human", "mode:replay"})
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
        self.assertIsNone(self.app.browser)

    def test_catalog_navigation_invalid_json_and_sample_remain_usable(self):
        folder = self.project / "data/replays"
        folder.mkdir(parents=True)
        sample = json.loads(Path("data/replays/sample_replay.json").read_text(encoding="utf-8"))
        sample["metadata"].update(started_at="2026-09-09T12:34:56+08:00", game_id="20260909_000001")
        valid = folder / "20260909_000001.json"
        valid.write_text(json.dumps(sample), encoding="utf-8")
        (folder / "bad.json").write_text("{", encoding="utf-8")
        self.click("mode:replay")
        self.assertEqual(self.app.browser.skipped, 1)
        self.click("entry:0")
        self.assertEqual(self.app.browser.level, "group")
        self.click("entry:0")
        self.assertEqual(self.app.browser.level, "game")
        self.click("entry:0")
        # A replay can disappear after the index was read without losing the browser.
        valid.unlink()
        self.click("browser_open")
        self.assertTrue(self.app.browser.error)
        valid.write_text(json.dumps(sample), encoding="utf-8")
        self.click("browser_open")
        self.assertIsNone(self.app.browser)
        self.assertEqual(self.app.replay.total_ply(), 6)
        self.click("sample")
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

    def test_invalid_cli_replay_shows_error_screen(self):
        app = ChessApplication(self.screen, "missing-replay.json", executor=self.executor)
        self.addCleanup(app.close)
        app.render()
        self.assertEqual(app.mode, "replay")
        self.assertIsNone(app.replay)
        self.assertIn("無法開啟", app.message)


if __name__ == "__main__":
    unittest.main()
