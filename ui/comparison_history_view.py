"""跨來源比較計畫清單。"""
from pathlib import Path
from datetime import datetime
import json
from engine.learning.teacher import digest
from engine.learning.comparison import comparison_report


def load_bundle(path):
    path = Path(path)
    data = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    content = dict(data); identity = content.pop("identity", None)
    if data.get("format_version") != 1 or data.get("purpose") not in ("screening", "final") or digest(content) != identity:
        raise ValueError("比較紀錄身份或版本不符")
    work = data["work"]; seen = set(); planned = 0; reports = []
    root = path.parents[2]
    for item in work:
        source_path = Path(item["path"])
        if not source_path.resolve().is_relative_to((root / "data").resolve()): raise ValueError("比較計畫路徑不符")
        key = (str(source_path.resolve()), item["baseline"])
        if key in seen: raise ValueError("比較計畫重複")
        seen.add(key)
        report = comparison_report(source_path); plan = report["plan"]
        if plan["source"] not in data["sources"]: raise ValueError("比較來源不符")
        planned += plan["definitions"][item["baseline"]]["planned_games"]
        reports.append(report["baselines"][item["baseline"]])
    if not work or planned != data["planned_games"]: raise ValueError("比較工作量不符")
    return data, reports
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
        for path in (root / 'data/learning-setup').glob('*'):
            if not path.is_dir(): continue
            try:
                bundle, reports = load_bundle(path)
                statuses = [item['status'] for item in reports]
                status = 'completed' if all(item == 'completed' for item in statuses) else ('not-started' if all(item == 'not-started' for item in statuses) else 'stopped')
                self.entries.append(dict(path=path, purpose=bundle['purpose'], source=bundle['sources'][0], status=status, error='', bundle=True))
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                self.entries.append(dict(path=path, purpose='comparison', source=None, status='invalid', error=str(exc), bundle=True))
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
            key = str(entry['path'])
            date = datetime.fromtimestamp(entry['path'].stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            name = app.learning.saved_state.get('names', {}).get(key, date + ' ' + labels[entry['purpose']])
            detail = source['experiment_id'][-8:] if source else entry['error']
            app.button('learning_history_open:'+str(index), f'{name} · {labels[entry["purpose"]]} · {statuses[entry["status"]]} · {detail}', (50, 175+i*65, 790, 42))
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
