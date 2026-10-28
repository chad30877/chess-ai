"""凍結用途後，對新教師標記資料評估已凍結候選。"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json

from engine.evaluation.config import EvaluationConfig
from engine.learning.final_comparison import load_final_comparison
from engine.learning.labeling import load_labeled_dataset
from engine.learning.teacher import digest
from engine.learning.training import evaluate_errors
from engine.storage.batch_storage import write_json_atomic

PURPOSE = '凍結候選最終教師誤差評估，不供選擇或調整候選'


def _sealed(value):
    value['identity'] = digest(value)
    return value


def _read(path):
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    content = dict(result); identity = content.pop('identity', None)
    if identity != digest(content):
        raise ValueError('評估紀錄身份不符')
    return result


def freeze_heldout(root, final_path):
    final = load_final_comparison(final_path)
    path = Path(root) / 'data/learning-heldout' / uuid4().hex
    path.mkdir(parents=True)
    write_json_atomic(path / 'snapshot.json', _sealed(dict(format_version=1, purpose=PURPOSE,
        root=str(Path(root).resolve()), final_path=str(Path(final_path).resolve()), final_identity=final['identity'], candidates=deepcopy(final['candidates']))))
    return path


def load_heldout(path):
    path = Path(path)
    snapshot = _read(path/'snapshot.json')
    if snapshot.get('format_version') != 1 or snapshot.get('purpose') != PURPOSE:
        raise ValueError('評估用途或版本不符')
    report = _read(path/'report.json') if (path/'report.json').exists() else None
    if report and report['snapshot_identity'] != snapshot['identity']:
        raise ValueError('評估結果與凍結身份不符')
    return dict(snapshot=snapshot, report=report)


def evaluate_heldout(path, label_path):
    path = Path(path)
    state = load_heldout(path)
    if state['report']:
        raise ValueError('評估結果已保存；不可替換資料或重選候選')
    snapshot = state['snapshot']
    final = load_final_comparison(snapshot['final_path'])
    if final['identity'] != snapshot['final_identity'] or final['candidates'] != snapshot['candidates']:
        raise ValueError('完整比較凍結候選已變更')
    labeled = load_labeled_dataset(label_path)
    rows = [r for r in labeled['positions'] if r['split'] == 'test']
    test_games = {r['game_id'] for r in rows}; test_positions = {r['position_id'] for r in rows}
    limitations = []
    if len(test_games) < 30:
        limitations.append('測試有效盤數不足 30，證據不足')
    if not rows:
        limitations.append('測試組沒有有效局面')
    results = []
    # 研究快照使用過的所有資料均為曝光來源，包括與本候選無關的其他實驗。
    research_root = Path(snapshot['root']) / 'data/learning'
    for file in research_root.rglob('inputs.json'):
        try:
            inputs = json.loads(file.read_text(encoding='utf-8'))
            prior = inputs['positions']
            if (test_games & {r['game_id'] for r in prior} or
                    test_positions & {r['position_id'] for r in prior}):
                limitations.append('測試資料與其他研究來源重疊，已曝光')
        except (OSError, ValueError, TypeError, KeyError):
            limitations.append('其他研究來源無法核對，無法確認未曝光')
    for file in (Path(snapshot['root']) / 'data/learning-heldout').glob('*/report.json'):
        if file.parent == path:
            continue
        try:
            previous = _read(file)
            if (previous['dataset_identity'] == labeled['snapshot']['dataset_sha256'] or
                    test_games & set(previous['test_game_ids']) or test_positions & set(previous['test_position_ids'])):
                limitations.append('測試資料曾供最終評估使用，已曝光')
        except (OSError, ValueError, TypeError, KeyError):
            limitations.append('既有最終評估來源無法核對，無法確認未曝光')
    teacher_keys = ('executable_sha256', 'extra_sha256', 'identification', 'options', 'processing_version', 'reset_policy', 'score_policy')
    current = labeled['snapshot']
    for entry in snapshot['candidates']:
        source = entry['source']
        try:
            original = load_labeled_dataset(source['label_path'])
            old = original['snapshot']
            if old['identity'] != source['label_identity'] or old['dataset_sha256'] != source['dataset_identity']:
                raise ValueError('來源身份不符')
            if any(old['teacher'].get(k) != current['teacher'].get(k) for k in teacher_keys) or any(old.get(k) != current.get(k) for k in ('nodes','filter_version','cp_special_threshold')):
                limitations.append('教師條件與候選來源不相容')
            old_positions = original['dataset']['positions']
            if (old['dataset_sha256'] == current['dataset_sha256'] or
                    test_games & {r['game_id'] for r in old_positions} or
                    test_positions & {r['position_id'] for r in old_positions}):
                limitations.append('測試資料與候選來源重疊，已曝光')
        except (OSError, KeyError, TypeError, ValueError):
            limitations.append('候選資料或教師來源無法核對，無法確認未曝光')
        calibration = source.get('calibration', {})
        if not calibration.get('healthy') or not isinstance(calibration.get('scale'), (int,float)):
            limitations.append('共同校準不健康或缺漏')
            metric = None
        else:
            metric = evaluate_errors(rows, EvaluationConfig.from_dict(source['config']), calibration['scale'])
        results.append(dict(candidate_identity=source.get('candidate_identity'), config_identity=digest(source['config']),
                            calibration_identity=source.get('calibration_identity'), metric=metric))
    limitations = list(dict.fromkeys(limitations))
    report = _sealed(dict(format_version=1, snapshot_identity=snapshot['identity'], purpose=PURPOSE,
        label_path=str(Path(label_path).resolve()), dataset_identity=current['dataset_sha256'],
        label_identity=current['identity'], teacher=current['teacher'], nodes=current['nodes'],
        data_source=labeled['dataset']['source'], scope='只核對可讀取的本機研究紀錄，無法證明其他環境未曝光。', test_game_ids=sorted(test_games), test_position_ids=sorted(test_positions), independent=not limitations, limitations=limitations,
        results=results))
    write_json_atomic(path/'report.json', report)
    return report
