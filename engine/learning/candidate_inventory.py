"""從已驗證的研究結果盤點候選，不啟動訓練或對局。"""
from itertools import combinations
from pathlib import Path
import math

from engine.learning.group_training import GROUPS, load_group_training, load_group_candidate
from engine.learning.combination_training import load_combination, load_combination_candidate
from engine.learning.teacher import digest
from engine.evaluation.config import EvaluationConfig


def load_candidate_inventory(source_path):
    """重讀同源研究，回傳覆蓋、缺漏、來源與依驗證誤差排序的候選。"""
    source_path = Path(source_path)
    source = load_group_training(source_path)
    entries = {groups: ({'single': 'missing'} if len(groups) == 1 else
                         {'direct': 'missing', 'joint': 'missing'})
               for size in range(1, len(GROUPS) + 1) for groups in combinations(GROUPS, size)}
    candidates, errors, seen = [], [], set()

    def add(candidate, path):
        metric = candidate['report']['validation']['learned']
        mae = metric['mae']
        if mae is None or not math.isfinite(mae) or not metric['games'] or not metric['positions']:
            return False
        config_identity = digest(EvaluationConfig.from_dict(candidate['config']).to_dict())
        candidates.append(dict(groups=tuple(candidate['groups']), kind=candidate['kind'], mae=mae,
            games=metric['games'], positions=metric['positions'], stages=metric['stages'],
            config_identity=config_identity, source=candidate, path=str(path)))
        return True

    for group in GROUPS:
        result = source['groups'].get(group)
        if not result: continue
        entries[(group,)]['single'] = result['status']
        if result['report']:
            candidate = load_group_candidate(source_path, group)
            if not add(candidate, source_path): entries[(group,)]['single'] = 'invalid'

    for snapshot in sorted((source_path.parents[1] / 'combinations').glob('*/snapshot.json')):
        try:
            saved = load_combination(snapshot.parent)
            sources = saved['snapshot']['sources']
            if not sources or any(s['snapshot_identity'] != source['snapshot']['identity'] for s in sources):
                continue
            groups = tuple(saved['snapshot']['groups'])
            if groups not in entries or len(groups) < 2: continue
            for item in sources:
                current = load_group_candidate(source_path, item['groups'][0])
                if item != current: raise ValueError('單群組凍結來源不符')
            for kind in ('direct', 'joint'):
                result = saved['results'][kind]
                if result['report']:
                    candidate = load_combination_candidate(snapshot.parent, kind)
                    if add(candidate, snapshot.parent): entries[groups][kind] = 'completed'
                    elif entries[groups][kind] != 'completed': entries[groups][kind] = 'invalid'
                elif entries[groups][kind] != 'completed':
                    entries[groups][kind] = 'failed' if saved['status'] == 'failed' else 'incomplete'
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append(dict(path=str(snapshot.parent), error=str(exc)))

    candidates.sort(key=lambda c: (c['mae'], c['config_identity'], c['path'], c['kind']))
    unique = []
    for candidate in candidates:
        if candidate['config_identity'] not in seen:
            seen.add(candidate['config_identity']); unique.append(candidate)
    complete = all(status == 'completed' for entry in entries.values() for status in entry.values()) and not errors
    return dict(entries=entries, candidates=unique[:10], complete=complete, errors=errors,
        source_identity=source['snapshot']['identity'], dataset_identity=source['snapshot']['dataset_identity'],
        label_identity=source['snapshot']['label_identity'], calibration=source['calibration'],
        test_data_identity=source['snapshot']['test_data_identity'], exposure=source['snapshot']['data_use'])
