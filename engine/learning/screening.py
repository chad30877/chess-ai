"""凍結短對局選擇並重用共同開局比較的保存與續跑。"""
from engine.learning.comparison import create_comparison, load_comparison_plan
from engine.opening_book import OpeningBook
from engine.opening_lines import common_opening_lines


def create_screening(root, candidate):
    lines = common_opening_lines(OpeningBook(), count=40)[32:]
    return create_comparison(root, candidate, roles=('learned',), screening=True, opening_lines=lines)


def load_screening(path):
    return load_comparison_plan(path)


def screening_outcome(pairs, status):
    """僅計算成對的完整有效棋局；未完成時不判定淘汰。"""
    from collections import Counter
    from engine.learning.rating import rating_from_counts
    valid = [pair for pair in pairs if len(pair) == 2 and all(
        game.get('status') == 'completed' and game.get('candidate_outcome') in ('win', 'draw', 'loss')
        and game.get('termination') not in ('user_stop', 'max_plies') for game in pair)]
    counts = Counter(game['candidate_outcome'] for pair in valid for game in pair)
    wins, draws, losses = (counts[k] for k in ('win', 'draw', 'loss'))
    score = wins + draws / 2
    complete = status == 'completed' and len(valid) == 8 and len(pairs) == 8
    return dict(wins=wins, draws=draws, losses=losses, games=2 * len(valid), score=score,
                rating=rating_from_counts(wins, draws, losses),
                eliminated=(score <= 2 if complete else None), complete=complete)


def screening_report(path):
    import json
    from engine.learning.comparison import comparison_batch
    from engine.replay.comparison_catalog import load_comparison
    plan = load_screening(path)
    batch = comparison_batch(path, 'stable')
    if not batch:
        return dict(plan=plan, path=None, status='not-started', **screening_outcome([], 'not-started'))
    summary = load_comparison(batch / 'manifest.json')
    raw = json.loads((batch / 'comparison.json').read_text(encoding='utf-8'))
    lines = plan['definitions']['stable']['opening_lines']
    pairs = []
    seen = set()
    for pair in raw['pairs']:
        position = pair['position_index']
        if position in seen or not 1 <= position <= 8 or pair.get('opening_line') != lines[position - 1]:
            raise ValueError('短對局開局配對不符')
        seen.add(position)
        games = pair['games']
        if len(games) == 2 and {g['candidate_color'] for g in games} == {'white', 'black'}:
            pairs.append(games)
        else:
            pairs.append([])
    return dict(plan=plan, path=batch, status=summary.status, **screening_outcome(pairs, summary.status))
