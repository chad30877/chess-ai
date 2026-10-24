"""同源單組權重的直接組合與獨立聯合訓練。"""
from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from uuid import uuid4

from engine.evaluation.config import EvaluationConfig
from engine.learning.group_training import GROUPS, load_group_candidate, load_group_training
from engine.learning.teacher import digest
from engine.learning.training import training_rules, fit_position_weights, evaluate_errors, TrainingStopped
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _seal(value):
    value['identity'] = digest(value)
    return value


def _verified(path):
    value = _read(path); content = dict(value); content.pop('identity', None)
    if value.get('identity') != digest(content): raise ValueError('組合提交內容身份不符')
    return value


def preview_combination(sources):
    """先核對來源尺度，再回傳實際原始／直接權重與選中欄位。"""
    if not sources: raise ValueError('請至少選擇一組已完成單組結果')
    first = sources[0]; selected = []
    for source in sources:
        if source.get('kind') != 'single' or len(source.get('groups', [])) != 1:
            raise ValueError('組合來源必須是已完成單群組候選')
        group = source['groups'][0]
        if group not in GROUPS or group in selected: raise ValueError('來源群組不合法或重複')
        for key in ('snapshot_identity', 'dataset_identity', 'label_identity', 'test_data_identity',
                    'calibration_identity', 'calibration', 'rules', 'stable'):
            if source[key] != first[key]: raise ValueError('來源資料、校準或規則不相容；請選同一實驗')
        if source['calibration_identity'] != source['calibration']['identity']:
            raise ValueError('來源校準身份不符')
        selected.append(group)
    groups = [g for g in GROUPS if g in selected]
    sources = sorted(sources, key=lambda s: groups.index(s['groups'][0]))
    original = deepcopy(first['original']); direct = deepcopy(original); terms = []
    for payload in (original, direct):
        for name, term in payload['terms'].items(): term['enabled'] = name == 'material'
    for source in sources:
        before = source['original']; after = source['config']
        for key in before:
            if key != 'terms' and (before[key] != first['original'][key] or after[key] != before[key]):
                raise ValueError('來源階段或固定子力不相容')
        if before['terms']['material'] != first['original']['terms']['material'] or after['terms']['material'] != before['terms']['material']:
            raise ValueError('來源固定子力不相容')
        for name, settings in before['terms'].items():
            if name == 'material': continue
            if after['terms'][name]['enabled'] != settings['enabled']: raise ValueError('來源群組開關已變更')
            if settings['enabled']:
                if name in terms: raise ValueError('來源評分項重疊')
                terms.append(name); original['terms'][name] = deepcopy(settings)
                direct['terms'][name] = deepcopy(after['terms'][name])
    EvaluationConfig.from_dict(original); EvaluationConfig.from_dict(direct)
    return dict(groups=groups, original=original, direct=direct, terms=terms, candidate_count=3)


def create_combination(source_path, groups=None, *, run_path=None):
    """先保存共同原始值、來源凍結權重及已曝光測試脈絡。"""
    groups = ['mobility', 'king-safety'] if groups is None else list(groups)
    sources = [load_group_candidate(source_path, g) for g in groups]
    preview = preview_combination(sources)
    source = load_group_training(source_path); inputs = _read(Path(source_path)/'inputs.json')
    if digest(inputs) != source['snapshot']['inputs_sha256']: raise ValueError('來源資料身份不符')
    first = sources[0]
    label_path = Path(source_path).resolve().parents[1]
    path = Path(run_path) if run_path else label_path/'combinations'/uuid4().hex
    if path.exists(): raise ValueError('組合條件不可變；請建立新實驗')
    prior = deepcopy(first['prior_test_experiments'])
    prior.append(dict(experiment_id=first['experiment_id'], snapshot_identity=first['snapshot_identity'], label_identity=first['label_identity']))
    for entry in (label_path/'combinations').glob('*/snapshot.json'):
        previous = _verified(entry)
        if previous['test_data_identity'] == first['test_data_identity'] and list(entry.parent.glob('*/report.json')):
            prior.append(dict(experiment_id=previous['id'], snapshot_identity=previous['identity'], label_identity=previous['label_identity']))
    prior = list({p['snapshot_identity']:p for p in prior}.values())
    rules = deepcopy(first['rules']); weights = [preview['original']['terms'][t][key] for t in preview['terms'] for key in ('weight','endgame_weight')]
    snapshot = _seal(dict(format_version=1, id=path.name, kind='combination', **preview,
        rules=rules, stable=first['stable'], sources=sources, source_path=str(Path(source_path).resolve()),
        calibration_identity=first['calibration_identity'], calibration=first['calibration'],
        dataset_identity=first['dataset_identity'], label_identity=first['label_identity'], label_path=str(label_path),
        test_data_identity=first['test_data_identity'], prior_test_experiments=prior,
        data_use='沿用單組來源已曝光的測試資料；直接組合與聯合訓練分別保存，不代表全新未見測試。',
        inputs_sha256=digest(inputs), penalty_center='selected-groups-original-v1', original_weights=weights,
        scales=[abs(w) or rules['zero_scale'] for w in weights],
        column_order=[f'{t}:{s}' for t in preview['terms'] for s in ('middlegame','endgame')]))
    path.mkdir(parents=True)
    for folder in ('candidates','direct','joint'): (path/folder).mkdir()
    write_json_atomic(path/'inputs.json', inputs); write_json_atomic(path/'snapshot.json', snapshot)
    write_json_atomic(path/'status.json', dict(status='ready', elapsed_seconds=0, error=''))
    return path


