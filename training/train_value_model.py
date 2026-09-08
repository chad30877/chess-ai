"""Train a minimal value model from self-play dataset."""

import argparse
import csv
import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model import RidgeClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from training.features import fen_to_features, result_to_target

CONFUSION_MATRIX_LABELS = [-1, 0, 1]


def completed_rows(rows: list[dict]) -> list[dict]:
    """Exclude unfinished games at ingestion without inventing training labels."""
    completed = [row for row in rows
                 if row.get("result") != "*" and row.get("status", "completed") == "completed"]
    skipped = len(rows) - len(completed)
    if skipped:
        print(f"Skipped {skipped} unfinished position rows (no training label).")
    if not completed:
        raise ValueError("Dataset has no completed positions available for training")
    return completed


def load_rows(dataset_path: Path) -> list[dict[str, str]]:
    suffix = dataset_path.suffix.lower()

    if suffix == ".csv":
        with dataset_path.open("r", encoding="utf-8", newline="") as f:
            return completed_rows(list(csv.DictReader(f)))

    if suffix == ".jsonl":
        rows: list[dict[str, str]] = []
        with dataset_path.open("r", encoding="utf-8") as f:
            for line in f:
                rows.append(json.loads(line))
        return completed_rows(rows)

    raise ValueError("Dataset format must be .csv or .jsonl")


def build_xy(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray]:
    x = np.stack([fen_to_features(row["fen"]) for row in rows])
    y = np.array([result_to_target(row["result"]) for row in rows], dtype=np.int32)
    return x, y


def print_label_distribution(y: np.ndarray) -> None:
    """Print target label distribution for quick dataset inspection."""
    labels, counts = np.unique(y, return_counts=True)
    total = len(y)

    print("Target label distribution:")
    print("  label  count  ratio")
    for label, count in zip(labels, counts):
        ratio = count / total
        print(f"  {int(label):>5}  {int(count):>5}  {ratio:>6.2%}")


def get_top_features(model: Pipeline, top_k: int = 20) -> list[dict[str, float | int]]:
    """Return the top-k features by absolute logistic regression weight."""
    classifier = model.named_steps["clf"]
    coefficients = classifier.coef_

    if coefficients.ndim == 1:
        feature_weights = np.abs(coefficients)
    else:
        feature_weights = np.max(np.abs(coefficients), axis=0)

    top_indices = np.argsort(feature_weights)[-top_k:][::-1]
    return [
        {"index": int(index), "weight": float(feature_weights[index])}
        for index in top_indices
    ]


def build_model(model_type: str) -> tuple[Pipeline, str | None]:
    """Build the selected classification pipeline."""
    if model_type == "logistic":
        class_weight = None # "balanced"
        classifier = LogisticRegression(
            class_weight=class_weight,
            max_iter=1000,
            random_state=42,
        )
    elif model_type == "ridge":
        class_weight = None
        classifier = RidgeClassifier()
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("clf", classifier),
        ]
    )
    return model, class_weight


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a minimal chess value model.")
    parser.add_argument("--dataset", type=str, required=True, help="Path to dataset CSV or JSONL")
    parser.add_argument(
        "--model",
        choices=["logistic", "ridge"],
        default="logistic",
        help="Model type to train.",
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=None,
        help="Use only the first N features from each feature vector.",
    )
    parser.add_argument(
        "--model-out",
        type=str,
        default="training/value_model.pkl",
        help="Output model file path",
    )
    parser.add_argument(
        "--metrics-out",
        type=str,
        default="training/value_model_metrics.json",
        help="Output metrics JSON path",
    )
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split ratio")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    rows = load_rows(dataset_path)
    if not rows:
        raise ValueError("Dataset is empty")

    x, y = build_xy(rows)
    print_label_distribution(y)

    if args.max_features is not None:
        if args.max_features <= 0:
            raise ValueError("--max-features must be greater than 0")
        if args.max_features > x.shape[1]:
            raise ValueError(f"--max-features must be <= total feature count ({x.shape[1]})")
        x = x[:, : args.max_features]

    unique_labels = np.unique(y)
    if len(unique_labels) < 2:
        raise ValueError("Need at least 2 target classes to train a classifier")

    try:
        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=args.test_size,
            random_state=42,
            stratify=y,
        )
    except ValueError:
        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=args.test_size,
            random_state=42,
            stratify=None,
        )

    baseline = DummyClassifier(strategy="most_frequent")
    baseline.fit(x_train, y_train)
    baseline_pred = baseline.predict(x_test)
    baseline_accuracy = float(accuracy_score(y_test, baseline_pred))

    model, class_weight = build_model(args.model)

    model.fit(x_train, y_train)
    y_pred = model.predict(x_test)

    accuracy = float(accuracy_score(y_test, y_pred))
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    matrix = confusion_matrix(y_test, y_pred, labels=CONFUSION_MATRIX_LABELS)
    top_features = get_top_features(model)

    model_out = Path(args.model_out)
    metrics_out = Path(args.metrics_out)
    model_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.parent.mkdir(parents=True, exist_ok=True)

    with model_out.open("wb") as f:
        pickle.dump(model, f)

    metrics = {
        "dataset": str(dataset_path),
        "num_rows": int(len(rows)),
        "num_features": int(x.shape[1]),
        "train_size": int(len(y_train)),
        "test_size": int(len(y_test)),
        "model_type": args.model,
        "class_weight": class_weight,
        "baseline_accuracy": baseline_accuracy,
        "accuracy": accuracy,
        "confusion_matrix": {
            "labels": CONFUSION_MATRIX_LABELS,
            "matrix": matrix.tolist(),
        },
        "classification_report": report,
        "top_features": top_features,
    }

    with metrics_out.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"Dataset rows: {len(rows)}")
    print(f"Feature count: {x.shape[1]}")
    print(f"Model type: {args.model}")
    print(f"Baseline accuracy: {baseline_accuracy:.4f}")
    print(f"Accuracy: {accuracy:.4f}")
    print("Confusion matrix:")
    print("rows=true labels, cols=pred labels")
    print(f"labels={CONFUSION_MATRIX_LABELS}")
    for row in matrix.tolist():
        print(" ".join(f"{value:>5}" for value in row))
    print("Top features:")
    for feature in top_features:
        print(f"feature_index={feature['index']} weight={feature['weight']:.6f}")
    print(f"Model saved to: {model_out}")
    print(f"Metrics saved to: {metrics_out}")


if __name__ == "__main__":
    main()
