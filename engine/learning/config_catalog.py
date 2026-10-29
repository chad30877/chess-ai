"""輕量設定目錄；清單只讀設定與摘要，執行時才驗證研究輸入。"""
import json
import math
from pathlib import Path
from collections import Counter
from engine.evaluation.config import (EvaluationConfig, PAWN_TERM_NAMES, MOBILITY_TERM_NAMES,
                                      KING_SAFETY_TERM_NAMES, COORDINATION_TERM_NAMES)
from engine.learning.teacher import digest
from engine.learning.group_training import GROUPS

LETTERS = dict(zip(GROUPS, 'PSMKC'))
TERMS = dict(zip(GROUPS, [('piece_square',), PAWN_TERM_NAMES, MOBILITY_TERM_NAMES,
                         KING_SAFETY_TERM_NAMES, COORDINATION_TERM_NAMES]))


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def sealed(value):
    content = dict(value)
    identity = content.pop('identity', None)
    if not identity or digest(content) != identity: raise ValueError('保存摘要身分不符')
    return value


def composition(config):
    terms = EvaluationConfig.from_dict(config).to_dict()['terms']
    groups = [group for group, names in TERMS.items() if any(terms.get(name, {}).get('enabled') for name in names)]
    return groups, ''.join(LETTERS[g] if g in groups else '-' for g in GROUPS)


def project_root(root):
    root = Path(root)
    return root.parent if root.name == 'data' else root.parents[1]


def load_catalog(root):
    root = Path(root)
    project = project_root(root)
    rows, errors = [], []
    stable_file = project / 'configs/evaluation/stable.json'
    if not stable_file.exists(): stable_file = Path(__file__).resolve().parents[2] / 'configs/evaluation/stable.json'
    stable = read(stable_file)
    try: names = read(project / 'data/learning-ui.json').get('names', {})
    except (OSError, ValueError): names = {}
    files = [(p, None, None) for p in sorted((project / 'configs/evaluation').glob('*.json'))]
    for snapshot_file in sorted(root.glob('*/teacher-labels/*/*/*/snapshot.json')):
        if snapshot_file.parent.parent.name not in ('training', 'group-training', 'combinations'): continue
        try:
            snapshot = sealed(read(snapshot_file))
            for file in sorted(snapshot_file.parent.rglob('frozen.json')):
                files.append((file, snapshot_file, snapshot))
        except (OSError, ValueError) as exc: errors.append(dict(path=str(snapshot_file), error=str(exc)))
    for file, snapshot_file, snapshot in files:
        try:
            saved = read(file)
            legacy = bool(snapshot_file and snapshot_file.parent.parent.name == 'training')
            if snapshot and not legacy: sealed(saved)
            config = EvaluationConfig.from_dict(saved['config'] if snapshot else saved).to_dict()
            groups, code = composition(config)
            kind = saved.get('kind', 'single') if snapshot else 'custom'
            if snapshot and snapshot.get('kind') == 'combination':
                kind = file.parent.name
            method = {'direct':'D', 'joint':'J', 'single':'J', 'custom':'U'}.get(kind, 'U')
            label_path = snapshot.get('label_path') if snapshot else None
            teacher = names.get(str(Path(label_path)), '教師 ' + Path(label_path).name[-8:]) if label_path else '自訂'
            sources = snapshot.get('sources', []) if snapshot else []
            if len({s.get('label_identity') for s in sources}) > 1: teacher = '多個教師'
            name_key = str(file.resolve())
            name = names.get(name_key, f'{teacher} {code}' if snapshot else file.stem)
            report_file = file.parent / 'report.json'
            report = {}
            if report_file.exists() and snapshot:
                try:
                    report = read(report_file)
                    if not legacy: sealed(report)
                    if report.get('frozen_identity') != (digest(saved) if legacy else saved.get('identity')): raise ValueError('報告與設定不符')
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    errors.append(dict(path=str(report_file), error=str(exc)))
                    report = {}
            metric = report.get('validation', {}).get('learned', {})
            mae = metric.get('mae')
            if mae is not None and not math.isfinite(mae): mae = None
            calibration = report.get('calibration_identity')
            if legacy and (file.parent / 'calibration.json').exists(): calibration = digest(read(file.parent / 'calibration.json'))
            context = digest([snapshot.get('dataset_identity'), snapshot.get('label_identity'), calibration]) if snapshot and mae is not None else None
            identity = digest(config)
            original = snapshot.get('original', snapshot.get('definitions', {}).get(file.parent.name, {}).get('original', config)) if snapshot else config
            source = dict(kind=kind, groups=groups, config=config, original=original, stable=stable, report=report,
                          experiment_id=snapshot.get('id', file.parent.name) if snapshot else file.stem,
                          snapshot_identity=snapshot.get('identity') if snapshot else identity,
                          candidate_identity=saved.get('candidate_identity', identity),
                          dataset_identity=snapshot.get('dataset_identity', '') if snapshot else '',
                          label_identity=snapshot.get('label_identity', '') if snapshot else '',
                          label_path=label_path, calibration_identity=report.get('calibration_identity'),
                          test_data_identity=snapshot.get('test_data_identity', '') if snapshot else '',
                          prior_test_experiments=snapshot.get('prior_test_experiments', []) if snapshot else [])
            rows.append(dict(origin='catalog', path=str(file), source=source, config_identity=identity,
                             file_identity=digest(saved), snapshot_path=str(snapshot_file) if snapshot_file else None,
                             snapshot_identity=digest(snapshot) if snapshot else None, groups=groups, kind=kind,
                             method=method, code=code, name=name, name_key=name_key, teacher=teacher,
                             mae=mae, metric_context=context, metric_date=report_file.stat().st_mtime_ns if report else 0,
                             comparison_status='未評估', ratings={}, report_path=str(report_file) if report else None))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(path=str(file), error=str(exc)))
    counts = Counter()
    for row in rows:
        counts[row['name']] += 1
        if counts[row['name']] > 1 and row['name_key'] not in names: row['name'] += f' ({counts[row["name"]]})'
    return dict(candidates=rows, errors=errors, all_sources=True)


