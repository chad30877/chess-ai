"""多組評分項群組的可恢復研究批次。"""
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from time import monotonic
from uuid import uuid4

from engine.learning.combination_training import (
    _read, _seal, _verified, create_combination, load_combination,
    preview_combination, run_combination,
)
from engine.learning.group_training import GROUPS, load_group_candidate
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic


def create_combination_batch(source_path, selections=None, *, run_path=None):
    """凍結來源及所選組合；預設選取所有至少兩群組的組合。"""
    source_path = Path(source_path).resolve()
    names = list(GROUPS)
    if selections is None:
        selections = [list(c) for size in range(2, len(names) + 1) for c in combinations(names, size)]
    normalized = []
    for selected in selections:
        if len(selected) < 2 or len(set(selected)) != len(selected) or any(g not in GROUPS for g in selected):
            raise ValueError('請選擇至少兩個不重複的評分項群組')
        group = [g for g in names if g in selected]
        if group in normalized: raise ValueError('組合不可重複')
        normalized.append(group)
    if not normalized: raise ValueError('請選擇組合')
    sources = {g: load_group_candidate(source_path, g) for g in names if any(g in c for c in normalized)}
    preview_combination(list(sources.values()))
    path = Path(run_path) if run_path else source_path.parents[1] / 'combination-batches' / uuid4().hex
    if path.exists(): raise ValueError('研究批次已存在')
    snapshot = _seal(dict(format_version=1, source_path=str(source_path), selections=normalized,
        sources={g: sources[g]['frozen_identity'] for g in sources},
        source_identity=next(iter(sources.values()))['snapshot_identity'],
        max_seconds=next(iter(sources.values()))['rules']['max_seconds']))
    path.mkdir(parents=True)
    write_json_atomic(path/'snapshot.json', snapshot)
    write_json_atomic(path/'items.json', {})
    write_json_atomic(path/'status.json', dict(status='ready', error='', elapsed_seconds=0))
    return path


def load_combination_batch(path):
    path = Path(path)
    snapshot = _verified(path/'snapshot.json')
    if snapshot.get('format_version') != 1: raise ValueError('批次格式不符')
    mappings = _read(path/'items.json')
    items = []
    for groups in snapshot['selections']:
        key = '+'.join(groups)
        item = dict(groups=groups, path=mappings.get(key), status='pending', data_use='')
        if item['path']:
            saved = load_combination(item['path'])
            source_ids = {s['groups'][0]: s['frozen_identity'] for s in saved['snapshot']['sources']}
            if (saved['snapshot']['groups'] != groups or
                    source_ids != {g:snapshot['sources'][g] for g in groups}):
                raise ValueError('組合來源與批次不相容')
            item.update(status=saved['status'], data_use=saved['snapshot']['data_use'])
        items.append(item)
    state = _read(path/'status.json')
    complete = sum(i['status'] == 'completed' for i in items)
    if complete == len(items): state.update(status='completed', error='')
    elif state['status'] in ('running','completed'): state['status'] = 'interrupted'
    return dict(**state, snapshot=snapshot, items=items, completed=complete, total=len(items))


def run_combination_batch(path, *, stop=None, progress=lambda state:None, now=monotonic):
    """整批共用一次期限，既有提交保持不變，停止後由使用者手動續跑。"""
    path = Path(path); began = now()
    with experiment_lock(path):
        saved = load_combination_batch(path); snapshot = saved['snapshot']
        if saved['status'] == 'completed': return path
        source = Path(snapshot['source_path'])
        for g, identity in snapshot['sources'].items():
            if load_group_candidate(source, g)['frozen_identity'] != identity:
                raise ValueError('單群組來源已變更，無法續跑')
        mappings = _read(path/'items.json')
        def report(status, error=''):
            write_json_atomic(path/'status.json', dict(status=status, error=error, elapsed_seconds=now()-began))
            current = load_combination_batch(path)
            if status == 'running': current['status'] = 'running'
            progress(deepcopy(current))
        report('running')
        for item in saved['items']:
            if stop is not None and stop.is_set(): report('stopped', '使用者停止；可手動續跑'); return path
            if now()-began >= snapshot['max_seconds']: report('stopped', '已達八小時上限；可手動續跑'); return path
            if item['status'] == 'completed': continue
            groups = item['groups']; key = '+'.join(groups)
            if not item['path']:
                # 只沿用凍結單組身份完全相符的已保存結果。
                for entry in sorted((source.parents[1]/'combinations').glob('*/snapshot.json')):
                    try:
                        candidate = load_combination(entry.parent)
                        ids = {s['groups'][0]:s['frozen_identity'] for s in candidate['snapshot']['sources']}
                        if candidate['snapshot']['groups'] == groups and ids == {g:snapshot['sources'][g] for g in groups}:
                            item['path'] = str(entry.parent.resolve()); break
                    except (ValueError, OSError, KeyError, TypeError):
                        continue
                if not item['path']:
                    item['path'] = str(create_combination(source, groups).resolve())
                mappings[key] = item['path']; write_json_atomic(path/'items.json', mappings)
            run_combination(item['path'], stop=stop, now=now, started_at=began)
            result = load_combination(item['path'])
            if result['status'] != 'completed':
                report(result['status'], result.get('error', '')); return path
            report('running')
        report('completed')
    return path

class CombinationBatchRun:
    """供應用程式背景執行及停止批次。"""
    def __init__(self, path, executor):
        from threading import Event, Lock
        self.path = Path(path); self._stop = Event(); self._lock = Lock()
        self._state = load_combination_batch(path)
        self.future = executor.submit(self._work)

    def _work(self):
        try:
            run_combination_batch(self.path, stop=self._stop, progress=self._progress)
        except Exception as exc:
            self._progress(dict(status='failed', error=str(exc)))

    def _progress(self, state):
        with self._lock: self._state.update(state)

    def snapshot(self):
        with self._lock: return deepcopy(self._state)

    def stop(self): self._stop.set()
