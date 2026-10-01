"""Handcrafted piece-square tables and related evaluation helpers."""

import chess

PieceSquareTable = tuple[tuple[float, ...], ...]

# Tables are written in board-display order from White's perspective:
# row 0 is rank 8 and row 7 is rank 1.
PAWN_PST: PieceSquareTable = (
    (0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00),
    (0.18, 0.20, 0.22, 0.25, 0.25, 0.22, 0.20, 0.18),
    (0.10, 0.12, 0.15, 0.18, 0.18, 0.15, 0.12, 0.10),
    (0.08, 0.10, 0.15, 0.20, 0.20, 0.15, 0.10, 0.08),
    (0.05, 0.08, 0.12, 0.18, 0.18, 0.12, 0.08, 0.05),
    (0.03, 0.05, 0.08, 0.12, 0.12, 0.08, 0.05, 0.03),
    (0.02, 0.03, 0.05, 0.08, 0.08, 0.05, 0.03, 0.02),
    (0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00),
)

KNIGHT_PST: PieceSquareTable = (
    (-0.40, -0.25, -0.15, -0.10, -0.10, -0.15, -0.25, -0.40),
    (-0.25, -0.10, 0.00, 0.05, 0.05, 0.00, -0.10, -0.25),
    (-0.15, 0.05, 0.15, 0.20, 0.20, 0.15, 0.05, -0.15),
    (-0.10, 0.08, 0.20, 0.30, 0.30, 0.20, 0.08, -0.10),
    (-0.10, 0.08, 0.20, 0.30, 0.30, 0.20, 0.08, -0.10),
    (-0.15, 0.05, 0.15, 0.20, 0.20, 0.15, 0.05, -0.15),
    (-0.25, -0.10, 0.00, 0.05, 0.05, 0.00, -0.10, -0.25),
    (-0.40, -0.25, -0.15, -0.10, -0.10, -0.15, -0.25, -0.40),
)

BISHOP_PST: PieceSquareTable = (
    (-0.10, -0.05, -0.03, -0.02, -0.02, -0.03, -0.05, -0.10),
    (-0.05, 0.02, 0.05, 0.05, 0.05, 0.05, 0.02, -0.05),
    (-0.03, 0.05, 0.10, 0.12, 0.12, 0.10, 0.05, -0.03),
    (-0.02, 0.05, 0.12, 0.18, 0.18, 0.12, 0.05, -0.02),
    (-0.02, 0.05, 0.12, 0.18, 0.18, 0.12, 0.05, -0.02),
    (-0.03, 0.05, 0.10, 0.12, 0.12, 0.10, 0.05, -0.03),
    (-0.05, 0.02, 0.05, 0.05, 0.05, 0.05, 0.02, -0.05),
    (-0.10, -0.05, -0.03, -0.02, -0.02, -0.03, -0.05, -0.10),
)

ROOK_PST: PieceSquareTable = (
    (0.00, 0.02, 0.04, 0.05, 0.05, 0.04, 0.02, 0.00),
    (0.08, 0.10, 0.10, 0.12, 0.12, 0.10, 0.10, 0.08),
    (0.00, 0.02, 0.04, 0.05, 0.05, 0.04, 0.02, 0.00),
    (0.00, 0.02, 0.05, 0.08, 0.08, 0.05, 0.02, 0.00),
    (0.00, 0.02, 0.05, 0.08, 0.08, 0.05, 0.02, 0.00),
    (0.00, 0.01, 0.03, 0.05, 0.05, 0.03, 0.01, 0.00),
    (0.00, 0.02, 0.03, 0.05, 0.05, 0.03, 0.02, 0.00),
    (0.02, 0.04, 0.05, 0.08, 0.08, 0.05, 0.04, 0.02),
)

QUEEN_PST: PieceSquareTable = (
    (-0.05, -0.02, -0.01, 0.00, 0.00, -0.01, -0.02, -0.05),
    (-0.02, 0.00, 0.01, 0.02, 0.02, 0.01, 0.00, -0.02),
    (-0.01, 0.01, 0.03, 0.05, 0.05, 0.03, 0.01, -0.01),
    (0.00, 0.02, 0.05, 0.08, 0.08, 0.05, 0.02, 0.00),
    (0.00, 0.02, 0.05, 0.08, 0.08, 0.05, 0.02, 0.00),
    (-0.01, 0.01, 0.03, 0.05, 0.05, 0.03, 0.01, -0.01),
    (-0.02, 0.00, 0.01, 0.03, 0.03, 0.01, 0.00, -0.02),
    (-0.05, -0.02, 0.00, 0.03, 0.03, 0.00, -0.02, -0.05),
)

