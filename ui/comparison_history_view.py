"""跨來源比較計畫清單。"""
from pathlib import Path
from datetime import datetime
import json
from engine.learning.teacher import digest
from engine.learning.comparison import comparison_report
from engine.learning.unfinished import bundle_status


from engine.learning.comparison_setup import load_saved_setup as load_bundle

from engine.learning.final_comparison import load_final_comparison

_status = bundle_status


class ComparisonHistoryView:
    def __init__(self):
        self.entries = []
        self.page = 0

    def open(self, root, selected=None):
        root = Path(root)
        final_paths = set()
        self.entries = []
        for path in (root / 'data/learning-final').glob('*'):
            if not path.is_dir(): continue
            try:
                final_paths.update(Path(entry['path']) for entry in load_final_comparison(path)['candidates'])
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                self.entries.append(dict(path=path, purpose='final', source=None, status='invalid', error=str(exc)))
        for folder, purpose in [('learning-screening', 'screening'), ('learning-comparisons', 'comparison')]:
            for path in (root / 'data' / folder).glob('*'):
                if not path.is_dir(): continue
                kind = 'final' if path in final_paths else purpose
                try:
                    report = comparison_report(path)
                    source = report['plan']['source']
                    baselines = report['baselines']
                    statuses = [value['status'] for value in baselines.values()]
                    status = _status(statuses)
                    self.entries.append(dict(path=path, purpose=kind, source=source, status=status, error=''))
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    self.entries.append(dict(path=path, purpose=kind, source=None, status='invalid', error=str(exc)))
        for path in (root / 'data/learning-setup').glob('*'):
            if not path.is_dir(): continue
            try:
                bundle, reports = load_bundle(path)
                statuses = [item['status'] for item in reports]
                status = _status(statuses)
                self.entries.append(dict(path=path, purpose=bundle['purpose'], source=bundle['sources'][0], status=status, error='', bundle=True))
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                self.entries.append(dict(path=path, purpose='comparison', source=None, status='invalid', error=str(exc), bundle=True))
        if selected and not any(str(row['path']) == selected for row in self.entries):
            path = Path(selected)
            self.entries.append(dict(path=path, purpose='comparison', source=None, status='invalid', error='上次選擇的紀錄已不存在', bundle=path.parent.name == 'learning-setup'))
        def modified(row):
            try: return row['path'].stat().st_mtime
            except OSError: return 0
        self.entries.sort(key=modified, reverse=True)

    def render(self, app):
        labels = {'screening':'快速篩選', 'final':'完整比較', 'comparison':'原始／學習對照'}
        statuses = {'completed':'完成', 'not-started':'未開始', 'stopped':'未完成', 'failed':'失敗', 'running':'執行中', 'invalid':'不可用'}
        pages = max(1, (len(self.entries)+5)//6)
        self.page = min(self.page, pages-1)
        app.text('比較紀錄', 50, 78, large=True)
        app.button('learning_history_back', '返回候選', (50, 120, 170, 34))
        if not self.entries: app.text('尚無比較紀錄', 50, 190)
        for i, entry in enumerate(self.entries[self.page*6:self.page*6+6]):
            index = self.page*6+i; source = entry['source']
            key = str(entry['path'])
            try: date = datetime.fromtimestamp(entry['path'].stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            except OSError:
                date = '日期不明'; entry['status'] = 'invalid'; entry['error'] = '紀錄已不存在'; entry['source'] = source = None
            name = app.learning.saved_state.get('names', {}).get(key, date + ' ' + labels[entry['purpose']])
            if app.learning.saved_state.get('selected', {}).get('comparison_history') == key: name = '✓ ' + name
            detail = source['experiment_id'][-8:] if source else entry['error']
            app.button('learning_history_open:'+str(index), name, (50, 175+i*65, 430, 42))
            app.text(f'{labels[entry["purpose"]]} · {statuses[entry["status"]]} · {detail}', 495, 183+i*65, width=345)
        app.button('learning_history_prev', '上頁', (50, 620, 130, 34), enabled=self.page>0)
        app.text(f'{self.page+1}/{pages}', 210, 625)
        app.button('learning_history_next', '下頁', (300, 620, 130, 34), enabled=self.page+1<pages)


class ComparisonBundleHistory:
    def __init__(self):
        self.path = None; self.data = None; self.reports = []; self.page = 0; self.message = ''
    def open(self, path):
        self.path = Path(path); self.data, self.reports = load_bundle(path)
    def render(self, app):
        app.text('比較紀錄 · ' + ('快速篩選' if self.data['purpose'] == 'screening' else '完整比較'), 50, 78, large=True)
        app.button('learning_bundle_back', '返回紀錄', (50, 120, 180, 34))
        total = self.data['planned_games']
        remaining = sum(row['pending_games'] for report in self.reports for row in report['candidates'])
        app.text(f'已完成 {total-remaining}／{total} 局 · 剩餘 {remaining} 局', 50, 170, width=790)
        pages = max(1, (len(self.data['work'])+4)//5); self.page = min(self.page, pages-1)
        for i, work in enumerate(self.data['work'][self.page*5:self.page*5+5]):
            index = self.page*5+i; report = self.reports[index]
            app.button('learning_bundle_open:'+str(index), f'{index+1}. {Path(work["path"]).name[-8:]} · {work["baseline"]} · {report["status"]}', (50, 220+i*58, 790, 38))
        app.button('learning_bundle_prev', '上頁', (50, 530, 130, 34), enabled=self.page>0)
        app.text(f'{self.page+1}/{pages}', 210, 538)
        app.button('learning_bundle_next', '下頁', (300, 530, 130, 34), enabled=self.page+1<pages)
        app.button('learning_bundle_resume', '開始／續跑比較', (490, 620, 350, 36), enabled=remaining>0, primary=True)
        if self.message: app.text(self.message, 50, 700, width=790)
