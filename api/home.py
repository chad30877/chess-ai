"""首頁資料：未完成工作、最近研究與對局紀錄。啟動時背景掃描並快取，工作結束後重新掃描。"""
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock

from engine.learning.unfinished import unfinished
from engine.replay.records_catalog import RecordsCatalog

RECENT_LIMIT = 5

KIND_LABELS = {
    'teacher': '教師先導',
    'labeling': '教師標記',
    'training': '棋子位置學習',
    'groups': '評分權重學習',
    'combination': '組合訓練',
    'combination_batch': '組合批次',
    'comparison_bundle': '整組比較',
    'comparison': '學習比較',
}

STATUS_LABELS = {
    'running': '執行中',
    'stopped': '已停止',
    'interrupted': '已中斷',
    'failed': '失敗',
    'unavailable': '無法讀取',
    'partial': '部分完成',
    'not-started': '未開始',
}

RECORD_KINDS = {'batch': '一般批次', 'comparison': '評分比較', 'comparison_unavailable': '評分比較', 'standalone': '非批次'}


def _names(project_root):
    try:
        data = json.loads((Path(project_root) / 'data/learning-ui.json').read_text(encoding='utf-8'))
        return data.get('names', {}) if isinstance(data.get('names'), dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _resumable(data_root, project_root, names):
    items = []
    for item in unfinished(Path(data_root) / 'learning', project_root):
        path = str(item['path'])
        label = KIND_LABELS.get(item['kind'], item['kind'])
        items.append(dict(kind=item['kind'], kind_label=label, id=Path(path).name,
                          status=item['status'], status_label=STATUS_LABELS.get(item['status'], item['status']),
                          name=names.get(path) or f'{label} {Path(path).name[:8]}', path=path,
                          baseline=item.get('baseline')))
    return items


def _recent_research(data_root, names):
    datasets = []
    for file in (Path(data_root) / 'learning').glob('*/dataset.json'):
        try:
            datasets.append((file.stat().st_mtime, file.parent))
        except OSError:
            continue
    datasets.sort(reverse=True)
    result = []
    for mtime, path in datasets[:RECENT_LIMIT]:
        result.append(dict(name=names.get(str(path)) or f'資料 {path.name[:8]}', id=path.name, path=str(path),
                           updated_at=datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds')))
    return result


def _recent_records(data_root):
    result = []
    for entry in RecordsCatalog(Path(data_root)).entries[:RECENT_LIMIT]:
        counts = entry.counts
        result.append(dict(key=entry.key, batch_id=entry.batch_id, name=entry.name,
                           kind=entry.kind, kind_label=RECORD_KINDS.get(entry.kind, entry.kind),
                           status=entry.status, created_at=entry.created_at, games=len(entry.games),
                           unfinished=counts['unfinished'] + counts['unknown'], error=entry.error))
    return result


class HomeCache:
    def __init__(self, executor, *, data_root, project_root):
        self._executor = executor
        self._data_root = Path(data_root)
        self._project_root = Path(project_root)
        self._lock = Lock()
        self._state = dict(status='scanning', resumable=[], recent_research=[], recent_records=[],
                           scanned_at=None, error='')
        self._pending = None
        self._again = False

    def refresh(self):
        """排入背景重新掃描；掃描中再呼叫只會在結束後再掃一次。"""
        with self._lock:
            if self._pending is not None and not self._pending.done():
                self._again = True
                return self._pending
            self._again = False
            self._state['status'] = 'scanning'
            self._pending = self._executor.submit(self._scan)
            return self._pending

    def _scan(self):
        try:
            names = _names(self._project_root)
            state = dict(resumable=_resumable(self._data_root, self._project_root, names),
                         recent_research=_recent_research(self._data_root, names),
                         recent_records=_recent_records(self._data_root), error='', status='ready')
        except Exception as exc:  # 掃描失敗不影響其他頁面，保留上次結果並顯示原因。
            state = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
        state['scanned_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self._lock:
            self._state.update(state)
            again = self._again
            self._pending = None
        if again:
            self.refresh()

    def snapshot(self):
        with self._lock:
            return dict(self._state)
