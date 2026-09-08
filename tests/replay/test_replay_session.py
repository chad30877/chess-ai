"""Minimal tests for ReplaySession navigation behavior."""

import unittest

import chess

from engine.replay.replay_session import ReplaySession


class ReplaySessionTest(unittest.TestCase):
    def test_navigation_forward_backward_and_bounds(self) -> None:
        moves_uci = ["e2e4", "e7e5", "g1f3"]
        session = ReplaySession(chess.STARTING_FEN, moves_uci)

        board = chess.Board(chess.STARTING_FEN)
        expected_positions = [board.fen()]
        for move_uci in moves_uci:
            board.push(chess.Move.from_uci(move_uci))
            expected_positions.append(board.fen())

        self.assertEqual(session.positions, expected_positions)
        self.assertEqual(session.current_ply, 0)
        self.assertEqual(session.total_ply(), 3)

        session.prev()
        self.assertEqual(session.current_ply, 0)

        session.next()
        self.assertEqual(session.current_ply, 1)
        self.assertEqual(session.current_fen(), expected_positions[1])

        session.next()
        session.prev()
        self.assertEqual(session.current_ply, 1)
        self.assertEqual(session.current_fen(), expected_positions[1])

        session.goto_ply(2)
        self.assertEqual(session.current_fen(), expected_positions[2])

        session.last()
        self.assertEqual(session.current_ply, 3)
        self.assertEqual(session.current_fen(), expected_positions[3])

        session.next()
        self.assertEqual(session.current_ply, 3)

        session.first()
        self.assertEqual(session.current_ply, 0)
        self.assertEqual(session.current_fen(), expected_positions[0])

    def test_goto_ply_out_of_range_raises(self) -> None:
        session = ReplaySession(chess.STARTING_FEN, ["e2e4"])

        with self.assertRaises(IndexError):
            session.goto_ply(-1)

        with self.assertRaises(IndexError):
            session.goto_ply(2)


if __name__ == "__main__":
    unittest.main()