def validate_catalog_row(row):
    file = Path(row['path'])
    saved = read(file)
    if digest(saved) != row['file_identity']: raise ValueError('設定已變更，請重新整理候選')
    config = EvaluationConfig.from_dict(saved['config'] if row.get('snapshot_path') else saved).to_dict()
    if config != row['source']['config']: raise ValueError('所選設定身分不符')
    if row.get('snapshot_path'):
        snapshot_file = Path(row['snapshot_path'])
        snapshot = read(snapshot_file)
        content = dict(snapshot); identity = content.pop('identity', None)
        if digest(snapshot) != row['snapshot_identity'] or digest(content) != identity:
            raise ValueError('研究快照已變更')
        if digest(read(snapshot_file.parent / 'inputs.json')) != snapshot['inputs_sha256']:
            raise ValueError('研究輸入已變更')
        if row.get('report_path'):
            from engine.learning.candidate_inventory import validate_candidate_row, load_legacy_candidate
            from engine.learning.group_training import load_group_candidate
            from engine.learning.combination_training import load_combination_candidate
            path = snapshot_file.parent
            if path.parent.name == 'group-training':
                source, origin = load_group_candidate(path, file.parent.name), 'group'
            elif path.parent.name == 'combinations':
                source, origin = load_combination_candidate(path, file.parent.name), 'combination'
            else: source, origin = load_legacy_candidate(path), 'legacy'
            if EvaluationConfig.from_dict(source['config']).to_dict() != config: raise ValueError('凍結設定身分不符')
            return validate_candidate_row(dict(path=str(path), origin=origin, source=source))
    EvaluationConfig.from_dict(row['source']['config'])
    return row['source']


def load_ratings(project):
    """按共同條件保留每份設定最新有效對戰；不讀取教師輸入。"""
    from engine.learning.rating import rating_from_counts, valid_comparison_game
    from engine.replay.comparison_catalog import load_comparison
    project = Path(project)
    results, contexts = {}, {}
    for file in sorted((project / 'data/batches').glob('*/manifest.json'), key=lambda p: p.stat().st_mtime_ns):
        try:
            manifest = read(file)
            definition = manifest['settings']['experiment']
            lines = definition['opening_lines']
            if definition['repetitions'] != 1: continue
            stable_file = project / 'configs/evaluation/stable.json'
            stable = EvaluationConfig.from_dict(read(stable_file)).to_dict()
            if EvaluationConfig.from_dict(definition['baseline']['config']).to_dict() != stable: continue
            summary = load_comparison(file)
            raw = read(file.parent / 'comparison.json')
            context = digest([stable, definition['search'], definition['claim_draw'], definition['max_plies'], lines])
            depth = definition['search'].get('depth_plies', '?')
            contexts[context] = f'深度 {depth} · {len(lines)} 開局 · {context[:6]}'
            for index, candidate in enumerate(definition['candidates']):
                pairs, seen = [], set()
                for pair in raw.get('pairs', []):
                    if pair.get('candidate_index', 0) != index: continue
                    position = pair['position_index']
                    if position in seen or not 1 <= position <= len(lines): raise ValueError('重複或無效配對')
                    seen.add(position)
                    if pair.get('opening_line') != lines[position - 1]: raise ValueError('開局不符')
                    games = pair['games']
                    if len(games) == 2 and {g['candidate_color'] for g in games} == {'white','black'} and all(valid_comparison_game(g) for g in games):
                        pairs.append(games)
                counts = Counter(g['candidate_outcome'] for pair in pairs for g in pair)
                score = rating_from_counts(counts['win'], counts['draw'], counts['loss'])
                if score is None: continue
                formal = len(lines) == len(pairs) == 32 and len({digest(line) for line in lines}) == 32 and definition['max_plies'] is None and summary.status == 'completed'
                identity = digest(EvaluationConfig.from_dict(candidate['config']).to_dict())
                results.setdefault(identity, {})[context] = dict(value=score, status='正式' if formal else '暫估', path=str(file.parent))
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError): continue
    return results, contexts
