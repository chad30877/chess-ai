"""共用校準與整次期限的多個獨立群組學習。"""
from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from uuid import uuid4

from engine.evaluation.config import EvaluationConfig
from engine.learning.labeling import load_labeled_dataset
from engine.learning.teacher import digest
from engine.learning.training import training_rules, calibrate, fit_position_weights, evaluate_errors, select_candidate, TrainingStopped
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
GROUPS = {'piece-square': '棋子位置', 'pawn': '兵形', 'mobility': '活動力', 'king-safety': '王安全', 'coordination': '協調'}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _seal(value):
    value['identity'] = digest(value)
    return value


def _verified(path):
    value = _read(path)
    content = dict(value); content.pop('identity', None)
    if value.get('identity') != digest(content): raise ValueError('學習提交內容身份不符')
    return value


def create_group_training(label_path, groups=None, *, run_path=None):
    """群組各自擬合，共享唯一資料副本、校準參照及規則。"""
    groups = list(GROUPS) if groups is None else list(groups)
    if not groups or len(set(groups)) != len(groups) or any(g not in GROUPS for g in groups):
        raise ValueError('請選擇不重複的既有評分項群組')
    labeled = load_labeled_dataset(label_path)
    rules = training_rules()
    definitions = {}
    for group in groups:
        original = _read(ROOT / f'configs/evaluation/learning-{group}.json')
        terms = [name for name, term in original['terms'].items() if name != 'material' and term['enabled']]
        weights = [original['terms'][term][key] for term in terms for key in ('weight', 'endgame_weight')]
        definitions[group] = dict(original=original, terms=terms, original_weights=weights,
            scales=[abs(w) or rules['zero_scale'] for w in weights],
            column_order=[f'{term}:{stage}' for term in terms for stage in ('middlegame', 'endgame')])
    path = Path(run_path) if run_path else Path(label_path) / 'group-training' / uuid4().hex
    if path.exists(): raise ValueError('學習條件不可變；請建立新實驗')
    prior = []
    for folder in ('training', 'group-training'):
        for entry in (Path(label_path) / folder).glob('*/snapshot.json'):
            earlier = _read(entry)
            if (earlier.get('dataset_identity') == labeled['snapshot']['dataset_sha256'] and
                    ((entry.parent / 'report.json').exists() or list(entry.parent.glob('groups/*/report.json')))):
                prior.append(dict(experiment_id=earlier['id'], snapshot_identity=earlier['identity'], label_identity=earlier['label_identity']))
    inputs = dict(label_snapshot=labeled['snapshot'], positions=labeled['positions'])
    snapshot = _seal(dict(format_version=1, id=path.name, kind='independent-groups', groups=groups,
        definitions=definitions, rules=rules, stable=_read(ROOT / 'configs/evaluation/stable.json'),
        inputs_sha256=digest(inputs), dataset_identity=labeled['snapshot']['dataset_sha256'],
        label_identity=labeled['snapshot']['identity'], label_path=str(Path(label_path).resolve()),
        test_data_identity=digest([labeled['snapshot']['dataset_sha256'], sorted(r['position_id'] for r in labeled['positions'] if r['split'] == 'test')]),
        prior_test_experiments=prior, data_use='各組以驗證選定後凍結測試；相同測試資料可能已於其他實驗曝光。'))
    path.mkdir(parents=True)
    write_json_atomic(path / 'inputs.json', inputs)
    write_json_atomic(path / 'snapshot.json', snapshot)
    for group in groups: (path / 'groups' / group / 'candidates').mkdir(parents=True)
    write_json_atomic(path / 'status.json', dict(status='ready', elapsed_seconds=0, error=''))
    return path


