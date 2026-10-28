"""依已驗證共同開局紀錄計算設定棋力分數。"""
from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import random

from engine.evaluation.config import EvaluationConfig
from engine.learning.teacher import digest
from engine.replay.comparison_catalog import load_comparison

ROOT = Path(__file__).resolve().parents[2]
LIMITATION = '相對 stable 1500 的估計；固定開局配對重抽樣不保證普遍棋力。'


def rating_from_counts(wins, draws, losses):
    n = wins + draws + losses
    if not n:
        return None
    p = (wins + draws / 2 + .5) / (n + 1)
    return 1500 + 400 * math.log10(p / (1 - p))


def _config(value):
    return EvaluationConfig.from_dict(value).to_dict()


@lru_cache(maxsize=128)
def _interval(pairs):
    if len(pairs) < 2 or len(set(pairs)) < 2:
        return None
    rng = random.Random(0)
    estimates = []
    for _ in range(2000):
        counts = Counter(outcome for _ in pairs for outcome in rng.choice(pairs))
        estimates.append(rating_from_counts(counts['win'], counts['draw'], counts['loss']))
    estimates.sort()
    return [estimates[49], estimates[1949]]


def profile_rating(root, config, *, search=None, claim_draw=False, max_plies=None):
    """搜尋已凍結的 stable 比較；損壞、不相容及重複棋局不列入。"""
    from engine.learning.comparison import load_comparison_plan, comparison_batch
    from engine.sessions.evaluation_comparison import ComparisonSearchConfig
    from dataclasses import asdict
    wanted = _config(config)
    stable = _config(json.loads((ROOT / 'configs/evaluation/stable.json').read_text(encoding='utf-8')))
    search = search or asdict(ComparisonSearchConfig(depth_plies=3, quiescence_depth=4,
                                                       search_workers=1, transposition_capacity=4096))
    result = dict(status='unrated', rating=None, wins=0, draws=0, losses=0, games=0,
                  sources=[], interval=None, conditions=dict(search=search, claim_draw=claim_draw,
                  max_plies=max_plies), limitation=LIMITATION, provisional=None)
    unique = {}
    provisional = {}
    for file in sorted((Path(root) / 'data/learning-comparisons').glob('*/snapshot.json')):
        try:
            plan = load_comparison_plan(file.parent)
            definition = plan['definitions']['stable']
            if (_config(definition['baseline']['config']) != stable or definition['search'] != search
                or definition['claim_draw'] != claim_draw or definition['max_plies'] != max_plies
                or definition['repetitions'] != 1):
                continue
            batch = comparison_batch(file.parent, 'stable')
            if not batch:
                continue
            summary = load_comparison(batch / 'manifest.json')
            manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
            raw = json.loads((batch / 'comparison.json').read_text(encoding='utf-8'))
            actual = manifest['settings']['comparison']
            if actual.get('opening_lines') != definition['opening_lines'] or actual.get('repetitions') != 1:
                continue
            lines = definition['opening_lines']
            line_keys = [(line['initial_fen'], tuple(line['moves_uci'])) for line in lines]
            full = len(lines) == 32 and len(set(line_keys)) == 32 and max_plies is None
            participants = summary.participants
            actual_candidates = participants.get('candidates', [participants.get('candidate')])
            for index, item in enumerate(definition['candidates']):
                if _config(item['config']) != wanted:
                    continue
                # 保存的實際執行設定須與凍結的參與者一致。
                from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig
                search_config = ComparisonSearchConfig(**search)
                expected_baseline = ComparisonParticipant.alphabeta(definition['baseline']['label'], EvaluationConfig.from_dict(stable), search=search_config).settings_snapshot(claim_draw=claim_draw)
                expected_candidate = ComparisonParticipant.alphabeta(item['label'], EvaluationConfig.from_dict(wanted), search=search_config).settings_snapshot(claim_draw=claim_draw)
                if participants['baseline'] != expected_baseline or actual_candidates[index] != expected_candidate:
                    continue
                pairs = {}
                for pair in raw['pairs']:
                    if pair.get('candidate_index', 0) != index:
                        continue
                    position = pair['position_index']
                    if not 1 <= position <= len(lines) or pair['pair_number'] != position or position in pairs:
                        raise ValueError('無效開局配對')
                    if pair.get('opening_line') != lines[position - 1] or pair.get('initial_fen') != lines[position - 1]['initial_fen']:
                        raise ValueError('開局來源不符')
                    games = pair['games']
                    if (len(games) == 2 and {g['candidate_color'] for g in games} == {'white', 'black'}
                        and all(g['status'] == 'completed' and g['candidate_outcome'] in ('win','draw','loss')
                                and g['termination'] not in ('user_stop', 'max_plies') for g in games)):
                        pairs[position] = tuple(g['candidate_outcome'] for g in games)
                target = unique if full and summary.status == 'completed' and len(pairs) == 32 else provisional
                for position, outcomes in pairs.items():
                    key = digest([line_keys[position - 1], definition['base_seed'] + position - 1])
                    target.setdefault(key, (outcomes, str(batch)))
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
    def summarize(records):
        pairs = [v[0] for v in records.values()]
        counts = Counter(outcome for pair in pairs for outcome in pair)
        wins, draws, losses = (counts[k] for k in ('win', 'draw', 'loss'))
        return dict(rating=rating_from_counts(wins, draws, losses), wins=wins, draws=draws,
                    losses=losses, games=wins+draws+losses, sources=sorted({v[1] for v in records.values()}),
                    interval=_interval(tuple(pairs)))
    if unique:
        result.update(summarize(unique), status='formal')
    if provisional:
        result['provisional'] = summarize(provisional)
        if not unique: result['status'] = 'provisional'
    return result
