"""Live-game state transitions, worker isolation, and shared rule outcomes."""

import unittest
from tests.helpers.executors import ManualExecutor

import chess

from engine.evaluation.config import EvaluationConfig
from engine.sessions.live_session import LiveSession, LiveSettings
from engine.replay.replay_session import ReplaySession


class LiveSessionTest(unittest.TestCase):
    def setUp(self):
        self.executor = ManualExecutor()

    def test_start_wait_interval_and_snapshot_isolation(self):
        game = LiveSession(LiveSettings(interval=1))
        game.tick(100, self.executor)
        self.assertEqual(self.executor.jobs, [])
        game.start(100)
        game.tick(100.5, self.executor)
        self.assertEqual(self.executor.jobs, [])
        game.tick(101, self.executor)
        snapshot = self.executor.jobs[0][2][0]
        self.assertIsNot(snapshot, game.board)
        self.executor.finish()
        game.tick(101, self.executor)
        self.assertEqual(len(game.move_items), 1)
        game.tick(101.9, self.executor)
        self.assertEqual(len(self.executor.jobs), 1)

    def test_pause_holds_completed_result_and_step_applies_exactly_one(self):
        game = LiveSession(LiveSettings(interval=0))
        game.start()
        game.tick(0, self.executor)
        game.pause()
        self.executor.finish()
        game.tick(1, self.executor)
        self.assertEqual(len(game.move_items), 0)
        game.request_step()
        game.request_step()
        game.tick(2, self.executor)
        game.tick(3, self.executor)
        self.assertEqual(len(game.move_items), 1)
        self.assertEqual(game.status, "paused")
        self.assertEqual(len(self.executor.jobs), 1)
        game.resume()
        game.tick(4, self.executor)
        self.assertEqual(len(self.executor.jobs), 2)

    def test_stopped_worker_cannot_mutate_old_or_new_session(self):
        old = LiveSession(LiveSettings(interval=0))
        old.start()
        old.tick(0, self.executor)
        self.executor.jobs[0][0].set_running_or_notify_cancel()
        old.stop()
        new = LiveSession(LiveSettings(interval=0))
        new.start()
        self.executor.finish(0)
        old.tick(1, self.executor)
        self.assertEqual(old.board.fen(), chess.STARTING_FEN)
        self.assertEqual(new.board.fen(), chess.STARTING_FEN)
        self.assertEqual((old.status, old.result, old.termination), ("stopped", "*", "user_stop"))

    def test_human_turn_guards_illegal_moves_and_ai_turn(self):
        game = LiveSession(LiveSettings(white="Human", interval=0))
        with self.assertRaises(ValueError):
            game.play_human(chess.Move.from_uci("e2e4"))
        game.start()
        with self.assertRaises(ValueError):
            game.play_human(chess.Move.from_uci("e2e5"))
        self.assertEqual({m.uci() for m in game.legal_from(chess.E2)}, {"e2e3", "e2e4"})
        game.play_human(chess.Move.from_uci("e2e4"))
        with self.assertRaises(ValueError):
            game.play_human(chess.Move.from_uci("e7e5"))
        game.tick(0, self.executor)
        self.assertEqual(len(self.executor.jobs[0][2][0].move_stack), 1)
        self.executor.finish()
        game.tick(1, self.executor)
        self.assertTrue(game.human_turn)

    def test_black_human_waits_for_white_ai(self):
        game = LiveSession(LiveSettings(black="Human", interval=0))
        game.start()
        self.assertFalse(game.human_turn)
        game.tick(0, self.executor)
        self.executor.finish()
        game.tick(1, self.executor)
        self.assertTrue(game.human_turn)

    def test_ai_failure_is_reported_without_draw_or_partial_move(self):
        for result in (RuntimeError("test failure"), chess.Move.from_uci("e2e5")):
            with self.subTest(result=result):
                game = LiveSession(LiveSettings(interval=0))
                game.start()
                game.tick(0, self.executor)
                future = self.executor.jobs[-1][0]
                if isinstance(result, Exception):
                    future.set_exception(result)
                else:
                    future.set_result(result)
                game.tick(1, self.executor)
                self.assertEqual((game.status, game.result, game.termination), ("failed", "*", "ai_error"))
                self.assertEqual(game.board.fen(), chess.STARTING_FEN)

    def test_checkmate_precedes_limit_and_replays_consistently(self):
        game = LiveSession(LiveSettings(white="Human", black="Human", max_plies=4))
        game.start()
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            game.play_human(chess.Move.from_uci(uci))
        self.assertEqual((game.status, game.result, game.termination), ("completed", "0-1", "checkmate"))
        data = game.replay_payload()
        replay = ReplaySession(data["initial_fen"], data["moves_uci"])
        replay.last()
        self.assertEqual(replay.current_fen(), game.board.fen())
        self.assertEqual(replay.current_result(), game.result)
        self.assertEqual(game.move_items[-1]["san"], "Qh4#")

    def test_repetition_history_preserved_for_both_claim_policies(self):
        for claim, expected in ((False, 16), (True, 7)):
            game = LiveSession(LiveSettings(white="Human", black="Human", claim_draw=claim))
            game.start()
            moves = ["g1f3", "g8f6", "f3g1", "f6g8"]
            while game.active:
                game.play_human(chess.Move.from_uci(moves[len(game.move_items) % 4]))
            self.assertEqual(len(game.move_items), expected)
            replay = ReplaySession(game.initial_fen, [m["uci"] for m in game.move_items], claim_draw=claim)
            replay.last()
            self.assertEqual(replay.current_result(), game.result)

    def test_zero_ply_ending_and_execution_limit(self):
        game = LiveSession(LiveSettings(max_plies=0))
        game.start()
        self.assertEqual((game.status, game.result), ("truncated", "*"))
        game = LiveSession(LiveSettings(initial_fen="7k/8/8/8/8/8/8/K7 w - - 0 1", max_plies=0))
        game.start()
        self.assertEqual((game.status, game.result), ("completed", "1/2-1/2"))

    def test_replay_saves_the_actual_injected_evaluation_settings(self):
        config = EvaluationConfig(piece_values={"B": 3.75}, pst_weight=0.25)
        game = LiveSession(LiveSettings(
            white="Human", black="Greedy", black_evaluation=config,
        ))

        saved = game.replay_payload()["metadata"]["strategies"]["black"]["evaluator"]

        self.assertEqual(saved["terms"]["material"]["piece_values"]["B"], 3.75)
        self.assertEqual(saved["terms"]["piece_square"]["weight"], 0.25)


if __name__ == "__main__":
    unittest.main()