def load_group_training(path):
    """只讀已提交結果；摘要落後不覆蓋候選及各組正式報告。"""
    path = Path(path); snapshot = _verified(path / 'snapshot.json')
    if snapshot.get('format_version') != 1 or snapshot.get('kind') != 'independent-groups':
        raise ValueError('群組學習快照版本不符')
    calibration = _verified(path / 'calibration.json') if (path / 'calibration.json').exists() else None
    if calibration and calibration.get('snapshot_identity') != snapshot['identity']: raise ValueError('校準身份不符')
    groups = {}
    for group in snapshot['groups']:
        root = path / 'groups' / group
        candidates = {}
        for file in (root / 'candidates').glob('*.json'):
            candidate = _verified(file)
            if (candidate.get('snapshot_identity') != snapshot['identity'] or candidate.get('group') != group or
                    candidate.get('strength') != file.stem or not calibration or candidate.get('calibration_identity') != calibration['identity']):
                raise ValueError('群組候選身份不符')
            EvaluationConfig.from_dict(candidate['config'])
            candidates[file.stem] = candidate
        frozen = _verified(root / 'frozen.json') if (root / 'frozen.json').exists() else None
        if frozen:
            source = candidates.get(frozen['strength'])
            if not source or frozen.get('candidate_identity') != source['identity'] or frozen['config'] != source['config']:
                raise ValueError('群組凍結候選身份不符')
        report = _verified(root / 'report.json') if (root / 'report.json').exists() else None
        if report and (not frozen or report.get('frozen_identity') != frozen['identity'] or
                       report.get('calibration_identity') != calibration['identity']):
            raise ValueError('群組報告身份不符')
        errors = _read(root / 'failures.json') if (root / 'failures.json').exists() else {}
        errors = {k: v for k, v in errors.items() if k not in candidates}
        groups[group] = dict(candidates=candidates, frozen=frozen, report=report, errors=errors,
                            status='completed' if report else 'failed' if errors else 'incomplete')
    state = _read(path / 'status.json')
    completed = sum(len(g['candidates']) for g in groups.values())
    completed_groups = sum(g['report'] is not None for g in groups.values())
    if completed_groups == len(groups): state.update(status='completed', error='')
    elif state['status'] in ('running', 'completed'): state['status'] = 'interrupted'
    state.update(path=str(path), snapshot=snapshot, calibration=calibration, groups=groups,
        completed=completed, total=len(groups)*len(snapshot['rules']['strengths']),
        completed_groups=completed_groups, failed_groups=sum(g['status'] == 'failed' for g in groups.values()))
    return state


def _metrics(rows, configs, scale, check):
    result = {split: {name: evaluate_errors(rows[split], config, scale, check) for name, config in configs.items()}
              for split in ('validation', 'test')}
    deltas = {}
    for split, values in result.items():
        deltas[split] = {}
        for name in ('original', 'learned'):
            deltas[split][name] = {}
            for baseline in ('material', 'stable'):
                def difference(a, b): return a - b if a is not None and b is not None else None
                deltas[split][name][baseline] = dict(mae=difference(values[name]['mae'], values[baseline]['mae']),
                    stages={stage: difference(values[name]['stages'][stage]['mae'], values[baseline]['stages'][stage]['mae'])
                            for stage in values[name]['stages']})
    return dict(**result, deltas=deltas)


