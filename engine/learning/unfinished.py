"""唯讀盤點未完成的學習工作與比較；pygame 與網頁介面共用。"""
from pathlib import Path

from engine.learning.combination_batch import load_combination_batch
from engine.learning.combination_training import load_combination
from engine.learning.comparison import comparison_report
from engine.learning.comparison_setup import load_saved_setup
from engine.learning.group_training import load_group_training
from engine.learning.labeling import load_labeling
from engine.learning.teacher import load_pilot
from engine.learning.training import load_training


def bundle_status(statuses):
    if all(value == 'completed' for value in statuses): return 'completed'
    if any(value == 'failed' for value in statuses): return 'failed'
    if any(value in ('generating', 'running') for value in statuses): return 'running'
    if all(value == 'not-started' for value in statuses): return 'not-started'
    return 'stopped'


def unfinished(root, project):
    root, project = Path(root), Path(project)
    items = []
    loaders = {'teacher': load_pilot, 'labeling': load_labeling, 'training': load_training,
               'groups': load_group_training, 'combination': load_combination, 'combination_batch': load_combination_batch}
    for kind, pattern in (
        ('teacher', '*/teacher-pilots/*'),
        ('labeling', '*/teacher-labels/*'),
        ('groups', '*/teacher-labels/*/group-training/*'),
        ('combination', '*/teacher-labels/*/combinations/*'),
        ('combination_batch', '*/teacher-labels/*/combination-batches/*'),
    ):
        for path in root.glob(pattern):
            try:
                if not path.is_dir() or not ((path / 'snapshot.json').exists() or (path / 'status.json').exists()): continue
                status = loaders[kind](path).get('status', 'interrupted')
                if status not in ('completed',):
                    items.append(dict(kind=kind, path=path, status=status))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                items.append(dict(kind=kind, path=path, status='unavailable'))
    bundled = set()
    for path in (project / 'data/learning-setup').glob('*'):
        if not path.is_dir(): continue
        try:
            bundle, reports = load_saved_setup(path)
            bundled.update((Path(item['path']), item['baseline']) for item in bundle['work'])
            status = bundle_status([report['status'] for report in reports])
            if status != 'completed':
                items.append(dict(kind='comparison_bundle', path=path, status=status))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            items.append(dict(kind='comparison_bundle', path=path, status='unavailable'))
    for folder in ('learning-comparisons', 'learning-screening'):

        for file in (project / 'data' / folder).glob('*/snapshot.json'):
            try:
                report = comparison_report(file.parent)
                for baseline, data in report['baselines'].items():
                    if (file.parent, baseline) not in bundled and data['status'] not in ('completed', 'not-started'):
                        items.append(dict(kind='comparison', path=file.parent, baseline=baseline, status=data['status']))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                items.append(dict(kind='comparison', path=file.parent, baseline=None, status='unavailable'))
    return sorted(items, key=lambda x: str(x['path']))
