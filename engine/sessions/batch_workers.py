"""可由 Windows spawn 載入的對局工作；不引用 UI 或協調端鎖。"""

import random
from contextlib import ExitStack
from time import perf_counter

from engine.evaluation.config import EvaluationConfig
from engine.players import AlphaBetaPlayer, GreedyPlayer, RandomPlayer
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.search import SearchLimits
from engine.search.transposition import DEFAULT_TRANSPOSITION_CAPACITY
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, _ControlledPlayer
from engine.sessions.self_play import play_game

_STOP = _RESUME = _RESULTS = None


def initialize_worker(stop, resume, results):
    global _STOP, _RESUME, _RESULTS
    _STOP, _RESUME, _RESULTS = stop, resume, results


def worker_control():
    while not _STOP.is_set():
        if _RESUME.wait(timeout=0.05):
            return not _STOP.is_set()
    return False


def general_player(name, rng, evaluation, claim_draw, search_depth=2, search_workers=1,
                   transposition_capacity=DEFAULT_TRANSPOSITION_CAPACITY):
    if name == "Random":
        return RandomPlayer(rng=rng)
    if name == "Greedy":
        return GreedyPlayer(config=evaluation, rng=rng, claim_draw=claim_draw)
    if name == "AlphaBeta":
        return AlphaBetaPlayer.from_evaluator(HandcraftedEvaluator(config=evaluation or EvaluationConfig()),
            limits=SearchLimits(max_depth=search_depth, transposition_capacity=transposition_capacity),
            search_workers=search_workers, claim_draw=claim_draw)
    raise ValueError(f"Unsupported batch player: {name}")


def own_player(stack, player):
    """建立後立即登記，第二位玩家建立失敗也能釋放第一位。"""
    close = getattr(player, "close", None)
    if close is not None:
        stack.callback(close)
    return player


def search_control():
    # 暫停只在落子邊界等待；搜尋途中僅觀察停止。
    return not _STOP.is_set()


def participant_payload(participant):
    """評分設定內含唯讀 mapping，跨程序只傳一般字典。"""
    from dataclasses import asdict

    return dict(label=participant.label, strategy=participant.strategy,
                evaluation=participant.evaluation_config.to_dict() if participant.evaluation_config else None,
                search=asdict(participant.search_config) if participant.search_config else None)


def restore_participant(payload):
    return ComparisonParticipant(payload["label"], payload["strategy"],
                                 EvaluationConfig.from_dict(payload["evaluation"]) if payload["evaluation"] else None,
                                 ComparisonSearchConfig(**payload["search"]) if payload["search"] else None)


def run_work(work):
    """一局完成立即回報；配對第二局不等待協調端保存第一局。"""
    number = work["number"]
    error = ""
    try:
        if not worker_control():
            return
        _RESULTS.put(("started", number, None))
        if work["kind"] == "general":
            s = work["settings"]
            rng = random.Random(work["seed"])
            with ExitStack() as stack:
                players = []
                for side in ("white", "black"):
                    player = own_player(stack, general_player(s[side], rng,
                        EvaluationConfig.from_dict(s[side + "_evaluation"]) if s[side + "_evaluation"] else None,
                        s["claim_draw"], s.get("search_depth", 2), s.get("search_workers", 1),
                        s.get("transposition_capacity", DEFAULT_TRANSPOSITION_CAPACITY)))
                    players.append(_ControlledPlayer(player, search_control))
                _RESULTS.put(("game_started", number, number))
                started = perf_counter()
                game = play_game(number, *players, s["white"], s["black"], initial_fen=work["initial_fen"],
                                 claim_draw=s["claim_draw"], max_plies=s["max_plies"], control=worker_control)
            _RESULTS.put(("game", number, (game, work["seed"], perf_counter() - started)))
        else:
            baseline, candidate = [restore_participant(work[side]) for side in ("baseline", "candidate")]
            for offset, (white, black) in enumerate(((baseline, candidate), (candidate, baseline))):
                if offset in work.get("skip_offsets", ()):
                    continue
                if not worker_control():
                    break
                game_number = (number - 1) * 2 + offset + 1
                _RESULTS.put(("game_started", number, game_number))
                rng = random.Random(work["seed"])
                with ExitStack() as stack:
                    players = []
                    for side in (white, black):
                        player = own_player(stack, side.create_player(rng, claim_draw=work["claim_draw"]))
                        key = "baseline" if side is baseline else "candidate"
                        if side.settings_snapshot(player=player) != work["participant_settings"][key]:
                            raise ValueError("Actual player settings changed during comparison")
                        players.append(_ControlledPlayer(player, search_control))
                    started = perf_counter()
                    game = play_game(game_number, *players, white.label, black.label,
                                     initial_fen=work["initial_fen"], claim_draw=work["claim_draw"],
                                     max_plies=work["max_plies"], control=worker_control)
                _RESULTS.put(("game", number, (game, work["seed"], perf_counter() - started)))
                if game.termination == "user_stop":
                    break
    except Exception as exc:
        error = f"工作 {number}：{type(exc).__name__}: {exc}"
        _STOP.set()
        _RESUME.set()
    finally:
        _RESULTS.put(("finished", number, error))
