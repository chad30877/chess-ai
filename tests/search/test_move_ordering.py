"""Tests for basic alpha-beta move ordering."""

import unittest

import chess

from engine.search.ordering import order_moves


class MoveOrderingTest(unittest.TestCase):
    def test_promotions_precede_captures_and_quiet_moves(self) -> None:
        board = chess.Board("4k3/P6q/8/8/8/8/8/4K2R w K - 0 1")
        moves = [
            chess.Move.from_uci("e1f1"),
            chess.Move.from_uci("h1h2"),
            chess.Move.from_uci("a7a8q"),
            chess.Move.from_uci("h1h7"),
        ]
        legal_moves = [move for move in moves if move in board.legal_moves]
        original_fen = board.fen()

        ordered = order_moves(board, legal_moves)

        self.assertEqual(ordered[0], chess.Move.from_uci("a7a8q"))
        self.assertEqual(ordered[1], chess.Move.from_uci("h1h7"))
        self.assertEqual(set(ordered[2:]), {
            chess.Move.from_uci("e1f1"),
            chess.Move.from_uci("h1h2"),
        })
        self.assertEqual(board.fen(), original_fen)

    def test_capture_order_uses_victim_and_attacker_values(self) -> None:
        board = chess.Board("4k3/8/8/3q4/2P2N2/8/8/4K3 w - - 0 1")
        pawn_takes_queen = chess.Move.from_uci("c4d5")
        knight_takes_queen = chess.Move.from_uci("f4d5")

        ordered = order_moves(board, [knight_takes_queen, pawn_takes_queen])

        self.assertEqual(ordered, [pawn_takes_queen, knight_takes_queen])

    def test_preferred_move_precedes_the_normal_priority_order(self) -> None:
        board = chess.Board()
        preferred = chess.Move.from_uci("e2e4")
        moves = [
            chess.Move.from_uci("g1f3"),
            preferred,
            chess.Move.from_uci("d2d4"),
        ]

        ordered = order_moves(board, moves, preferred_move=preferred)

        self.assertEqual(ordered[0], preferred)
        self.assertEqual(set(ordered), set(moves))


if __name__ == "__main__":
    unittest.main()
