"""唯讀盤點未完成的學習工作並重建其原始來源。"""
from pathlib import Path

from engine.learning.comparison import comparison_report
from engine.learning.combination_training import load_combination
from engine.learning.combination_batch import load_combination_batch
from engine.learning.dataset import load_dataset
from engine.learning.group_training import load_group_training
from engine.learning.labeling import load_labeling
from engine.learning.training import load_training
from engine.learning.teacher import load_pilot
from ui.group_training_view import GroupTrainingView
from ui.combination_view import CombinationView
from ui.label_view import LabelView
from ui.learned_comparison_view import LearnedComparisonView
from ui.teacher_view import TeacherView
from ui.training_view import TrainingView
from ui.comparison_history_view import ComparisonBundleHistory, _status
from engine.learning.comparison_setup import load_saved_setup


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
            status = _status([report['status'] for report in reports])
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


class RecoveredWork:
    def __init__(self, root):
        self.root = Path(root)
        self.context = {}

    def open(self, item):
        kind, path = item['kind'], Path(item['path'])
        if kind == 'comparison_bundle':
            view = ComparisonBundleHistory(); view.open(path)
            self.context = dict(history_bundle=view)
            return
        if kind == 'comparison':
            view = LearnedComparisonView(self.root)
            view.open_plan(path)
            if item.get('baseline'): view.baseline = item['baseline']
            view.return_page = 'data'
            self.context = dict(comparison=view)
            return
        if kind == 'teacher':
            dataset, label = path.parents[1], None
        elif kind == 'labeling':
            label = path
        elif kind == 'training':
            label = Path(load_training(path)['snapshot']['label_path'])
        elif kind == 'groups':
            label = Path(load_group_training(path)['snapshot']['label_path'])
        elif kind == 'combination':
            saved = load_combination(path)
            label = Path(saved['snapshot']['label_path'])
            source = Path(saved['snapshot']['source_path'])
        else:
            saved = load_combination_batch(path)
            source = Path(saved['snapshot']['source_path'])
            label = source.parents[1]
        if label:
            labeled = load_labeling(label)
            dataset = Path(labeled['snapshot']['dataset_path'])
            pilot = Path(labeled['snapshot']['pilot_path'])
        data = load_dataset(dataset)
        teacher = TeacherView(self.root)
        teacher.open(dataset, path if kind == 'teacher' else pilot)
        if teacher.load_error: raise ValueError(teacher.message)
        self.context = dict(data=data, path=dataset, sample_index=0, teacher=teacher,
                            labels=LabelView(), training=TrainingView(self.root),
                            group_training=GroupTrainingView(self.root), combination=CombinationView(self.root))
        if label:
            labels = LabelView(); labels.dataset = dataset; labels.pilot = pilot
            labels.path = label; labels.state = labeled; labels._entries = labels.entries()
            labels.index = next((i for i, entry in enumerate(labels._entries) if entry.parent == label), 0)
            self.context['labels'] = labels
        if kind == 'training':
            view = TrainingView(self.root); view.open(label, path); self.context['training'] = view
        elif kind == 'groups':
            view = GroupTrainingView(self.root); view.open(label, path); self.context['group_training'] = view
        elif kind in ('combination', 'combination_batch'):
            group = GroupTrainingView(self.root); group.open(label, source)
            if group.load_error: raise ValueError(group.message)
            view = CombinationView(self.root); view.open(source, path if kind == 'combination' else None)
            if kind == 'combination' and view.load_error: raise ValueError(view.message)
            if kind == 'combination_batch':
                view.batch_path, view.batch_state = path, saved
            self.context.update(group_training=group, combination=view)
