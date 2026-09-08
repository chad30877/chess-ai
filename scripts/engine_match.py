"""Run matches between simple one-ply engines using different evaluators."""

import argparse
import random
from dataclasses import dataclass

from engine.evaluator import MaterialEvaluator
from engine.game import create_board, get_result, is_game_over, make_move
from engine.ml_evaluator import MLEvaluator
from engine.players import GreedyPlayer


@dataclass(frozen=True)
class MatchStats:
    wins: int
    draws: int
    losses: int


def build_player(engine_type: str, game_id: int, color_offset: int, model_path: str | None) -> GreedyPlayer:
    rng = random.Random(game_id * 2 + color_offset)

    if engine_type == "material":
        return GreedyPlayer(evaluator=MaterialEvaluator(), rng=rng)
    if engine_type == "ml":
        return GreedyPlayer(evaluator=MLEvaluator(model_path=model_path), rng=rng)

    raise ValueError(f"Unsupported engine type: {engine_type}")


def play_one_game(
    game_id: int,
    engine_a: str,
    engine_b: str,
    model_path: str | None,
) -> str:
    """Return result from engine A perspective: win, draw, or loss."""
    board = create_board()

    if game_id % 2 == 1:
        white_player = build_player(engine_a, game_id, 1, model_path)
        black_player = build_player(engine_b, game_id, 2, model_path)
        engine_a_is_white = True
    else:
        white_player = build_player(engine_b, game_id, 1, model_path)
        black_player = build_player(engine_a, game_id, 2, model_path)
        engine_a_is_white = False

    while not is_game_over(board):
        current_player = white_player if board.turn else black_player
        move = current_player.choose_move(board)
        make_move(board, move)

    result = get_result(board)
    if result == "1/2-1/2":
        return "draw"
    if result == "1-0":
        return "win" if engine_a_is_white else "loss"
    return "loss" if engine_a_is_white else "win"


def run_match(engine_a: str, engine_b: str, games: int, model_path: str | None) -> MatchStats:
    wins = 0
    draws = 0
    losses = 0

    for game_id in range(1, games + 1):
        result = play_one_game(game_id, engine_a, engine_b, model_path)
        if result == "win":
            wins += 1
        elif result == "draw":
            draws += 1
        else:
            losses += 1

    return MatchStats(wins=wins, draws=draws, losses=losses)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run simple engine-vs-engine matches.")
    parser.add_argument("--engine-a", choices=["material", "ml"], required=True)
    parser.add_argument("--engine-b", choices=["material", "ml"], required=True)
    parser.add_argument("--games", type=int, default=50, help="Number of games to play.")
    parser.add_argument(
        "--ml-model",
        type=str,
        default=None,
        help="Optional path to the ML model file for ml evaluator.",
    )
    args = parser.parse_args()

    if args.games <= 0:
        raise ValueError("--games must be greater than 0")

    stats = run_match(args.engine_a, args.engine_b, args.games, args.ml_model)

    print(f"Engine A: {args.engine_a}")
    print(f"Engine B: {args.engine_b}")
    print(f"Games: {args.games}")
    print("Results from Engine A perspective:")
    print(f"win: {stats.wins}")
    print(f"draw: {stats.draws}")
    print(f"loss: {stats.losses}")


if __name__ == "__main__":
    main()
