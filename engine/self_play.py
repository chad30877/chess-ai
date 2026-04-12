"""Batch self-play utilities."""

from dataclasses import dataclass

from engine.game import create_board, is_game_over, make_move


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

        result = board.result()
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

        result = board.result()
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