KING_PST: PieceSquareTable = (
    (-0.25, -0.20, -0.18, -0.15, -0.15, -0.18, -0.20, -0.25),
    (-0.20, -0.15, -0.12, -0.10, -0.10, -0.12, -0.15, -0.20),
    (-0.15, -0.12, -0.10, -0.08, -0.08, -0.10, -0.12, -0.15),
    (-0.12, -0.10, -0.15, -0.20, -0.20, -0.15, -0.10, -0.12),
    (-0.08, -0.10, -0.18, -0.25, -0.25, -0.18, -0.10, -0.08),
    (0.00, -0.03, -0.08, -0.15, -0.15, -0.08, -0.03, 0.00),
    (0.08, 0.10, 0.02, -0.05, -0.05, 0.02, 0.10, 0.12),
    (0.12, 0.15, 0.18, 0.05, 0.08, 0.15, 0.20, 0.15),
)

WHITE_PIECE_SQUARE_TABLES: dict[int, PieceSquareTable] = {
    chess.PAWN: PAWN_PST,
    chess.KNIGHT: KNIGHT_PST,
    chess.BISHOP: BISHOP_PST,
    chess.ROOK: ROOK_PST,
    chess.QUEEN: QUEEN_PST,
    chess.KING: KING_PST,
}


def _mirror_rank(square: chess.Square) -> chess.Square:
    return chess.square(chess.square_file(square), 7 - chess.square_rank(square))


def _table_coordinates(square: chess.Square) -> tuple[int, int]:
    return 7 - chess.square_rank(square), chess.square_file(square)


def _white_perspective_square(piece: chess.Piece, square: chess.Square) -> chess.Square:
    if piece.color == chess.WHITE:
        return square
    return _mirror_rank(square)


def get_piece_square_value(piece: chess.Piece, square: chess.Square) -> float:
    """Return the PST bonus for one piece on one square."""

    if piece.piece_type not in WHITE_PIECE_SQUARE_TABLES:
        raise ValueError(f"Unsupported piece type for PST lookup: {piece.piece_type}")

    white_view_square = _white_perspective_square(piece, square)
    row_index, file_index = _table_coordinates(white_view_square)
    return WHITE_PIECE_SQUARE_TABLES[piece.piece_type][row_index][file_index]


def evaluate_piece_square_tables_for_color(board: chess.Board, color: chess.Color) -> float:
    """Return the raw PST total for one side."""

    total = 0.0
    for square, piece in board.piece_map().items():
        if piece.color == color:
            total += get_piece_square_value(piece, square)
    return total


def evaluate_piece_square_tables(board: chess.Board) -> float:
    """Return White PST total minus Black PST total."""

    white_total = evaluate_piece_square_tables_for_color(board, chess.WHITE)
    black_total = evaluate_piece_square_tables_for_color(board, chess.BLACK)
    return white_total - black_total


# Endgame v1 changes only the king: central activity replaces shelter bonuses.
KING_ENDGAME_PST: PieceSquareTable = (
    (-0.30, -0.20, -0.10, -0.05, -0.05, -0.10, -0.20, -0.30),
    (-0.20, -0.10, 0.00, 0.05, 0.05, 0.00, -0.10, -0.20),
    (-0.10, 0.00, 0.10, 0.15, 0.15, 0.10, 0.00, -0.10),
    (-0.05, 0.05, 0.15, 0.25, 0.25, 0.15, 0.05, -0.05),
    (-0.05, 0.05, 0.15, 0.25, 0.25, 0.15, 0.05, -0.05),
    (-0.10, 0.00, 0.10, 0.15, 0.15, 0.10, 0.00, -0.10),
    (-0.20, -0.10, 0.00, 0.05, 0.05, 0.00, -0.10, -0.20),
    (-0.30, -0.20, -0.10, -0.05, -0.05, -0.10, -0.20, -0.30),
)
ENDGAME_PIECE_SQUARE_TABLES = {**WHITE_PIECE_SQUARE_TABLES, chess.KING: KING_ENDGAME_PST}


def evaluate_endgame_piece_square_tables(board: chess.Board) -> float:
    """Endgame PST v1, with the same rank mirror and White perspective."""
    totals = {chess.WHITE: 0.0, chess.BLACK: 0.0}
    for square, piece in board.piece_map().items():
        row, file = _table_coordinates(_white_perspective_square(piece, square))
        totals[piece.color] += ENDGAME_PIECE_SQUARE_TABLES[piece.piece_type][row][file]
    return totals[chess.WHITE] - totals[chess.BLACK]


def middlegame_phase(board: chess.Board) -> float:
    """Model v1: N/B=1, R=2, Q=4; both sides total 24 initially.

    Pawns/kings do not affect phase; promotions are capped at the initial total.
    This depends on counts, never configurable material prices or side to move.
    """
    units = sum(len(board.pieces(kind, color)) * weight
                for kind, weight in ((chess.KNIGHT, 1), (chess.BISHOP, 1),
                                     (chess.ROOK, 2), (chess.QUEEN, 4))
                for color in chess.COLORS)
    return min(units, 24) / 24.0