def load_combination(path):
    """僅讀已提交結果；來源移除後仍能恢復已保存實驗。"""
    path = Path(path); snapshot = _verified(path/'snapshot.json')
    if snapshot.get('format_version') != 1 or snapshot.get('kind') != 'combination': raise ValueError('組合格式不符')
    preview = preview_combination(snapshot['sources'])
    if any(preview[k] != snapshot[k] for k in ('original','direct','groups','terms')): raise ValueError('組合快照與來源權重不符')
    candidates = {}
    for file in (path/'candidates').glob('*.json'):
        item = _verified(file)
        if item['snapshot_identity'] != snapshot['identity'] or item['strength'] != file.stem or item['calibration_identity'] != snapshot['calibration_identity']:
            raise ValueError('聯合候選來源身份不符')
        EvaluationConfig.from_dict(item['config']); candidates[file.stem] = item
    results = {}
    for kind in ('direct','joint'):
        frozen = _verified(path/kind/'frozen.json') if (path/kind/'frozen.json').exists() else None
        report = _verified(path/kind/'report.json') if (path/kind/'report.json').exists() else None
        if frozen:
            if frozen['snapshot_identity'] != snapshot['identity'] or frozen['kind'] != kind: raise ValueError('凍結身份不符')
            EvaluationConfig.from_dict(frozen['config'])
            if kind == 'direct':
                if frozen['config'] != snapshot['direct']: raise ValueError('直接組合權重已變更')
            else:
                candidate = candidates.get(frozen['strength'])
                if not candidate or any(candidate[k] != frozen[k] for k in ('config','validation')) or candidate['identity'] != frozen['candidate_identity']:
                    raise ValueError('聯合凍結與候選不同')
        if report and (not frozen or report['frozen_identity'] != frozen['identity'] or report['calibration_identity'] != snapshot['calibration_identity']):
            raise ValueError('組合報告來源不符')
        results[kind] = dict(frozen=frozen, report=report)
    controls = _verified(path/'controls.json') if (path/'controls.json').exists() else None
    if controls and (controls['snapshot_identity'] != snapshot['identity'] or controls['calibration_identity'] != snapshot['calibration_identity']):
        raise ValueError('固定四設定來源不符')
    state = _read(path/'status.json')
    if all(r['report'] for r in results.values()) and (controls or not {'mobility','king-safety'} <= set(snapshot['groups'])):
        state.update(status='completed', error='')
    elif state['status'] in ('completed','running'): state['status'] = 'interrupted'
    state.update(path=str(path), snapshot=snapshot, candidates=candidates, results=results,
        calibration=snapshot['calibration'], controls=controls, completed=len(candidates), total=3)
    return state


def _metrics(rows, snapshot, learned, check):
    material = deepcopy(snapshot['original'])
    for name, term in material['terms'].items(): term['enabled'] = name == 'material'
    configs = dict(material=material, original=snapshot['original'], learned=learned, stable=snapshot['stable'])
    return {s:{name:evaluate_errors(rows[s], EvaluationConfig.from_dict(config), snapshot['calibration']['scale'], check)
        for name, config in configs.items()} for s in ('validation','test')}


