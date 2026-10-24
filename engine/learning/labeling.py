"""不可變教師條件、逐局面提交與可恢復標記資料。"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from uuid import uuid4

from engine.learning.dataset import load_dataset, SPLITS
from engine.learning.teacher import UciTeacher, TeacherStopped, MAX_SECONDS, digest, load_pilot
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic

LABEL_VERSION = 1
SAMPLE_FIELDS = ('game_id', 'split', 'stage', 'initial_fen', 'moves_uci', 'fen')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _matches(record, sample, nodes, score_policy):
    return (record.get('sample_id') == sample['position_id'] and
            record.get('requested_nodes') == nodes and record.get('score_policy') == score_policy and
            all(record.get(key) == sample[key] for key in SAMPLE_FIELDS))


def _envelope(snapshot, sample, record, origin):
    return dict(sample_id=sample['position_id'], work_id=digest([snapshot['identity'], sample['position_id']]),
                snapshot_identity=snapshot['identity'], origin=origin, label=record)


def create_labeling(dataset_path, pilot_path, *, run_path=None):
    """由已選定先導建立新標記快照；來源及教師改動不覆寫既有實驗。"""
    dataset_path, pilot_path = Path(dataset_path), Path(pilot_path)
    data, pilot = load_dataset(dataset_path), load_pilot(pilot_path)
    choice = pilot.get('choice')
    if not choice:
        raise ValueError('請先完成教師先導並選定預算')
    identity = dict(choice)
    identity.pop('identity', None)
    if (choice['identity'] != digest(identity) or choice['dataset_sha256'] != digest(data) or
            choice['pilot_snapshot_sha256'] != digest(pilot['snapshot']) or
            choice['teacher'] != pilot['snapshot']['teacher']):
        raise ValueError('教師選擇與資料或先導身份不一致；請建立新先導')
    if choice['filter_version'] != 1 or choice['cp_special_threshold'] != 20000:
        raise ValueError('篩選條件版本不相容；請建立新先導')
    if not data['positions']:
        raise ValueError('沒有可標記局面')
    path = Path(run_path) if run_path else dataset_path / 'teacher-labels' / uuid4().hex
    if (path / 'snapshot.json').exists():
        raise ValueError('標記條件不可變；請建立新實驗')
    path.mkdir(parents=True, exist_ok=run_path is not None)
    snapshot = dict(format_version=1, processing_version=LABEL_VERSION,
        experiment_id=path.name, dataset_sha256=digest(data), dataset_path=str(dataset_path.resolve()),
        choice=deepcopy(choice), teacher=deepcopy(choice['teacher']), nodes=choice['nodes'],
        filter_version=choice['filter_version'], cp_special_threshold=choice['cp_special_threshold'],
        max_seconds=MAX_SECONDS, pilot_path=str(pilot_path.resolve()))
    snapshot['identity'] = digest(snapshot)
    write_json_atomic(path / 'dataset.json', data)
    write_json_atomic(path / 'snapshot.json', snapshot)
    (path / 'records').mkdir()
    (path / 'failures').mkdir()
    by_id = {s['position_id']: s for s in data['positions']}
    for record in pilot['records']:
        sample = by_id.get(record['sample_id'])
        if sample and _matches(record, sample, snapshot['nodes'], snapshot['teacher']['score_policy']):
            write_json_atomic(path / 'records' / f'{sample["position_id"]}.json',
                              _envelope(snapshot, sample, deepcopy(record), 'pilot'))
    write_json_atomic(path / 'status.json', dict(status='ready', path=str(path), elapsed_seconds=0, error=''))
    return path


def load_labeling(path):
    """提交紀錄為事實來源；只讀重建過期或落後的進度摘要。"""
    path = Path(path)
    snapshot, data = _read(path / 'snapshot.json'), load_dataset(path)
    identity = dict(snapshot)
    identity.pop('identity', None)
    if (snapshot.get('format_version') != 1 or snapshot.get('processing_version') != LABEL_VERSION or
            snapshot['identity'] != digest(identity) or snapshot['dataset_sha256'] != digest(data)):
        raise ValueError('標記快照版本或資料身份不一致')
    by_id = {s['position_id']: s for s in data['positions']}
    records, seen = [], set()
    for file in sorted((path / 'records').glob('*.json')):
        record = _read(file)
        sample = by_id.get(record.get('sample_id'))
        if (sample is None or record['sample_id'] in seen or record.get('snapshot_identity') != snapshot['identity'] or
                record.get('work_id') != digest([snapshot['identity'], record['sample_id']]) or
                not _matches(record['label'], sample, snapshot['nodes'], snapshot['teacher']['score_policy'])):
            raise ValueError('已提交教師標記身份不一致')
        records.append(record)
        seen.add(record['sample_id'])
    failures = [_read(file) for file in sorted((path / 'failures').glob('*.json')) if file.stem not in seen]
    state = _read(path / 'status.json') if (path / 'status.json').exists() else dict(status='interrupted', elapsed_seconds=0)
    _summarize(state, path, snapshot, data, records, failures)
    completed, total = state['completed'], state['total']
    if completed == total:
        state.update(status='completed', error='')
    elif state.get('status') == 'completed':
        state.update(status='interrupted', error='摘要顯示完成，但尚有未提交局面')
    return state


def _summarize(state, path, snapshot, data, records, failures):
    total, completed = len(data['positions']), len(records)
    splits = {}
    for split in SPLITS:
        valid = [r['label'] for r in records if r['label']['split'] == split and r['label']['valid']]
        splits[split] = dict(games=len({r['game_id'] for r in valid}), positions=len(valid),
                            stages=dict(Counter(r['stage'] for r in valid)))
    summary = dict(valid=sum(r['label']['valid'] for r in records),
        excluded=sum(not r['label']['valid'] for r in records),
        reasons=dict(Counter(reason for r in records for reason in r['label']['exclusion_reasons'])),
        data_exclusions=data['summary']['excluded'], reused_pilot=sum(r['origin'] == 'pilot' for r in records),
        splits=splits, shortfall_games=data['summary']['shortfall_games'])
    state.update(path=str(path), snapshot=snapshot, dataset=data, records=records, failures=failures,
                 completed=completed, total=total, remaining=total-completed, failed=len(failures),
                 retry=len(failures), summary=summary, ready=completed == total)
    return state


def load_labeled_dataset(path):
    """正式學習入口只接受所有分組標記均已完成的快照。"""
    state = load_labeling(path)
    if not state['ready']:
        raise ValueError('教師標記未完成；部分資料不能進入正式學習')
    by_id = {r['sample_id']: r['label'] for r in state['records']}
    positions = [dict(sample, label=deepcopy(by_id[sample['position_id']]))
                 for sample in state['dataset']['positions'] if by_id[sample['position_id']]['valid']]
    return dict(snapshot=state['snapshot'], dataset=state['dataset'], positions=positions, summary=state['summary'])


def run_labeling(path, *, stop=None, progress=lambda state: None, now=monotonic, timeout=30):
    """新一次八小時預算；只處理未提交局面，絕不自動重新啟動。"""
    path = Path(path)
    with experiment_lock(path):
        saved = load_labeling(path)
        if saved['ready']:
            progress(saved)
            return path
        started = now()
        snapshot, data = saved['snapshot'], saved['dataset']
        state = dict(status='running', path=str(path), elapsed_seconds=0, error='')
        records = list(saved['records'])
        failures = {f['sample_id']: f for f in saved['failures']}
        def report(**update):
            state.update(update, elapsed_seconds=now() - started)
            write_json_atomic(path / 'status.json', state)
            current = _summarize(dict(state), path, snapshot, data, records, list(failures.values()))
            progress({key: value for key, value in current.items() if key not in ('records', 'dataset')})
        report()
        current_sample = None
        teacher = None
        try:
            with UciTeacher(snapshot['teacher']['command'], stop=stop, deadline=started + MAX_SECONDS,
                            now=now, timeout=timeout) as teacher:
                if teacher.metadata != snapshot['teacher']:
                    raise ValueError('教師執行檔或 UCI 條件與凍結快照不同；請建立新先導及標記實驗')
                completed = {record['sample_id'] for record in saved['records']}
                for sample in data['positions']:
                    if sample['position_id'] in completed:
                        continue
                    current_sample = sample
                    record = teacher.analyse(sample, snapshot['nodes'])
                    teacher.check()
                    committed = _envelope(snapshot, sample, record, 'teacher')
                    write_json_atomic(path / 'records' / f'{sample["position_id"]}.json', committed)
                    records.append(committed)
                    completed.add(sample['position_id'])
                    failures.pop(sample['position_id'], None)
                    current_sample = None
                    report()
                report(status='completed')
        except TeacherStopped as exc:
            report(status='stopped', error=str(exc))
        except Exception as exc:
            if current_sample is not None:
                failure_path = path / 'failures' / f'{current_sample["position_id"]}.json'
                previous = _read(failure_path) if failure_path.exists() else {}
                failure = dict(sample_id=current_sample['position_id'],
                    split=current_sample['split'], error=str(exc), attempts=previous.get('attempts', 0)+1,
                    raw_output=getattr(teacher, 'last_output', []))
                write_json_atomic(failure_path, failure)
                failures[current_sample['position_id']] = failure
            report(status='failed', error=str(exc))
    return path


class LabelRun:
    """UI 背景執行／續跑；競爭鎖失敗不覆寫另一個執行者的狀態。"""
    def __init__(self, path, executor, **options):
        self.path = Path(path)
        self._stop, self._lock = Event(), Lock()
        saved = load_labeling(self.path)
        self._state = {key: value for key, value in saved.items() if key not in ('records', 'dataset')}
        self._state['status'] = 'queued'
        self.future = executor.submit(self._work, options)

    def _work(self, options):
        try:
            return run_labeling(self.path, stop=self._stop, progress=self._progress, **options)
        except Exception as exc:
            self._progress(dict(status='failed', error=f'標記執行失敗：{exc}'))
            return self.path

    def _progress(self, state):
        with self._lock: self._state.update(state)

    def snapshot(self):
        with self._lock: return dict(self._state)

    def stop(self):
        self._stop.set()
