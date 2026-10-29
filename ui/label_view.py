"""逐局面標記、手動停止與保存續跑介面。"""
from pathlib import Path
import json
from engine.learning.labeling import LabelRun, create_labeling, load_labeling

SPLITS = {'train': '訓練', 'validation': '驗證', 'test': '測試'}
STAGES = {'opening': '開局', 'middlegame': '中局', 'endgame': '殘局'}
REASONS = {'mate': '將死', 'capture': '吃子', 'promotion': '升變', 'bound_only': '僅上下界',
           'tablebase_score': '殘局庫分數', 'tablebase_hit': '殘局庫命中', 'terminal': '終局', 'in_check': '受將'}


class LabelView:
    def __init__(self):
        self.dataset = self.pilot = self.path = self.run = self._loaded_run = None
        self.state = {}
        self.message = ''
        self.index = 0
        self.advanced = False
        self.loading = None
        self.load_error = False
        self._loading_runtime = None
        self._entries = []

    def active(self):
        return self.run is not None and not self.run.future.done()

    def entries(self):
        if not self.dataset: return []
        return sorted((self.dataset / 'teacher-labels').glob('*/snapshot.json'),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    @staticmethod
    def _read_saved(dataset, path=None, pilot=None):
        entries = sorted((dataset / 'teacher-labels').glob('*/snapshot.json'),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        selected = Path(path) if path is not None else None
        if selected is None:
            for entry in entries:
                try:
                    snapshot = json.loads(entry.read_text(encoding='utf-8'))
                    if pilot and Path(snapshot['pilot_path']).resolve() != Path(pilot).resolve(): continue
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                selected = entry.parent
                break
        try:
            state = load_labeling(selected) if selected else {}
            snapshot = state.get('snapshot')
            if snapshot and pilot and Path(snapshot['pilot_path']).resolve() != Path(pilot).resolve():
                raise ValueError('標記來源與目前教師先導不符')
            return entries, selected, state, None
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            return entries, selected, {}, str(exc)

    def open(self, dataset, pilot, executor, preferred=None):
        self.dataset, self.pilot = Path(dataset), Path(pilot)
        self.path = self.run = self._loaded_run = None
        self.state, self.message, self.index = {}, '', 0
        self._entries = []
        self._loading_runtime = None
        self.loading = executor.submit(self._read_saved, self.dataset, preferred, self.pilot)

    def _poll_loading(self):
        future = self.loading
        if future is None or not future.done(): return
        self.loading = None
        try:
            self._entries, self.path, self.state, error = future.result()
            self.index = next((i for i, entry in enumerate(self._entries) if entry.parent == self.path), 0)
            self.load_error = bool(error)
            self.message = f'無法讀取標記 {self.path}：{error}' if error else ''
            runtime, self._loading_runtime = self._loading_runtime, None
            if runtime and error:
                self.state = runtime
            elif runtime and runtime.get('status') == 'failed':
                self.state['error'] = runtime.get('error', '')
                if not self.state.get('ready'): self.state['status'] = 'failed'
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.state = {}
            self.load_error = True
            self.message = f'無法讀取標記 {self.path or self.dataset}：{exc}'

    def load(self, path):
        self.state = load_labeling(path)
        self.path = Path(path)

    def action(self, action, app):
        try:
            self._poll_loading()
            if action == 'learning_labels_retry':
                self.state = {}
                self.message = ''
                self._loading_runtime = None
                self.loading = app.read_executor.submit(self._read_saved, self.dataset, self.path, self.pilot)
                return
            if self.loading is not None and action not in ('learning_labels_prev', 'learning_labels_next'): return
            if action == 'learning_labels_stop' and self.active():
                self.run.stop()
                return
            if self.active(): return
            if self.load_error and action in ('learning_labels_new', 'learning_labels_resume'): return
            if action == 'learning_labels_new':
                self.path = create_labeling(self.dataset, self.pilot)
                self.run = LabelRun(self.path, app.executor)
                self.index, self.message = 0, ''
            elif action == 'learning_labels_resume' and self.path and not self.state.get('ready'):
                self.run = LabelRun(self.path, app.executor)
                self.message = ''
            elif action == 'learning_labels_advanced': self.advanced = not self.advanced
            elif action in ('learning_labels_prev', 'learning_labels_next'):
                entries = self._entries
                self.index = (self.index + (1 if action.endswith('next') else -1)) % len(entries)
                self.run = self._loaded_run = None
                self.path = entries[self.index].parent
                self.state, self.message = {}, ''
                self._loading_runtime = None
                self.loading = app.read_executor.submit(self._read_saved, self.dataset, self.path, self.pilot)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.message = str(exc)

    def render(self, app):
        self._poll_loading()
        loading = self.loading is not None
        active = self.active()
        if self.run:
            if active: self.state = self.run.snapshot()
            elif self._loaded_run is not self.run:
                self._loading_runtime = self.run.snapshot()
                self.state = self._loading_runtime
                self.loading = app.read_executor.submit(self._read_saved, self.dataset, self.run.path, self.pilot)
                self._loaded_run = self.run
                loading = True
        state = self.state
        app.text('學習實驗 · 教師標記', 50, 78, large=True)
        app.button('learning_data', '資料', (50, 122, 130, 34))
        app.button('learning_teacher', '教師先導', (195, 122, 190, 34))
        app.button('learning_training', '棋子位置學習', (400, 122, 200, 34), enabled=bool(state.get('ready')) and not active and not loading)
        app.button('learning_groups', '五個單群組', (620, 122, 220, 34), enabled=state.get('ready',False) and not active and not loading)
        app.button('learning_labels_new', '建立新標記', (50, 178, 230, 36), enabled=not active and not loading and not self.load_error, primary=True)
        app.button('learning_labels_resume', '續跑／重試', (300, 178, 230, 36), enabled=bool(self.path) and not state.get('ready') and not active and not loading and not self.load_error)
        app.button('learning_labels_stop', '停止', (550, 178, 130, 36), enabled=active)
        statuses = {'queued': '排隊', 'running': '標記中', 'completed': '標記完成', 'stopped': '已停止', 'failed': '失敗', 'interrupted': '未完成', 'ready': '待開始'}
        if state:
            status = state['status']
            if status in ('queued', 'running') and not active: status = 'interrupted'
            app.text(f'{statuses.get(status, status)} · 已完成 {state["completed"]}/{state["total"]} · 剩餘 {state["remaining"]} · 失敗／待重試 {state["failed"]}', 50, 238, width=790)
            app.text(f'{state.get("elapsed_seconds", 0):.1f} 秒 · 每次最多八小時 · 手動續跑', 50, 270, muted=True, width=790)
        if loading: app.text('載入已保存標記…', 50, 306, width=790)
        elif self.message or state.get('error'):
            app.text(self.message or state['error'], 50, 306, width=570)
            if self.load_error: app.button('learning_labels_retry', '重新讀取', (650, 300, 150, 34))
        summary = state.get('summary')
        if summary:
            app.text(f'有效 {summary["valid"]} · 排除 {summary["excluded"]} · 重用先導 {summary["reused_pilot"]} · 來源不足 {summary["shortfall_games"]} 盤', 50, 350, width=790)
            for index, (split, title) in enumerate(SPLITS.items()):
                group = summary['splits'][split]
                stages = ' / '.join(f'{label} {group["stages"].get(stage, 0)}' for stage, label in STAGES.items())
                app.text(f'{title}：{group["games"]} 盤 / {group["positions"]} 有效局面　{stages}', 50, 388 + index * 30, width=790)
            reasons = summary['reasons']
            for row, keys in enumerate((('mate', 'capture', 'promotion', 'bound_only'), ('tablebase_score', 'tablebase_hit', 'terminal', 'in_check'))):
                app.text(' · '.join(f'{REASONS[k]} {reasons.get(k, 0)}' for k in keys), 50, 490 + row * 28, muted=True, width=790)
        app.button('learning_labels_advanced', '收起進階條件' if self.advanced else '進階條件', (50, 552, 230, 34))
        snapshot = state.get('snapshot')
        if self.advanced and snapshot:
            app.text(f'固定 {snapshot["nodes"]:,} 節點 · {snapshot.get("workers", 1)} 程序 · 篩選 v{snapshot["filter_version"]} · SHA256 {snapshot["teacher"]["executable_sha256"][:16]}…', 50, 597, width=790)
            data = summary['data_exclusions']
            app.text('資料排除：' + ' · '.join(f'{label} {data.get(key, 0)}' for key, label in (('first_8_plies', '前八手'), ('in_check', '受將'), ('terminal', '終局'))), 50, 628, muted=True, width=790)
            app.text(f'抽樣上限 {data.get("not_sampled", 0)} · 跨組重複 {data.get("cross_split_duplicate", 0)} · 同組重複 {data.get("within_split_duplicate", 0)}', 50, 657, muted=True, width=790)
        entries = self._entries
        app.text(f'已保存標記 {min(self.index + 1, len(entries))}/{len(entries)}', 50, 700)
        app.button('learning_labels_prev', '上一份', (455, 690, 160, 34), enabled=len(entries) > 1 and not active)
        app.button('learning_labels_next', '下一份', (640, 690, 160, 34), enabled=len(entries) > 1 and not active)