def run_group_training(path, *, stop=None, progress=lambda state: None, now=monotonic, started_at=None):
    """只有一個開始時間與校準；組別失敗不丟棄其他組的完整結果。"""
    path = Path(path)
    with experiment_lock(path):
        saved = load_group_training(path)
        if saved['status'] == 'completed': return path
        snapshot = saved['snapshot']; rules = snapshot['rules']
        began = now() if started_at is None else started_at
        state = dict(status='running', elapsed_seconds=0, error='', completed=saved['completed'],
            total=saved['total'], completed_groups=saved['completed_groups'], failed_groups=0,
            current_group='', current_candidate='', worker_pid=None, group_states={g:r['status'] for g,r in saved['groups'].items()})
        def report(**update):
            state.update(update, elapsed_seconds=now()-began)
            state['failed_groups'] = sum(value == 'failed' for value in state['group_states'].values())
            write_json_atomic(path / 'status.json', state)
            progress(deepcopy(state))
        def check():
            if stop is not None and stop.is_set(): raise TrainingStopped('使用者停止；剩餘群組可手動續跑')
            if now()-began >= rules['max_seconds']: raise TrainingStopped('已達八小時上限；所有群組共用整次預算')
        try:
            report(); check()
            current = training_rules()
            if any(rules[k] != current[k] for k in ('version', 'numpy', 'scipy')): raise ValueError('數值版本已改變；請另建實驗')
            inputs = _read(path / 'inputs.json'); check()
            if digest(inputs) != snapshot['inputs_sha256']: raise ValueError('學習資料身份不符')
            rows = {s: [r for r in inputs['positions'] if r['split'] == s] for s in ('train', 'validation', 'test')}
            stable = EvaluationConfig.from_dict(snapshot['stable'])
            calibration = saved['calibration']
            if calibration is None:
                calibration = calibrate(rows['train'], stable, rules, check)
                calibration.update(snapshot_identity=snapshot['identity'], reference=snapshot['stable'])
                _seal(calibration); check(); write_json_atomic(path / 'calibration.json', calibration)
            for group in snapshot['groups']:
                check()
                previous = saved['groups'][group]
                if previous['report']: continue
                root = path / 'groups' / group; definition = snapshot['definitions'][group]
                original = EvaluationConfig.from_dict(definition['original'])
                candidates = previous['candidates']; errors = dict(previous['errors'])
                state['group_states'][group] = 'running'
                report(current_group=group, current_candidate='', worker_pid=None)
                try:
                    if previous['frozen'] is None:
                        for name, strength in rules['strengths']:
                            check()
                            if name in candidates: continue
                            report(current_candidate=name, worker_pid=None)
                            try:
                                config, solved = fit_position_weights(rows['train'], original, definition['terms'], calibration['scale'], strength, rules,
                                    check=check, started=lambda pid: report(worker_pid=pid))
                                validation = evaluate_errors(rows['validation'], config, calibration['scale'], check)
                                candidate = _seal(dict(group=group, strength=name, penalty=strength, config=config.to_dict(),
                                    validation=validation, solver=solved, kind='single', groups=[group],
                                    snapshot_identity=snapshot['identity'], calibration_identity=calibration['identity']))
                                check(); write_json_atomic(root / 'candidates' / f'{name}.json', candidate)
                                candidates[name] = candidate; errors.pop(name, None)
                                report(completed=state['completed']+1, worker_pid=None)
                            except TrainingStopped: raise
                            except Exception as exc:
                                errors[name] = str(exc)
                                write_json_atomic(root / 'failures.json', errors)
                        if len(candidates) != len(rules['strengths']): raise ValueError('群組有失敗候選，重試完成後才選定與測試')
                        best = select_candidate(candidates, rules, empty_error='驗證組無資料；不可選定候選')
                        frozen = _seal(dict(group=group, strength=best['strength'], config=best['config'], validation=best['validation'],
                            candidate_identity=best['identity'], snapshot_identity=snapshot['identity'], selection_order=rules['selection_order']))
                        check(); write_json_atomic(root / 'frozen.json', frozen)
                    else: frozen = previous['frozen']
                    material = deepcopy(definition['original'])
                    for name, settings in material['terms'].items(): settings['enabled'] = name == 'material'
                    configs = dict(material=EvaluationConfig.from_dict(material), original=original,
                        learned=EvaluationConfig.from_dict(frozen['config']), stable=stable)
                    report(current_candidate='frozen-test', worker_pid=None)
                    metrics = _metrics(rows, configs, calibration['scale'], check)
                    improved = all(metrics[s]['original']['mae'] is not None and metrics[s]['learned']['mae'] is not None and
                        metrics[s]['learned']['mae'] < metrics[s]['original']['mae'] for s in ('validation', 'test'))
                    final = _seal(dict(**metrics, frozen_identity=frozen['identity'], calibration_identity=calibration['identity'],
                        reliable_ranking=calibration['healthy'] and all(metrics[s]['learned']['mae'] is not None for s in ('validation','test')), priority_battle_observation=calibration['healthy'] and improved,
                        data_use=snapshot['data_use']))
                    check(); write_json_atomic(root / 'report.json', final)
                    state['group_states'][group] = 'completed'
                    report(completed_groups=state['completed_groups']+1, current_candidate='', worker_pid=None)
                except TrainingStopped: raise
                except Exception as exc:
                    errors['group'] = str(exc); write_json_atomic(root / 'failures.json', errors)
                    state['group_states'][group] = 'failed'
                    report(failed_groups=state['failed_groups']+1, error=f'{GROUPS[group]}：{exc}', worker_pid=None)
            report(status='completed' if state['completed_groups'] == len(snapshot['groups']) else 'partial', current_group='', current_candidate='', worker_pid=None)
        except TrainingStopped as exc: report(status='stopped', error=str(exc), worker_pid=None)
        except Exception as exc: report(status='failed', error=str(exc), worker_pid=None)
    return path


