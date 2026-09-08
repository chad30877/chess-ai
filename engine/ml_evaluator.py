"""ML-based board evaluator backed by a trained value model."""

import pickle
from pathlib import Path

import chess

from engine.interfaces import Evaluator
from training.features import fen_to_features


class MLValueEvaluator(Evaluator):
    """Evaluate non-terminal positions with a White-perspective value model."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_model_path = project_root / "training" / "value_model.pkl"
        self.model_path = Path(model_path) if model_path is not None else default_model_path

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        with self.model_path.open("rb") as model_file:
            self.model = pickle.load(model_file)

        if not hasattr(self.model, "predict_proba"):
            raise TypeError(
                "Loaded model does not support predict_proba(). Use a probabilistic model."
            )

    def evaluate(self, board: chess.Board) -> float:
        """Return White-perspective score = white_win_prob - black_win_prob."""
        fen = board.fen()
        features = fen_to_features(fen)
        classifier = self.model.named_steps["clf"]
        expected_features = getattr(classifier, "n_features_in_", len(features))

        if expected_features > len(features):
            raise ValueError(
                f"Model expects {expected_features} features, but fen_to_features returned {len(features)}."
            )

        x = features[:expected_features].reshape(1, -1)
        probabilities = self.model.predict_proba(x)[0]
        class_probabilities = dict(zip(self.model.classes_, probabilities))

        white_win_prob = float(class_probabilities.get(1, 0.0))
        black_win_prob = float(class_probabilities.get(-1, 0.0))
        return white_win_prob - black_win_prob


MLEvaluator = MLValueEvaluator