def fixed_weight_metrics(rows, config, scale, check=lambda:None):
    """同一權重僅切四種開關，負增量代表加入王安全後誤差較小。"""
    payload = config.to_dict(); configs = {}; metrics = {}
    mobility = {n for n in payload['terms'] if n.endswith('_mobility')}
    king = {'king_pawn_shield','king_zone_attacks','king_file_exposure'}
    for name, selected in (('material',set()),('mobility',mobility),('king-safety',king),('both',mobility|king)):
        value = deepcopy(payload)
        for term, settings in value['terms'].items(): settings['enabled'] = term == 'material' or (term in selected and payload['terms'][term]['enabled'])
        configs[name] = value
        metrics[name] = evaluate_errors(rows, EvaluationConfig.from_dict(value), scale, check)
    def delta(a, b):
        left, right = metrics[a], metrics[b]
        def difference(x,y): return x-y if x is not None and y is not None else None
        return dict(mae=difference(left['mae'],right['mae']),
            stages={s:difference(left['stages'][s]['mae'],right['stages'][s]['mae']) for s in left['stages']})
    return dict(configs=configs, metrics=metrics,
        king_increments=dict(without_mobility=delta('king-safety','material'), with_mobility=delta('both','mobility')))


def run_combination(path, *, stop=None, progress=lambda state:None, now=monotonic, started_at=None):
    """直接結果與逐候選提交共用一次八小時；測試只評估各自凍結設定。"""
    path = Path(path)
    began = now() if started_at is None else started_at
    with experiment_lock(path):
        saved = load_combination(path)
        if saved['status'] == 'completed': return path
        snapshot = saved['snapshot']; rules = snapshot['rules']
        state = dict(status='running', elapsed_seconds=0, error='', completed=saved['completed'], total=3, current_candidate='', worker_pid=None)
        def report(**updates):
            state.update(updates, elapsed_seconds=now()-began)
            write_json_atomic(path/'status.json', state); progress(deepcopy(state))
        def check():
            if stop is not None and stop.is_set(): raise TrainingStopped('使用者停止；未完成工作可手動續跑')
            if now()-began >= rules['max_seconds']: raise TrainingStopped('已達八小時上限；組合全程共用期限')
        def freeze(kind, config, **details):
            frozen = _seal(dict(kind=kind, groups=snapshot['groups'], config=config,
                snapshot_identity=snapshot['identity'], calibration_identity=snapshot['calibration_identity'], **details))
            check(); write_json_atomic(path/kind/'frozen.json', frozen)
            return frozen
        def finish(kind, frozen):
            report(current_candidate=kind+'-frozen-test', worker_pid=None)
            metrics = _metrics(rows, snapshot, frozen['config'], check)
            improved = all(metrics[s]['original']['mae'] is not None and metrics[s]['learned']['mae'] is not None and
                metrics[s]['learned']['mae'] < metrics[s]['original']['mae'] for s in ('validation','test'))
            final = _seal(dict(**metrics, frozen_identity=frozen['identity'], calibration_identity=snapshot['calibration_identity'],
                reliable_ranking=snapshot['calibration']['healthy'] and all(metrics[s]['learned']['mae'] is not None for s in ('validation','test')),
                priority_battle_observation=snapshot['calibration']['healthy'] and improved, data_use=snapshot['data_use']))
            check(); write_json_atomic(path/kind/'report.json', final)
        try:
            report(); check()
            current = training_rules()
            if any(current[k] != rules[k] for k in ('version','numpy','scipy')): raise ValueError('數值版本不同；請另建組合')
            inputs = _read(path/'inputs.json'); check()
            if digest(inputs) != snapshot['inputs_sha256']: raise ValueError('組合資料身份不符')
            rows = {s:[r for r in inputs['positions'] if r['split'] == s] for s in ('train','validation','test')}
            if not saved['results']['direct']['report']:
                frozen = saved['results']['direct']['frozen'] or freeze('direct', snapshot['direct'])
                finish('direct', frozen)
            if not saved['controls'] and {'mobility','king-safety'} <= set(snapshot['groups']):
                report(current_candidate='fixed-controls', worker_pid=None)
                controls = {s:fixed_weight_metrics(rows[s], EvaluationConfig.from_dict(snapshot['direct']), snapshot['calibration']['scale'], check)
                    for s in ('validation','test')}
                controls = _seal(dict(**controls, snapshot_identity=snapshot['identity'], calibration_identity=snapshot['calibration_identity'],
                    weight_source='direct', data_use=snapshot['data_use']))
                check(); write_json_atomic(path/'controls.json', controls)
            candidates = saved['candidates']; previous = saved['results']['joint']
            if previous['frozen'] is None:
                for name, strength in rules['strengths']:
                    check()
                    if name in candidates: continue
                    report(current_candidate=name, worker_pid=None)
                    config, solved = fit_position_weights(rows['train'], EvaluationConfig.from_dict(snapshot['original']),
                        snapshot['terms'], snapshot['calibration']['scale'], strength, rules,
                        check=check, started=lambda pid:report(worker_pid=pid))
                    validation = evaluate_errors(rows['validation'], config, snapshot['calibration']['scale'], check)
                    candidate = _seal(dict(kind='joint', groups=snapshot['groups'], strength=name, penalty=strength,
                        config=config.to_dict(), validation=validation, solver=solved, snapshot_identity=snapshot['identity'],
                        calibration_identity=snapshot['calibration_identity']))
                    check(); write_json_atomic(path/'candidates'/f'{name}.json', candidate); candidates[name] = candidate
                    report(completed=len(candidates), worker_pid=None)
                eligible = [candidates[n] for n in rules['selection_order'] if candidates[n]['validation']['mae'] is not None]
                if not eligible: raise ValueError('驗證組無有效資料；不可選定聯合候選')
                best = eligible[0]
                for item in eligible[1:]:
                    if item['validation']['mae'] < best['validation']['mae']-rules['tie_tolerance']: best = item
                frozen = freeze('joint', best['config'], validation=best['validation'], strength=best['strength'],
                    candidate_identity=best['identity'], selection_order=rules['selection_order'])
            else: frozen = previous['frozen']
            if not previous['report']: finish('joint', frozen)
            report(status='completed', current_candidate='', worker_pid=None)
        except TrainingStopped as exc: report(status='stopped', error=str(exc), worker_pid=None)
        except Exception as exc: report(status='failed', error=str(exc), worker_pid=None)
    return path