def load_group_candidate(path, group):
    """後續組合及對戰共用的完整候選與來源身份。"""
    saved = load_group_training(path); result = saved['groups'][group]
    if not result['report']: raise ValueError('此群組尚未完成凍結測試')
    snapshot = saved['snapshot']; frozen = result['frozen']
    return dict(kind='single', groups=[group], experiment_id=snapshot['id'], snapshot_identity=snapshot['identity'],
        candidate_identity=frozen['candidate_identity'], frozen_identity=frozen['identity'], config=deepcopy(frozen['config']),
        strength=frozen['strength'], rules=deepcopy(snapshot['rules']),
        dataset_identity=snapshot['dataset_identity'], label_identity=snapshot['label_identity'],
        calibration_identity=saved['calibration']['identity'], calibration=deepcopy(saved['calibration']),
        original=deepcopy(snapshot['definitions'][group]['original']), stable=deepcopy(snapshot['stable']),
        test_data_identity=snapshot['test_data_identity'], prior_test_experiments=snapshot['prior_test_experiments'],
        label_path=snapshot['label_path'], report=deepcopy(result['report']))


def save_group_config(path, group, destination):
    config = EvaluationConfig.from_dict(load_group_candidate(path, group)['config'])
    destination = Path(destination)
    if destination.exists(): raise ValueError('目標已存在；請使用新檔名')
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(destination, config.to_dict())
    return destination


class GroupTrainingRun:
    def __init__(self, path, executor, *, label_path=None, groups=None, **options):
        self.path = Path(path); self._stop, self._lock = Event(), Lock()
        self.label_path, self.groups = label_path, groups
        if label_path is None:
            saved = load_group_training(path)
            self._state = {k: saved[k] for k in ('status','completed','total','completed_groups','failed_groups','elapsed_seconds','error')}
        else:
            self._state = dict(status='queued', completed=0, total=len(groups or GROUPS)*3, completed_groups=0, failed_groups=0, elapsed_seconds=0, error='')
        self.future = executor.submit(self._work, options)
    def _work(self, options):
        try:
            began = options.get('now', monotonic)()
            if self.label_path is not None: create_group_training(self.label_path, self.groups, run_path=self.path)
            return run_group_training(self.path, stop=self._stop, progress=self._progress, started_at=began, **options)
        except Exception as exc: self._progress(dict(status='failed', error=str(exc)))
    def _progress(self, state):
        with self._lock: self._state.update(state)
    def snapshot(self):
        with self._lock: return deepcopy(self._state)
    def stop(self): self._stop.set()
