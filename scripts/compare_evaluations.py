"""Compare two evaluation settings in paired, color-swapped games."""

import argparse
import json
from pathlib import Path

import chess

from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import (
    ComparisonParticipant,
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
        description="Compare evaluation settings with fixed-depth one-ply Greedy players.",
    )
    parser.add_argument("--candidate-config", type=Path, required=True)
    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--baseline-config", type=Path)
    baseline.add_argument("--baseline-random", action="store_true")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--baseline-label")
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

    candidate = ComparisonParticipant.greedy(
        args.candidate_label, load_evaluation_config(args.candidate_config),
    )
    baseline_label = args.baseline_label or ("Random" if args.baseline_random else "stable")
    if args.baseline_random:
        baseline_participant = ComparisonParticipant.random_baseline(baseline_label)
    else:
        baseline_participant = ComparisonParticipant.greedy(
            baseline_label, load_evaluation_config(args.baseline_config),
        )
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
    print("Budget: fixed_depth, 1 ply")
    print(f"Baseline: {baseline_label}")
    print(f"Candidate: {args.candidate_label}")
    print(
        f"wins={stats.wins} draws={stats.draws} losses={stats.losses} "
        f"unfinished={stats.unfinished}",
    )
    print("Small samples validate the flow; they do not prove playing strength.")


if __name__ == "__main__":
    main()
