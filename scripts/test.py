# test.py
import chess

FEN = "2b1k3/rppp4/2n2r2/p6p/4p3/4K3/7q/8 b - - 7 33"


def main():
    board = chess.Board(FEN)
    board.push(chess.Move.from_uci("h2c2"))

    print("=== Board ===")
    print(board)
    print()

    print("=== Basic Info ===")
    print("FEN:", board.fen())
    print("Side to move:", "Black" if board.turn == chess.BLACK else "White")
    print("Is check:", board.is_check())
    print("Is checkmate:", board.is_checkmate())
    print("Is stalemate:", board.is_stalemate())
    print("Is game over:", board.is_game_over())
    print("Result (if over):", board.result(claim_draw=True) if board.is_game_over(claim_draw=True) else "Not over")
    print()

    legal_moves = list(board.legal_moves)

    print("=== Legal Moves ===")
    print("Legal move count:", len(legal_moves))
    for i, move in enumerate(legal_moves, start=1):
        print(f"{i:2d}. UCI={move.uci():5s} SAN={board.san(move)}")

    print()
    if not legal_moves:
        print("No legal moves.")
    else:
        print("This position is NOT an end position under normal chess rules.")


if __name__ == "__main__":
    main()