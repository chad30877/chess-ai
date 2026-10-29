"""從已驗證的研究結果盤點候選，不啟動訓練或對局。"""
from itertools import combinations
from copy import deepcopy
import json
from pathlib import Path
import math

from engine.learning.group_training import GROUPS, load_group_training, load_group_candidate
from engine.learning.combination_training import load_combination, load_combination_candidate
from engine.learning.teacher import digest
from engine.evaluation.config import EvaluationConfig
from engine.learning.training import load_training


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


def _validate_inputs(snapshot, inputs):
    label = dict(inputs['label_snapshot'])
    label_identity = label.pop('identity', None)
    if (digest(inputs) != snapshot['inputs_sha256'] or not label_identity or
            digest(label) != label_identity or label_identity != snapshot['label_identity'] or
            label.get('dataset_sha256') != snapshot['dataset_identity'] or
            ('dataset_sha256' in inputs and inputs['dataset_sha256'] != snapshot['dataset_identity'])):
        raise ValueError('學習資料與標記來源身份不符')


def load_legacy_candidate(path):
    """唯讀轉接舊棋子位置成果；保留原始快照及凍結結果身份。"""
    saved = load_training(path)
    snapshot = saved['snapshot']
    if not saved['report'] or not saved['frozen'] or not saved['calibration']:
        raise ValueError('棋子位置學習尚未完成報告')
    inputs = json.loads((Path(path) / 'inputs.json').read_text(encoding='utf-8'))
    _validate_inputs(snapshot, inputs)
    frozen = saved['frozen']
    chosen = saved['candidates'][frozen['strength']]
    return dict(kind='single', groups=['piece-square'], experiment_id=snapshot['id'],
        snapshot_identity=snapshot['identity'], candidate_identity=chosen['identity'],
        frozen_identity=digest(frozen), config=deepcopy(frozen['config']), strength=frozen['strength'],
        rules=deepcopy(snapshot['rules']), dataset_identity=snapshot['dataset_identity'],
        label_identity=snapshot['label_identity'], calibration_identity=digest(saved['calibration']),
        calibration=deepcopy(saved['calibration']), original=deepcopy(snapshot['original']),
        stable=deepcopy(snapshot['stable']), test_data_identity=snapshot['test_data_identity'],
        prior_test_experiments=deepcopy(snapshot['prior_test_experiments']),
        label_path=snapshot['label_path'], report=deepcopy(saved['report']))


def load_all_candidate_inventory(root):
    """跨資料集查找已驗證候選，保留各來源及失效紀錄。"""
    root = Path(root)
    rows, errors = [], []
    def add(candidate, path, origin):
        metric = candidate['report']['validation']['learned']
        if metric['mae'] is None or not math.isfinite(metric['mae']) or not metric['games'] or not metric['positions']:
            raise ValueError('缺少有效驗證誤差')
        EvaluationConfig.from_dict(candidate['config'])
        rows.append(dict(groups=tuple(candidate['groups']), kind=candidate['kind'], origin=origin,
            mae=metric['mae'], games=metric['games'], positions=metric['positions'], stages=metric['stages'],
            config_identity=digest(EvaluationConfig.from_dict(candidate['config']).to_dict()),
            source=candidate, path=str(path)))
    for folder, origin in (('training', 'legacy'), ('group-training', 'group'), ('combinations', 'combination')):
        for entry in sorted(root.glob(f'*/teacher-labels/*/{folder}/*/snapshot.json')):
            path = entry.parent
            try:
                if origin == 'legacy':
                    add(load_legacy_candidate(path), path, origin)
                elif origin == 'group':
                    snapshot = json.loads(entry.read_text(encoding='utf-8'))
                    identity = dict(snapshot); identity.pop('identity', None)
                    if snapshot.get('identity') != digest(identity) or snapshot.get('kind') != 'independent-groups':
                        raise ValueError('群組學習快照身份不符')
                    inputs = json.loads((path / 'inputs.json').read_text(encoding='utf-8'))
                    _validate_inputs(snapshot, inputs)
                    for group in snapshot['groups']:
                        try:
                            add(load_group_candidate(path, group), path, origin)
                        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                            errors.append(dict(path=f'{path} / {group}', error=str(exc)))
                else:
                    snapshot = json.loads(entry.read_text(encoding='utf-8'))
                    identity = dict(snapshot); identity.pop('identity', None)
                    if snapshot.get('identity') != digest(identity) or snapshot.get('kind') != 'combination':
                        raise ValueError('組合快照身份不符')
                    inputs = json.loads((path / 'inputs.json').read_text(encoding='utf-8'))
                    _validate_inputs(snapshot, inputs)
                    for source in snapshot['sources']:
                        source_path = Path(source['label_path']) / 'group-training' / source['experiment_id']
                        if load_group_candidate(source_path, source['groups'][0]) != source:
                            raise ValueError('組合來源與凍結單群組不符')
                    for kind in ('direct', 'joint'):
                        try:
                            add(load_combination_candidate(path, kind), path, origin)
                        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                            errors.append(dict(path=f'{path} / {kind}', error=str(exc)))
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                errors.append(dict(path=str(path), error=str(exc)))
    rows.sort(key=lambda row: (row['source']['dataset_identity'], row['source']['label_identity'],
                               row['origin'], row['path'], row['kind'], row['groups']))
    return dict(candidates=rows, errors=errors)
