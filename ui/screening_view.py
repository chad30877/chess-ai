"""候選短對局的明確選擇、保存及結果。"""
import json
from ui.report_refresh import ReportRefresh
from pathlib import Path
from engine.learning.comparison import comparison_options
from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
from engine.learning.screening import create_screening, load_screening, screening_report
from engine.learning.teacher import digest
from engine.sessions.comparison_run import ComparisonRun
from engine.storage.batch_storage import write_json_atomic


class ScreeningView:
    def __init__(self, root):
        self.root = Path(root)
        self.path = None
        self.report = None
        self.message = ''
        self.refresh = ReportRefresh()
        self.selection_path = None
        self.selected = []
        self.final_path = None
        self.final_index = 0

    def open(self, candidate, source_identity):
        self.message = ''
        self.selection_path = self.root / 'data/learning-screening' / ('selection-' + source_identity + '.json')
        self.selected = json.loads(self.selection_path.read_text(encoding='utf-8')) if self.selection_path.exists() else []
        pointer = self.selection_path.with_name(self.selection_path.stem + '-final.json')
        self.final_path = Path(json.loads(pointer.read_text(encoding='utf-8'))['path']) if pointer.exists() else None
        self.final_index = 0
        self.path = None
        for file in sorted((self.root / 'data/learning-screening').glob('*/snapshot.json')):
            try:
                if digest(load_screening(file.parent)['source']) == digest(candidate):
                    self.path = file.parent
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if self.path is None:
            self.path = create_screening(self.root, candidate)
        self.report = screening_report(self.path)

    def action(self, action, app):
        try:
            if self.refresh.error and action != 'learning_screening_back': return
            if action == 'learning_screening_back':
                app.learning.page = 'inventory'
            elif action == 'learning_screening_final_freeze':
                self.final_path = freeze_final_comparison(self.root, self.selected)
                write_json_atomic(self.selection_path.with_name(self.selection_path.stem + '-final.json'), {'path': str(self.final_path)})
                self.final_index = 0
            elif action == 'learning_screening_final_next':
                self.final_index += 1
            elif action == 'learning_screening_final_open':
                final = load_final_comparison(self.final_path)
                entry = final['candidates'][self.final_index % len(final['candidates'])]
                app.learning.comparison.open(entry['source'])
                app.learning.comparison.open_plan(entry['path'])
                rows = app.learning.comparison.report['baselines']['material']['candidates']
                app.learning.comparison.candidate = next(i for i, row in enumerate(rows) if row['role'] == 'learned')
                app.learning.comparison.return_page = 'screening'
                app.learning.page = 'comparison'
            elif action == 'learning_screening_start':
                if app.batch and not app.batch.future.done():
                    raise ValueError('請先停止目前批次')
                app.batch = ComparisonRun(comparison_options(self.path, 'stable'), app.executor)
                app.batch_mode = 'evaluation'; app.mode = 'auto'; app.batch_games_page = 0
                app.learning.batch_return_page = 'screening'
            elif action == 'learning_screening_select':
                source = self.report['plan']['source']
                identity = digest(source['config'])
                existing = next((i for i, item in enumerate(self.selected) if digest(item['config']) == identity), None)
                if existing is not None:
                    self.selected.pop(existing)
                elif not self.report['complete'] or self.report['eliminated']:
                    raise ValueError('僅能選定通過篩選的候選')
                elif len(self.selected) < 5:
                    self.selected.append(source)
                else:
                    raise ValueError('最多選擇五個候選')
                write_json_atomic(self.selection_path, self.selected)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.message = str(exc)

    def render(self, app):
        refreshed = self.refresh.poll(self.path, screening_report, app.executor)
        if refreshed is not None:
            report, error = refreshed
            if error: self.message = f'無法讀取 {self.path}：{error}'
            else: self.report, self.message = report, ''
        result = self.report
        app.text('候選短對局篩選', 50, 78, large=True)
        app.button('learning_screening_back', '返回候選', (50, 120, 170, 34))
        if self.refresh.error:
            app.text(self.message, 50, 185, width=790)
            return
        app.text('stable · 八條共同開局 · 換色共 16 局', 50, 185, width=790)
        app.text('Alpha-Beta 3／q4 · 同時 4 局 · 每局 1 worker · TT 4096', 50, 220, width=790)
        app.text(f'狀態 {result["status"]} · 有效 {result["games"]}/16 局', 50, 260, width=790)
        app.text(f'{result["wins"]} 勝 · {result["draws"]} 和 · {result["losses"]} 敗 · 得分 {result["score"]:g}', 50, 300, width=790)
        app.text('暫估棋力：'+(f'{result["rating"]:.0f}' if result['rating'] is not None else '尚無完整配對'), 50, 340, width=790)
        app.text('篩選：'+('未完成' if result['eliminated'] is None else '淘汰' if result['eliminated'] else '通過'), 50, 380, width=790)
        active = app.batch is not None and not app.batch.future.done()
        app.button('learning_screening_start', '開始／續跑短對局', (50, 435, 290, 40), enabled=not active and not result['complete'], primary=True)
        identity = digest(result['plan']['source']['config'])
        is_selected = any(digest(item['config']) == identity for item in self.selected)
        app.button('learning_screening_select', ('取消選定' if is_selected else '選定作完整比較候選') + f' · {len(self.selected)}/5', (50, 500, 390, 40), enabled=is_selected or (result['complete'] and not result['eliminated']))
        app.button('learning_screening_final_freeze', '凍結完整比較候選', (50, 550, 280, 36), enabled=bool(self.selected))
        if self.final_path:
            final = load_final_comparison(self.final_path)
            self.final_index %= len(final['candidates'])
            app.button('learning_screening_final_next', f'候選 {self.final_index + 1}/{len(final["candidates"])}', (350, 550, 170, 36))
            app.button('learning_screening_final_open', '預覽雙基準比較', (540, 550, 260, 36))
        app.text(self.message or '候選由研究者決定；不會自動啟動完整比較。', 50, 610, width=790)
        app.button('learning_screening_heldout','最終教師評估',(50, 660, 280, 36),enabled=bool(self.final_path))
