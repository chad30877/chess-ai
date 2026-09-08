"""Batch self-play utilities."""

from dataclasses import dataclass

import chess

from engine.game import create_board, get_outcome, get_result, is_game_over, make_move
from engine.data_ids import now_iso


@dataclass(frozen=True)
class PlayedGame:
    game_id: int
    white_player: str
    black_player: str
    initial_fen: str
    final_fen: str
    result: str
    status: str
    termination: str
    positions: list[dict]
    started_at: str = ""
    finished_at: str = ""


def play_game(
    game_id: int, white_player, black_player, white_name: str, black_name: str,
    *, initial_fen: str = chess.STARTING_FEN, claim_draw: bool = False,
    max_plies: int | None = None,
    control=None,
) -> PlayedGame:
    """Collect one game, keeping execution truncation separate from chess rules."""
    if game_id <= 0:
        raise ValueError("game_id must be greater than 0")
    if max_plies is not None and max_plies < 0:
        raise ValueError("max_plies must be non-negative")
    started_at = now_iso()
    board = create_board(initial_fen)
    initial_fen = board.fen()
    positions: list[dict] = []
    while True:
        outcome = get_outcome(board, claim_draw=claim_draw)
        if outcome is not None:
            result, status = outcome.result(), "completed"
            termination = outcome.termination.name.lower()
            break
        if max_plies is not None and len(positions) >= max_plies:
            result, status, termination = "*", "truncated", "max_plies"
            break
        if control is not None and not control():
            result, status, termination = "*", "truncated", "user_stop"
            break
        player = white_player if board.turn else black_player
        move = player.choose_move(board)
        if control is not None and not control():
            result, status, termination = "*", "truncated", "user_stop"
            break
        row = {
            "game_id": game_id, "ply": len(positions) + 1, "fen": board.fen(),
            "side_to_move": "white" if board.turn else "black",
            "selected_move": move.uci(), "white_player": white_name,
            "black_player": black_name,
        }
        make_move(board, move)
        positions.append(row)
    for row in positions:
        row["result"] = result
    return PlayedGame(game_id, white_name, black_name, initial_fen, board.fen(),
                      result, status, termination, positions, started_at, now_iso())


@dataclass(frozen=True)
class GameRecord:
    game_id: int
    white_player: str
    black_player: str
    result: str
    move_count: int


@dataclass(frozen=True)
class BatchResult:
    games: list[GameRecord]
    stats: dict[str, int]


@dataclass(frozen=True)
class MoveRecord:
    game_id: int
    ply: int
    fen: str
    side_to_move: str
    selected_move: str
    result: str


def run_batch_matches(
    player_a_cls: type,
    player_b_cls: type,
    num_games: int,
    player_a_kwargs: dict | None = None,
    player_b_kwargs: dict | None = None,
) -> BatchResult:
    """Run N games between two player classes with alternating colors."""
    if num_games <= 0:
        raise ValueError("num_games must be greater than 0")

    player_a_kwargs = player_a_kwargs or {}
    player_b_kwargs = player_b_kwargs or {}

    player_a_name = player_a_cls.__name__
    player_b_name = player_b_cls.__name__

    stats = {
        "total_games": num_games,
        f"{player_a_name}_wins": 0,
        f"{player_b_name}_wins": 0,
        "draws": 0,
    }

    games: list[GameRecord] = []

    for game_id in range(1, num_games + 1):
        board = create_board()

        if game_id % 2 == 1:
            white_player = player_a_cls(**player_a_kwargs)
            black_player = player_b_cls(**player_b_kwargs)
            white_name = player_a_name
            black_name = player_b_name
        else:
            white_player = player_b_cls(**player_b_kwargs)
            black_player = player_a_cls(**player_a_kwargs)
            white_name = player_b_name
            black_name = player_a_name

        move_count = 0
        while not is_game_over(board):
            current_player = white_player if board.turn else black_player
            move = current_player.choose_move(board)
            make_move(board, move)
            move_count += 1

        result = get_result(board)
        if result == "1-0":
            stats[f"{white_name}_wins"] += 1
        elif result == "0-1":
            stats[f"{black_name}_wins"] += 1
        else:
            stats["draws"] += 1

        games.append(
            GameRecord(
                game_id=game_id,
                white_player=white_name,
                black_player=black_name,
                result=result,
                move_count=move_count,
            )
        )

    return BatchResult(games=games, stats=stats)


def collect_self_play_data(
    player_a_cls: type,
    player_b_cls: type,
    num_games: int,
    player_a_kwargs: dict | None = None,
    player_b_kwargs: dict | None = None,
) -> tuple[list[MoveRecord], BatchResult]:
    """Collect move-level records and batch statistics from self-play games."""
    if num_games <= 0:
        raise ValueError("num_games must be greater than 0")

    player_a_kwargs = player_a_kwargs or {}
    player_b_kwargs = player_b_kwargs or {}

    player_a_name = player_a_cls.__name__
    player_b_name = player_b_cls.__name__

    stats = {
        "total_games": num_games,
        f"{player_a_name}_wins": 0,
        f"{player_b_name}_wins": 0,
        "draws": 0,
    }

    games: list[GameRecord] = []
    move_records: list[MoveRecord] = []

    for game_id in range(1, num_games + 1):
        board = create_board()

        if game_id % 2 == 1:
            white_player = player_a_cls(**player_a_kwargs)
            black_player = player_b_cls(**player_b_kwargs)
            white_name = player_a_name
            black_name = player_b_name
        else:
            white_player = player_b_cls(**player_b_kwargs)
            black_player = player_a_cls(**player_a_kwargs)
            white_name = player_b_name
            black_name = player_a_name

        game_moves: list[tuple[int, str, str, str]] = []
        ply = 0

        while not is_game_over(board):
            current_player = white_player if board.turn else black_player
            fen_before_move = board.fen()
            side_to_move = "white" if board.turn else "black"

            move = current_player.choose_move(board)
            selected_move = move.uci()
            make_move(board, move)

            ply += 1
            game_moves.append((ply, fen_before_move, side_to_move, selected_move))

        result = get_result(board)
        move_count = ply

        if result == "1-0":
            stats[f"{white_name}_wins"] += 1
        elif result == "0-1":
            stats[f"{black_name}_wins"] += 1
        else:
            stats["draws"] += 1

        games.append(
            GameRecord(
                game_id=game_id,
                white_player=white_name,
                black_player=black_name,
                result=result,
                move_count=move_count,
            )
        )

        for record_ply, fen, side, move_uci in game_moves:
            move_records.append(
                MoveRecord(
                    game_id=game_id,
                    ply=record_ply,
                    fen=fen,
                    side_to_move=side,
                    selected_move=move_uci,
                    result=result,
                )
            )

    return move_records, BatchResult(games=games, stats=stats)
