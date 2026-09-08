"""Tests for handcrafted piece-square tables."""

import unittest

import chess

from engine.pst import (
    evaluate_piece_square_tables,
    evaluate_piece_square_tables_for_color,
    get_piece_square_value,
)


class PieceSquareTablesTest(unittest.TestCase):
    def test_starting_position_piece_square_score_is_symmetric(self) -> None:
        board = chess.Board()

        white_total = evaluate_piece_square_tables_for_color(board, chess.WHITE)
        black_total = evaluate_piece_square_tables_for_color(board, chess.BLACK)

        self.assertAlmostEqual(white_total, black_total)
        self.assertAlmostEqual(evaluate_piece_square_tables(board), 0.0)

    def test_knight_scores_better_when_centralized(self) -> None:
        edge_board = chess.Board("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1")
        center_board = chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1")

        self.assertGreater(
            evaluate_piece_square_tables(center_board),
            evaluate_piece_square_tables(edge_board),
        )

    def test_black_uses_mirrored_white_table(self) -> None:
        white_knight = chess.Piece(chess.KNIGHT, chess.WHITE)
        black_knight = chess.Piece(chess.KNIGHT, chess.BLACK)

        self.assertAlmostEqual(
            get_piece_square_value(white_knight, chess.C3),
            get_piece_square_value(black_knight, chess.C6),
        )


if __name__ == "__main__":
    unittest.main()
