"""Serialize settings from the player objects that actually play a game."""

from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.interfaces import Player
from engine.players import AlphaBetaPlayer
from engine.search import AlphaBetaSearcher


def strategy_config(name: str, player: Player | None) -> dict:
    if name == "Human":
        if player is not None:
            raise ValueError("Human strategy must not have a player object")
        return {"strategy": name}
    if name == "Random":
        if player is None:
            raise ValueError("Random strategy requires the actual player object")
        return {"strategy": name}
    if name == "AlphaBeta":
        if not isinstance(player, AlphaBetaPlayer) or not isinstance(player.searcher, AlphaBetaSearcher):
            raise ValueError("AlphaBeta saved settings require the actual AlphaBetaSearcher")
        searcher = player.searcher
        limits = searcher.default_limits
        if limits.time_ms is not None or limits.stop_requested is not None:
            raise ValueError("AlphaBeta saved settings currently support fixed depth without cancellation only")
        evaluator = searcher.evaluator
        if isinstance(evaluator, HandcraftedEvaluator):
            evaluator_type = "handcrafted"
        elif isinstance(evaluator, MaterialEvaluator):
            evaluator_type = "material"
        else:
            raise ValueError(f"Unsupported evaluator for saved settings: {type(evaluator).__name__}")
        return {
            "strategy": name,
            "evaluator": {"type": evaluator_type, **evaluator.config.to_dict()},
            "search": {
                "schema_version": 1,
                "algorithm": "alpha_beta",
                "max_depth": limits.max_depth,
                "claim_draw": searcher.claim_draw,
                "move_ordering": searcher.move_ordering,
                "quiescence_depth": searcher.quiescence_depth,
                "use_transposition_table": searcher.use_transposition_table,
                "use_pvs": searcher.use_pvs,
                "aspiration_window": searcher.aspiration_window,
            },
        }
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
