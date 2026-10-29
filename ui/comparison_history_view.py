"""跨來源比較計畫清單。"""
from pathlib import Path
from engine.learning.comparison import comparison_report
from engine.learning.final_comparison import load_final_comparison

class ComparisonHistoryView:
    def __init__(self):
        self.entries = []
        self.page = 0

    def open(self, root):
        root = Path(root)
        final_paths = set()
        for file in (root / 'data/learning-final').glob('*/snapshot.json'):
            try:
                final_paths.update(Path(entry['path']) for entry in load_final_comparison(file.parent)['candidates'])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.entries = []
        for folder, purpose in [('learning-screening', 'screening'), ('learning-comparisons', 'comparison')]:
            for path in (root / 'data' / folder).glob('*'):
                if not path.is_dir(): continue
                kind = 'final' if path in final_paths else purpose
                try:
                    report = comparison_report(path)
                    source = report['plan']['source']
                    baselines = report['baselines']
                    statuses = [value['status'] for value in baselines.values()]
                    status = 'completed' if all(value == 'completed' for value in statuses) else ('not-started' if all(value == 'not-started' for value in statuses) else 'stopped')
                    self.entries.append(dict(path=path, purpose=kind, source=source, status=status, error=''))
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    self.entries.append(dict(path=path, purpose=kind, source=None, status='invalid', error=str(exc)))
        self.entries.sort(key=lambda row: row['path'].stat().st_mtime, reverse=True)

    def render(self, app):
        labels = {'screening':'快速篩選', 'final':'完整比較', 'comparison':'原始／學習對照'}
        statuses = {'completed':'完成', 'not-started':'未開始', 'stopped':'未完成', 'invalid':'不可用'}
        pages = max(1, (len(self.entries)+5)//6)
        self.page = min(self.page, pages-1)
        app.text('比較紀錄', 50, 78, large=True)
        app.button('learning_history_back', '返回候選', (50, 120, 170, 34))
        if not self.entries: app.text('尚無比較紀錄', 50, 190)
        for i, entry in enumerate(self.entries[self.page*6:self.page*6+6]):
            index = self.page*6+i; source = entry['source']
            name = app.learning.saved_name(entry['path'], labels[entry['purpose']])
            detail = source['experiment_id'][-8:] if source else entry['error']
            app.button('learning_history_open:'+str(index), f'{name} · {labels[entry["purpose"]]} · {statuses[entry["status"]]} · {detail}', (50, 175+i*65, 790, 42))
        app.button('learning_history_prev', '上頁', (50, 620, 130, 34), enabled=self.page>0)
        app.text(f'{self.page+1}/{pages}', 210, 625)
        app.button('learning_history_next', '下頁', (300, 620, 130, 34), enabled=self.page+1<pages)
