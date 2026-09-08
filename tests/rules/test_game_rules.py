"""Shared rules and replay history regressions."""

import unittest

import chess

from engine.game import create_board, get_legal_moves, get_outcome, get_result, make_move
from engine.replay.replay_session import ReplaySession
from engine.sessions.self_play import collect_self_play_data, play_game, run_batch_matches


class ScriptedPlayer:
    def choose_move(self, board):
        # For the legacy API tests, each side independently follows the same script.
        script = ["f2f3", "e7e5", "g2g4", "d8h4"]
        return chess.Move.from_uci(script[len(board.move_stack)])


class SharedRulesTest(unittest.TestCase):
    def test_self_play_and_replay_agree_on_repetition_policies(self):
        class RepeatingPlayer:
            def choose_move(self, board):
                cycle = ["g1f3", "g8f6", "f3g1", "f6g8"]
                return chess.Move.from_uci(cycle[len(board.move_stack) % 4])

        for claim, plies, reason in [(False, 16, "fivefold_repetition"),
                                     (True, 7, "threefold_repetition")]:
            player = RepeatingPlayer()
            game = play_game(1, player, player, "a", "b", claim_draw=claim)
            session = ReplaySession(game.initial_fen, [r["selected_move"] for r in game.positions],
                                    claim_draw=claim)
            session.last()
            self.assertEqual(len(game.positions), plies)
            self.assertEqual(game.termination, reason)
            self.assertEqual(session.current_outcome().termination.name.lower(), reason)
            self.assertEqual(session.current_result(), game.result)
            self.assertEqual(session.current_fen(), game.final_fen)

    def test_illegal_move_does_not_change_board(self):
        board = create_board()
        self.assertEqual(len(get_legal_moves(board)), 20)
        with self.assertRaises(ValueError):
            make_move(board, chess.Move.from_uci("e2e5"))
        self.assertEqual(board.fen(), chess.STARTING_FEN)
        self.assertEqual(board.move_stack, [])

    def test_special_moves_replay_identically(self):
        cases = [
            (chess.STARTING_FEN, "e2e4 a7a6 e4e5 d7d5 e5d6"),
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1 e8c8"),
            ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a7a8q"),
        ]
        for fen, moves in cases:
            with self.subTest(moves=moves):
                board = create_board(fen)
                session = ReplaySession(fen, moves.split())
                for ply, move in enumerate(moves.split(), 1):
                    make_move(board, chess.Move.from_uci(move))
                    session.goto_ply(ply)
                    self.assertEqual(session.current_board().fen(), board.fen())
                    self.assertEqual(session.current_result(), get_result(board))

    def test_fivefold_history_survives_navigation_and_returned_board_mutation(self):
        moves = "g1f3 g8f6 f3g1 f6g8".split() * 4
        session = ReplaySession(chess.STARTING_FEN, moves)
        session.last()
        self.assertEqual(session.current_outcome().termination, chess.Termination.FIVEFOLD_REPETITION)
        self.assertIsNone(get_outcome(create_board(session.current_fen())))
        copy = session.current_board()
        copy.clear_stack()
        session.first()
        self.assertEqual(session.current_result(), "*")
        session.last()
        self.assertEqual(session.current_result(), "1/2-1/2")
        self.assertEqual(len(session.current_board().move_stack), 16)

    def test_claim_policy_includes_announced_next_move(self):
        moves = ("g1f3 g8f6 f3g1 f6g8".split() * 2)[:7]
        for claim in (False, True):
            session = ReplaySession(chess.STARTING_FEN, moves, claim_draw=claim)
            session.last()
            self.assertEqual(session.current_result(), "1/2-1/2" if claim else "*")
        board = create_board("7k/8/8/8/8/8/R7/K7 w - - 100 51")
        self.assertIsNone(get_outcome(board))
        self.assertEqual(get_outcome(board, claim_draw=True).termination, chess.Termination.FIFTY_MOVES)

    def test_terminal_rules_take_precedence_over_execution_limit(self):
        player = ScriptedPlayer()
        game = play_game(1, player, player, "a", "b", max_plies=4)
        self.assertEqual((game.result, game.status, game.termination), ("0-1", "completed", "checkmate"))
        truncated = play_game(1, player, player, "a", "b", max_plies=3)
        self.assertEqual((truncated.result, truncated.status, truncated.termination), ("*", "truncated", "max_plies"))

    def test_zero_move_chess_endings(self):
        cases = [
            ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "stalemate"),
            ("7k/8/8/8/8/8/8/K7 w - - 0 1", "insufficient_material"),
            ("7k/8/8/8/8/8/R7/K7 w - - 150 76", "seventyfive_moves"),
        ]
        for fen, reason in cases:
            with self.subTest(reason=reason):
                game = play_game(1, None, None, "a", "b", initial_fen=fen, max_plies=0)
                self.assertEqual((game.result, game.termination), ("1/2-1/2", reason))
                self.assertEqual(game.positions, [])

    def test_legacy_self_play_interfaces_keep_results(self):
        batch = run_batch_matches(ScriptedPlayer, ScriptedPlayer, 2)
        moves, collected = collect_self_play_data(ScriptedPlayer, ScriptedPlayer, 2)
        self.assertEqual(batch, collected)
        self.assertEqual(len(moves), 8)
        self.assertEqual([game.result for game in batch.games], ["0-1", "0-1"])


if __name__ == "__main__":
    unittest.main()
