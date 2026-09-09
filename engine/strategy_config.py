"""Serialize settings from the player objects that actually play a game."""

from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.interfaces import Player


def strategy_config(name: str, player: Player | None) -> dict:
    if name == "Human":
        if player is not None:
            raise ValueError("Human strategy must not have a player object")
        return {"strategy": name}
    if name == "Random":
        if player is None:
            raise ValueError("Random strategy requires the actual player object")
        return {"strategy": name}
    if name == "Greedy":
        if player is None or not hasattr(player, "evaluator"):
            raise ValueError("Greedy strategy requires its actual evaluator")
        evaluator = player.evaluator
        if isinstance(evaluator, HandcraftedEvaluator):
            evaluator_type = "handcrafted"
        elif isinstance(evaluator, MaterialEvaluator):
            evaluator_type = "material"
        else:
            raise ValueError(f"Unsupported evaluator for saved settings: {type(evaluator).__name__}")
        return {
            "strategy": name,
            "evaluator": {"type": evaluator_type, **evaluator.config.to_dict()},
        }
    raise ValueError(f"Unsupported strategy: {name}")
