"""Compare two evaluation settings in paired, color-swapped games."""

import argparse
import json
from pathlib import Path

import chess

from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import (
    ComparisonParticipant,
    ComparisonSearchConfig,
    run_evaluation_comparison,
)


def load_evaluation_config(path: Path) -> EvaluationConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read evaluation config {path}: {exc}") from exc
    return EvaluationConfig.from_dict(payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare evaluation settings using fixed-depth Greedy or AlphaBeta players.",
    )
    parser.add_argument("--candidate-config", type=Path, required=True)
    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--baseline-config", type=Path)
    baseline.add_argument("--baseline-random", action="store_true")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--baseline-label")
    parser.add_argument("--strategy", choices=("greedy", "alphabeta"), default="greedy")
    parser.add_argument("--depth", type=int, help="Regular depth in plies; Greedy=1, AlphaBeta default=2")
    parser.add_argument("--quiescence-depth", type=int)
    parser.add_argument("--move-ordering", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--transposition-table", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--pvs", action=argparse.BooleanOptionalAction, default=None)
    aspiration = parser.add_mutually_exclusive_group()
    aspiration.add_argument("--aspiration-window", type=float)
    aspiration.add_argument("--no-aspiration", action="store_true")
    parser.add_argument(
        "--initial-fen", action="append",
        help="Initial FEN; repeat for multiple positions. Defaults to the standard start.",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=10_000)
    parser.add_argument("--max-plies", type=int)
    parser.add_argument("--claim-draw", action="store_true")
    parser.add_argument("--batch-root", type=Path, default=Path("data/batches"))
    parser.add_argument("--name")
    parser.add_argument("--tag", action="append", default=[])
    args = parser.parse_args()

    search = None
    if args.strategy == "greedy":
        if args.depth not in (None, 1) or any(value is not None for value in (
            args.quiescence_depth, args.move_ordering, args.transposition_table,
            args.pvs, args.aspiration_window,
        )) or args.no_aspiration:
            parser.error("Greedy supports depth 1 only; search options require --strategy alphabeta")
    else:
        try:
            search = ComparisonSearchConfig(
                depth_plies=args.depth if args.depth is not None else 2,
                quiescence_depth=args.quiescence_depth if args.quiescence_depth is not None else 4,
                move_ordering=args.move_ordering if args.move_ordering is not None else True,
                use_transposition_table=args.transposition_table if args.transposition_table is not None else True,
                use_pvs=args.pvs if args.pvs is not None else True,
                aspiration_window=None if args.no_aspiration else (
                    args.aspiration_window if args.aspiration_window is not None else 1.0
                ),
            )
        except ValueError as exc:
            parser.error(str(exc))

    def participant(label, path):
        config = load_evaluation_config(path)
        if search is not None:
            return ComparisonParticipant.alphabeta(label, config, search=search)
        return ComparisonParticipant.greedy(label, config)

    candidate = participant(args.candidate_label, args.candidate_config)
    baseline_label = args.baseline_label or ("Random" if args.baseline_random else "stable")
    if args.baseline_random:
        baseline_participant = ComparisonParticipant.random_baseline(baseline_label)
    else:
        baseline_participant = participant(baseline_label, args.baseline_config)
    result = run_evaluation_comparison(
        baseline=baseline_participant,
        candidate=candidate,
        initial_fens=args.initial_fen or [chess.STARTING_FEN],
        repetitions=args.repetitions,
        base_seed=args.seed,
        batch_root=args.batch_root,
        name=args.name,
        tags=args.tag,
        claim_draw=args.claim_draw,
        max_plies=args.max_plies,
    )
    stats = result.candidate_stats
    print(f"Comparison batch: {result.path}")
    depth = search.depth_plies if search is not None else 1
    print(f"Budget: fixed_depth, {depth} {'ply' if depth == 1 else 'plies'}")
    print(f"Strategy: {args.strategy}")
    print(f"Baseline: {baseline_label}")
    print(f"Candidate: {args.candidate_label}")
    print(
        f"wins={stats.wins} draws={stats.draws} losses={stats.losses} "
        f"unfinished={stats.unfinished}",
    )
    print("Small samples validate the flow; they do not prove playing strength.")


if __name__ == "__main__":
    main()