def load_combination_candidate(path, kind='joint'):
    """與單組候選相同的設定及來源契約，供既有對戰比較使用。"""
    if kind not in ('direct','joint'): raise ValueError('請選直接組合或聯合訓練')
    saved = load_combination(path); snapshot = saved['snapshot']; result = saved['results'][kind]
    if not result['report']: raise ValueError('此組合尚未完成凍結測試')
    frozen = result['frozen']
    return dict(kind=kind, groups=snapshot['groups'], experiment_id=snapshot['id'], snapshot_identity=snapshot['identity'],
        candidate_identity=frozen.get('candidate_identity', frozen['identity']), frozen_identity=frozen['identity'],
        config=deepcopy(frozen['config']), strength=frozen.get('strength'), rules=deepcopy(snapshot['rules']),
        dataset_identity=snapshot['dataset_identity'], label_identity=snapshot['label_identity'],
        calibration_identity=snapshot['calibration_identity'], calibration=deepcopy(saved['calibration']),
        original=deepcopy(snapshot['original']), stable=deepcopy(snapshot['stable']), test_data_identity=snapshot['test_data_identity'],
        prior_test_experiments=deepcopy(snapshot['prior_test_experiments']), label_path=snapshot['label_path'],
        sources=deepcopy(snapshot['sources']), report=deepcopy(result['report']))


def save_combination_config(path, kind, destination):
    config = EvaluationConfig.from_dict(load_combination_candidate(path, kind)['config'])
    destination = Path(destination)
    if destination.exists(): raise ValueError('目標已存在；請使用新檔名')
    destination.parent.mkdir(parents=True, exist_ok=True); write_json_atomic(destination, config.to_dict())
    return destination


class CombinationRun:
    def __init__(self, path, executor, *, source_path=None, groups=None, **options):
        self.path = Path(path); self.source_path = source_path; self.groups = groups
        self._stop = Event(); self._lock = Lock()
        saved = load_combination(path) if source_path is None else dict(status='queued', completed=0, total=3, elapsed_seconds=0, error='')
        self._state = {k:saved[k] for k in ('status','completed','total','elapsed_seconds','error')}
        self.future = executor.submit(self._work, options)
    def _work(self, options):
        try:
            began = options.get('now', monotonic)()
            if self.source_path is not None: create_combination(self.source_path, self.groups, run_path=self.path)
            return run_combination(self.path, stop=self._stop, progress=self._progress, started_at=began, **options)
        except Exception as exc: self._progress(dict(status='failed', error=str(exc)))
    def _progress(self, state):
        with self._lock: self._state.update(state)
    def snapshot(self):
        with self._lock: return deepcopy(self._state)
    def stop(self): self._stop.set()
