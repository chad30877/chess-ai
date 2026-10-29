"""由所選候選預覽篩選與完整比較的共同條件。"""
from copy import deepcopy
from pathlib import Path
from engine.learning.comparison_setup import preview_setup
from engine.learning.group_training import GROUPS


class ComparisonSetupView:
    def __init__(self, root):
        self.root = Path(root)
        self.data_root = None
        self.rows = []
        self.quick = self.final = None
        self.final_error = ''
        self.purpose = 'screening'
        self.page = 0
        self.message = ''

    def open(self, data_root, rows):
        self.data_root = Path(data_root)
        self.rows = deepcopy(rows)
        self.quick = preview_setup(self.root, self.data_root, self.rows, 'screening')
        for row, source in zip(self.rows, self.quick['sources']): row['source'] = deepcopy(source)
        try:
            self.final = preview_setup(self.root, self.data_root, self.rows, 'final')
        except ValueError as exc:
            self.final = None; self.final_error = str(exc)

    def action(self, action, app):
        if action == 'learning_setup_back': app.learning.page = 'inventory'
        elif action in ('learning_setup_screening', 'learning_setup_to_screening'):
            self.purpose = 'screening'; self.message = ''
        elif action == 'learning_setup_final': self.purpose = 'final'; self.message = ''
        elif action == 'learning_setup_next': self.page += 1
        elif action == 'learning_setup_prev': self.page = max(0, self.page - 1)
        elif action == 'learning_setup_start': app.learning.begin_comparison_setup(self, app)

    def render(self, app):
        app.text('比較用途', 50, 78, large=True)
        app.button('learning_setup_back', '返回候選', (50, 120, 170, 34))
        app.button('learning_setup_screening', '快速篩選', (50, 170, 250, 36), primary=self.purpose == 'screening')
        app.button('learning_setup_final', '完整比較', (320, 170, 250, 36), primary=self.purpose == 'final')
        preview = self.quick if self.purpose == 'screening' else self.final
        app.text('stable' if self.purpose == 'screening' else '純子力 ＋ stable', 50, 225, width=790)
        if preview:
            app.text(f'候選 {len(preview["sources"])} 個 · 共 {preview["planned_games"]} 局', 50, 260, width=790)
        pages = max(1, (len(self.rows) + 3) // 4)
        self.page = min(self.page, pages - 1)
        for row, item in enumerate(self.rows[self.page * 4:self.page * 4 + 4]):
            source = item['source']; index = self.page * 4 + row
            status = '' if self.purpose == 'screening' or not self.final else (' · 通過篩選' if self.final['passed'][index] else ' · 尚未通過篩選')
            name = item.get('name', source['experiment_id'][-12:])
            app.text(f'{name} · {"、".join(GROUPS.get(group, group) for group in source["groups"])}{status}', 50, 310 + row * 38, width=790)
        app.button('learning_setup_prev', '上頁', (50, 480, 130, 32), enabled=self.page > 0)
        app.button('learning_setup_next', '下頁', (220, 480, 130, 32), enabled=self.page + 1 < pages)
        ready = self.purpose == 'screening' or bool(self.final and all(self.final['passed']))
        if not ready:
            app.text(self.final_error or '請先完成並通過快速篩選', 50, 540, width=790)
            app.button('learning_setup_to_screening', '前往快速篩選', (50, 580, 230, 36))
        app.button('learning_setup_start', '開始比較', (550, 650, 290, 40), enabled=ready and app.learning.pending_setup is None, primary=True)
        if self.message: app.text(self.message, 50, 710, width=790)
