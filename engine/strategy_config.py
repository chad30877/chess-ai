"""Actual settings for the strategies currently exposed by the UI and generator."""

import chess

from engine.players import GreedyPlayer


def strategy_config(name: str) -> dict:
    if name in ("Human", "Random"):
        return {"strategy": name}
    if name == "Greedy":
        evaluator = GreedyPlayer().evaluator
        return {"strategy": name, "evaluator": {
            "type": "handcrafted",
            "weights": {chess.piece_symbol(k).upper(): v
                        for k, v in evaluator.material_evaluator.weights.items()},
        }}
    raise ValueError(f"Unsupported strategy: {name}")
