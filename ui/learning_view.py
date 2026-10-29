"""學習實驗的資料來源、背景處理與保存預覽。"""

import json
from copy import copy, deepcopy
from datetime import datetime
from pathlib import Path
from engine.storage.batch_storage import write_json_atomic

import pygame

from engine.learning.dataset import DatasetRun, SOURCE_URL, load_dataset
from ui.teacher_view import TeacherView
from ui.label_view import LabelView
from ui.training_view import TrainingView
from ui.group_training_view import GroupTrainingView
from ui.learned_comparison_view import LearnedComparisonView
from ui.combination_view import CombinationView
from ui.candidate_inventory_view import InventoryView
from ui.screening_view import ScreeningView
from ui.heldout_view import HeldoutView
from ui.comparison_setup_view import ComparisonSetupView
from ui.comparison_history_view import ComparisonHistoryView, ComparisonBundleHistory
from ui.controls import ui_font
from ui.unfinished_tasks import unfinished, RecoveredWork

SPLIT_LABELS = {'train': '訓練', 'validation': '驗證', 'test': '測試'}
STAGE_LABELS = {'opening': '開局', 'middlegame': '中局', 'endgame': '殘局'}
START_ACTIONS = {'learning_create', 'learning_pilot_start', 'learning_labels_new', 'learning_labels_recreate', 'learning_labels_resume',
                 'learning_training_new', 'learning_training_resume', 'learning_groups_new', 'learning_groups_resume',
                 'learning_combination_new', 'learning_combination_resume', 'learning_combination_batch', 'learning_combination_batch_resume',
                 'learning_compare_start', 'learning_screening_start', 'learning_setup_start', 'learning_bundle_resume'}

EXCLUSION_LABELS = {'first_8_plies': '前八手', 'terminal': '終局', 'in_check': '受將',
                    'not_sampled': '抽樣上限', 'cross_split_duplicate': '跨組重複',
                    'within_split_duplicate': '同組重複'}


class _PendingComparison:
    def __init__(self, executor, root, data_root, rows, purpose):
        from engine.learning.comparison_setup import freeze_setup
        self.data_root = Path(data_root)
        self.root = Path(root)
        self.purpose = purpose
        self.rows = deepcopy(rows)
        self.future = executor.submit(freeze_setup, root, data_root, self.rows, purpose)
        self.cancelled = False
        self.error = ''
    def stop(self): self.cancelled = True
    def snapshot(self):
        return dict(status='failed' if self.error else 'stopping' if self.cancelled else 'running',
                    completed=0, total=0, error=self.error)


class _SavedGroupResults:
    def __init__(self): self.entries, self.page = [], 0
    def open(self, root):
        self.entries = sorted(root.glob('*/teacher-labels/*/group-training/*/snapshot.json'), reverse=True)


class _LabelChoices:
    def __init__(self): self.entries, self.page = [], 0
    def open(self, root):
        for file in sorted(Path(root).glob('*/teacher-labels/*/snapshot.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                snapshot = json.loads(file.read_text(encoding='utf-8'))
                status = json.loads((file.parent / 'status.json').read_text(encoding='utf-8')).get('status', 'interrupted')
                self.entries.append(dict(path=file.parent, snapshot=snapshot, status=status))
            except (OSError, ValueError, KeyError): continue


class _SelectedTeacher:
    def __init__(self, root): self.root = root
    def open(self, path, run=None):
        labels = LabelView()
        labels.load(path)
        labels.dataset = Path(labels.state['snapshot']['dataset_path'])
        labels.pilot = Path(labels.state['snapshot']['pilot_path'])
        labels._entries = labels.entries()
        labels.run = run
        self.navigation_labels = labels
        self.navigation_teacher = TeacherView(self.root)
        self.navigation_teacher.open(labels.dataset, labels.pilot)
        self.navigation_data = load_dataset(labels.dataset)


class _SelectedLabels(GroupTrainingView):
    def open(self, path, selections):
        source = _SelectedTeacher(self.root)
        source.open(path)
        if not source.navigation_labels.state.get('ready'): raise ValueError('這份教師評分尚未完成')
        self.navigation_labels = source.navigation_labels
        self.navigation_teacher = source.navigation_teacher
        self.navigation_data = source.navigation_data
        super().open(path, selections.get(f'groups:{path}'))


class _LearningContent:
    """將既有頁面壓入共用導覽下方，保持按鈕與文字對齊。"""
    def __init__(self, app):
        self.app = app
        if getattr(app, '_learning_font_scale', None) != app.scale:
            app._learning_fonts = (ui_font(round(15 * app.scale)), ui_font(round(23 * app.scale)))
            app._learning_font_scale = app.scale
    def __getattr__(self, name): return getattr(self.app, name)
    def text(self, value, x, y, **kwargs):
        app = self.app
        old = app.font, app.title_font
        app.font, app.title_font = app._learning_fonts
        try: app.text(value, x, 170 + (y - 74) * .84, **kwargs)
        finally: app.font, app.title_font = old
    def button(self, action, label, rect, **kwargs):
        x, y, w, h = rect
        app = self.app
        if action in ('learning_groups_new', 'learning_groups_resume') and app.learning.browse_result:
            kwargs['enabled'] = False
        old = app.font
        app.font = app._learning_fonts[0]
        try: app.button(action, label, (x, 170 + (y - 74) * .84, w, h * .84), **kwargs)
        finally: app.font = old


class LearningView:
    def __init__(self, root):
        self.root = Path(root) / 'data/learning'
        self.source = 'lichess'
        self.local_path = ''
        self.seed = '2026'
        self.focus = None
        self.draft = ''
        self.run = None
        self._loaded_run = None
        self.data = None
        self.path = None
        self.message = ''
        self.sample_index = 0
        self.recent_page = 0
        self.page = 'home'
        self.teacher = TeacherView(root)
        self.labels = LabelView()
        self.training = TrainingView(root)
        self.group_training = GroupTrainingView(root)
        self.comparison = LearnedComparisonView(root)
        self.combination = CombinationView(root)
        self.inventory = InventoryView()
        self.comparison_history = ComparisonHistoryView()
        self.history_bundle = ComparisonBundleHistory()
        self.batch_history_bundle = None
        self.screening = ScreeningView(root)
        self.heldout = HeldoutView(root)
        self.batch_return_page = 'comparison'
        self.batch_comparison = None
        self.replay_comparison = None
        self.setup = ComparisonSetupView(root)
        self.batch_setup = None
        self.pending_setup = None
        self.failed_setup = None
        self.inventory_return = 'groups'
        self.result_browser = _SavedGroupResults()
        self.browse_result = False
        self.loading = None
        self.loading_path = None
        self.page_loading = None
        self.page_load_error = ''
        self.page_load_request = None
        self._detached_task = None
        self._task_context = None
        self.background_contexts = []
        self.recovery_future = None
        self.recovery_error = ''
        self.recovery_entries = []
        self.recovery_list = False
        self.recovery_page = 0
        self.saved_list = False
        self.saved_entries = []
        self.saved_page = 0
        self.saved_kind = 'data'
        self.rename_focus = False
        self.rename_draft = ''
        self.rename_target = None
        self.label_choices = _LabelChoices()
        self.label_choice_purpose = 'training'
        self.saved_state_path = Path(root) / 'data/learning-ui.json'
        try:
            self.saved_state = json.loads(self.saved_state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            self.saved_state = {}
        for key in ('source', 'local_path', 'seed'):
            setattr(self, key, self.saved_state.get('source_options', {}).get(key, getattr(self, key)))

    def _saved_context(self):
        if self.page in ('home', 'data'): return 'data', self, [p.parent for p in self.entries()], '資料'
        if self.page == 'teacher': return f'teacher:{self.path}', self.teacher, [p.parent for p in self.teacher.entries()], '教師先導'
        if self.page == 'labeling': return f'labeling:{self.path}:{self.teacher.path}', self.labels, [p.parent for p in self.labels._entries], '教師標記'
        if self.page == 'training': return f'training:{self.labels.path}', self.training, [p.parent for p in self.training.entries], '棋子位置學習'
        if self.page == 'groups': return f'groups:{self.group_training.labels}', self.group_training, [p.parent for p in self.group_training.entries], '評分權重學習'
        if self.page == 'combination': return f'combination:{self.group_training.path}', self.combination, [p.parent for p in self.combination.entries], '組合'
        return None

    def _current_saved_path(self):
        if self.rename_focus and self.rename_target is not None: return self.rename_target
        if self.page == 'history_bundle': return self.history_bundle.path
        if self.page == 'comparison' and self.comparison.return_page in ('history', 'history_bundle'): return self.comparison.path
        context = self._saved_context()
        return context[1].path if context else None

    def saved_name(self, path, purpose):
        if purpose in ('教師評分', '教師標記'):
            return self.saved_state.get('names', {}).get(str(Path(path)), '教師 ' + Path(path).name[-8:])
        date = self.saved_state.get('created', {}).get(str(Path(path)), '日期不明')
        return self.saved_state.get('names', {}).get(str(Path(path)), f'{date} {purpose}')

    def _saved_label(self, path):
        try:
            status = json.loads((path / 'status.json').read_text(encoding='utf-8')).get('status', '未完成')
            status = {'completed': '完成', 'ready': '待開始', 'running': '未完成', 'queued': '未完成',
                      'stopped': '已停止', 'failed': '失敗', 'interrupted': '未完成'}.get(status, status)
        except (OSError, ValueError, TypeError):
            status = '不可用'
        date = self.saved_state.get('created', {}).get(str(Path(path)), '日期不明')
        return f'{date} · {path.parent.parent.name[-5:]}/{path.name[-8:]} · {status}'

    def _save_ui_state(self):
        self.saved_state_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.saved_state_path, self.saved_state)

    def _remember(self, key, path):
        self.saved_state.setdefault('selected', {})[str(key)] = str(Path(path))
        self._save_ui_state()

    def _remember_new(self, key, path):
        self.saved_state.setdefault('created', {}).setdefault(str(Path(path)), datetime.now().strftime('%Y/%m/%d'))
        self._remember(key, path)

    def scan_unfinished(self, executor):
        self.recovery_error = ''
        self.recovery_future = executor.submit(unfinished, self.root, self.teacher.project_root)

    def poll_unfinished(self):
        if self.recovery_future is not None and self.recovery_future.done():
            future, self.recovery_future = self.recovery_future, None
            try: self.recovery_entries = future.result()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.recovery_entries = []
                self.recovery_error = f'無法查找未完成工作：{exc}'

    def restore(self, executor):
        path = self.saved_state.get('selected', {}).get('data')
        if path and self.path is None and self.loading is None and not self.active_task():
            self._open_async(Path(path), executor)

    def open_comparison(self, candidate, executor=None, origin=None, path=None):
        row = dict(source=candidate, origin=origin, path=str(path)) if origin and path else None
        if executor is None:
            if row: self.comparison.open_selected(self.root, row)
            else: self.comparison.open(candidate)
            if self.page in ('groups', 'combination', 'training'): self.comparison.return_page = self.page
            self.page = 'comparison'
        else:
            self._open_page('comparison', 'comparison', lambda: LearnedComparisonView(self.teacher.project_root),
                            (self.root, row) if row else candidate, self.page, executor,
                            'open_selected' if row else 'open')

    def active(self):
        return self.active_task() is not None

    def running_labels(self, path):
        runs = [self.labels.run, *(task[2] for task, _ in self.background_contexts if task[0] == 'labeling')]
        return next((run for run in runs if run and run.path == Path(path) and not run.future.done()), None)

    def active_task(self):
        if self.pending_setup is not None:
            return 'setup', '比較準備', self.pending_setup
        if self._detached_task and not self._detached_task[2].future.done():
            return self._detached_task
        for task, context in self.background_contexts:
            if not task[2].future.done(): return task
        for page, label, view in (('data', '資料準備', self), ('teacher', '教師先導', self.teacher),
                                  ('labeling', '教師標記', self.labels), ('training', '棋子位置學習', self.training),
                                  ('groups', '單群組學習', self.group_training), ('combination', '組合學習', self.combination)):
            run = view.run
            if run is not None and not run.future.done():
                return page, label, run
        return None

    def failed_task(self):
        for task, context in self.background_contexts:
            if task[2].future.done() and task[2].snapshot().get('status') == 'failed': return task
        if self.failed_setup is not None:
            return 'setup', '比較準備', self.failed_setup
        if self._detached_task and self._detached_task[2].future.done() and self._detached_task[2].snapshot().get('status') == 'failed':
            return self._detached_task
        for page, label, view in (('data', '資料準備', self), ('teacher', '教師先導', self.teacher),
                                  ('labeling', '教師標記', self.labels), ('training', '棋子位置學習', self.training),
                                  ('groups', '單群組學習', self.group_training), ('combination', '組合學習', self.combination)):
            run = view.run
            if run is not None and run.future.done() and run.snapshot().get('status') == 'failed':
                return page, label, run
        return None

    def close(self, wait=False):
        if self.pending_setup is not None:
            self.pending_setup.stop()
            if wait:
                try: self.pending_setup.future.result()
                except Exception: pass
        detached = self._detached_task[2] if self._detached_task else None
        for run in (detached, *(task[2] for task, _ in self.background_contexts), self.run, self.teacher.run, self.labels.run, self.training.run, self.group_training.run, self.combination.run):
            if run and not run.future.done():
                run.stop()
                if wait:
                    run.future.result()

    def begin_comparison_setup(self, view, app):
        if self.pending_setup or (app.batch and not app.batch.future.done()):
            view.message = '請先停止目前工作'
            return
        self.failed_setup = None
        self.pending_setup = _PendingComparison(app.read_executor, view.root, view.data_root,
                                                view.rows, view.purpose)
        self.pending_setup.view = view
        view.message = '驗證候選並準備比較…'

    def poll_comparison_setup(self, app):
        pending = self.pending_setup
        if pending is None or not pending.future.done(): return
        self.pending_setup = None
        if pending.cancelled:
            pending.view.message = '已停止準備'
            return
        try:
            setup = pending.future.result()
            from engine.learning.comparison_setup import ComparisonBundleRun
            app.batch = ComparisonBundleRun(setup['work'], setup['planned_games'], app.executor,
                                            data_root=pending.data_root, rows=pending.rows,
                                            project_root=pending.root, purpose=pending.purpose)
            app.learning_batch = app.batch; app.batch_mode = 'evaluation'; app.batch_games_page = 0
            self.batch_return_page = 'setup'
            self.batch_setup = pending.view
            pending.view.message = ''
            if app.mode == 'learning' and self.page == 'setup': app.mode = 'auto'
        except Exception as exc:
            pending.error = str(exc)
            pending.view.message = f'無法準備比較：{exc}'
            self.failed_setup = pending

    def commit(self):
        if self.focus == 'path':
            self.local_path = self.draft.strip().strip('"')
        elif self.focus == 'seed':
            try:
                int(self.draft)
            except ValueError:
                self.message = '種子須為整數'
                return False
            self.seed = self.draft
        self.focus = None
        self._save_source_options()
        pygame.key.stop_text_input()
        return True

    def _save_source_options(self):
        self.saved_state['source_options'] = dict(source=self.source, local_path=self.local_path, seed=self.seed)
        self._save_ui_state()

    def pick_source(self):
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        try:
            window.attributes('-topmost', True)
            chosen = filedialog.askopenfilename(parent=window, title='選擇棋譜檔案',
                initialdir=str(Path(self.local_path).parent if self.local_path else self.root.parents[1]),
                filetypes=[('棋譜與壓縮檔', '*.pgn *.zst *.gz *.bz2'), ('所有檔案', '*')])
            if chosen:
                self.local_path = str(Path(chosen).resolve())
                self.source = 'local'
                self._save_source_options()
        finally:
            window.destroy()

    def input(self, event):
        if self.page == 'inventory' and self.inventory.report and self.inventory.report.get('all_sources'):
            handled = self.inventory.input(event)
            if handled:
                try: self.saved_state = json.loads(self.saved_state_path.read_text(encoding='utf-8'))
                except (OSError, ValueError): pass
                return True
        if self.rename_focus and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            if event.type == pygame.TEXTINPUT: self.rename_draft += event.text
            elif event.key == pygame.K_BACKSPACE: self.rename_draft = self.rename_draft[:-1]
            elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL: self.rename_draft = ''
            elif event.key == pygame.K_RETURN:
                if self.rename_draft.strip():
                    self.saved_state.setdefault('names', {})[str(self._current_saved_path())] = self.rename_draft.strip()
                    self._save_ui_state()
                self.rename_focus = False; pygame.key.stop_text_input()
            elif event.key == pygame.K_ESCAPE:
                self.rename_focus = False; pygame.key.stop_text_input()
            return True
        if self.page in ('teacher', 'labeling'):
            return self.teacher.input(event)
        if self.focus is None or event.type not in (pygame.TEXTINPUT, pygame.KEYDOWN):
            return False
        if event.type == pygame.TEXTINPUT:
            self.draft += event.text
        elif event.key == pygame.K_BACKSPACE:
            self.draft = self.draft[:-1]
        elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
            self.draft = ''
        elif event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
            try:
                pygame.scrap.init()
                clipboard = pygame.scrap.get(pygame.SCRAP_TEXT)
                if clipboard:
                    self.draft += clipboard.decode('utf-8').rstrip('\x00')
            except (pygame.error, UnicodeError):
                self.message = '無法貼上，請輸入路徑'
        elif event.key == pygame.K_RETURN:
            self.commit()
        elif event.key == pygame.K_ESCAPE:
            self.focus = None
            pygame.key.stop_text_input()
        return True

    def entries(self):
        return sorted(self.root.glob('*/status.json'), key=lambda p: p.stat().st_mtime, reverse=True)

    def _preserve_task_context(self):
        self._preserve_browsing_context()

    def _preserve_browsing_context(self):
        # 同一次切換保留完整來源組合；連未執行中的相依檢視也複製，避免改寫背景工作的來源。
        views = (('teacher', '教師評分', 'teacher'), ('labeling', '教師標記', 'labels'),
                 ('groups', '評分權重學習', 'group_training'), ('combination', '組合學習', 'combination'))
        active = [(page, label, getattr(self, attribute).run) for page, label, attribute in views
                  if getattr(self, attribute).active()]
        if not active: return
        keys = ('data', 'path', 'sample_index', 'teacher', 'labels', 'group_training', 'combination', 'browse_result')
        context = {key: getattr(self, key) for key in keys}
        for task in active:
            if not any(existing[0][2] is task[2] for existing in self.background_contexts):
                self.background_contexts.append((task, dict(context)))
        for _, _, attribute in views:
            view = getattr(self, attribute)
            replacement = copy(view)
            replacement.state = copy(view.state)
            if view.active(): replacement.run = replacement._loaded_run = None
            setattr(self, attribute, replacement)

    def open(self, path):
        self.loading = None
        self._preserve_task_context()
        self.data = load_dataset(path)
        self.path = Path(path)
        self.sample_index = 0
        self.message = ''
        preferred = self.saved_state.get('selected', {}).get(f'teacher:{Path(path)}')
        self.teacher.open(path, preferred)

    @staticmethod
    def _read_dataset(path, root, preferred):
        try:
            data = load_dataset(path)
            teacher = TeacherView(root)
            teacher.open(path, preferred)
            return data, teacher, None
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            return None, None, str(exc)

    def _open_async(self, path, executor):
        self._preserve_task_context()
        self.loading_path = Path(path)
        self.path = self.loading_path
        self.data = None
        self.message = ''
        preferred = self.saved_state.get('selected', {}).get(f'teacher:{self.loading_path}')
        self.loading = executor.submit(self._read_dataset, self.loading_path, self.teacher.project_root, preferred)

    def _poll_loading(self):
        if self.loading is None or not self.loading.done(): return
        future, self.loading = self.loading, None
        try:
            data, teacher, error = future.result()
            if error: raise ValueError(error)
            self.data, self.teacher = data, teacher
            self.path = self.loading_path
            self.sample_index = 0
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.data = None
            self.message = f'無法開啟資料 {self.loading_path}：{exc}'

    @staticmethod
    def _read_page(factory, path, method):
        try:
            view = factory()
            args = path if isinstance(path, tuple) else (path,)
            getattr(view, method)(*args)
            return view, None
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            return None, str(exc)

    def _open_page(self, page, attribute, factory, path, back, executor, method='open'):
        self.page = page
        self.page_load_error = ''
        self.page_load_request = (page, attribute, factory, path, back, method)
        self.page_loading = executor.submit(self._read_page, factory, path, method)

    def _poll_page(self):
        if self.page_loading is None or not self.page_loading.done(): return
        future, self.page_loading = self.page_loading, None
        view, error = future.result()
        if error:
            source = self.page_load_request[3]
            if isinstance(source, tuple):
                source = next((item for item in source if isinstance(item, dict) and 'path' in item), source[0])
            if isinstance(source, dict): source = source.get('path', source.get('experiment_id', '成果'))
            self.page_load_error = f'無法讀取 {source}：{error}'
        else:
            if self.page_load_request[1] == 'recovery':
                for key, value in view.context.items(): setattr(self, key, value)
                if view.context.get('data') is not None:
                    selected = self.saved_state.setdefault('selected', {})
                    selected['data'] = str(self.path)
                    if self.teacher.path:
                        selected[f'teacher:{self.path}'] = str(self.teacher.path)
                    if self.labels.path:
                        selected[f'labeling:{self.path}:{self.teacher.path}'] = str(self.labels.path)
                    context = self._saved_context()
                    item = self.page_load_request[3]
                    if item.get('new_draft'):
                        self.browse_result = False
                        self.group_training.action('learning_groups_draft', None)
                    if item['kind'] == 'combination_batch':
                        selected[f'groups:{self.labels.path}'] = str(self.group_training.path)
                    elif context and context[1].path:
                        selected[context[0]] = str(context[1].path)
                    self._save_ui_state()
            else:
                if self.page_load_request[1] == 'comparison' and self.page_load_request[4] in ('groups', 'combination', 'training', 'history_bundle'):
                    view.return_page = self.page_load_request[4]
                setattr(self, self.page_load_request[1], view)
                if hasattr(view, 'navigation_labels'):
                    self.labels = view.navigation_labels
                    self.path = self.labels.dataset
                    self.teacher = view.navigation_teacher
                    self.data = view.navigation_data
                    self.sample_index = 0
                    if self.labels.run:
                        self.background_contexts = [item for item in self.background_contexts if item[0][2] is not self.labels.run]
            self.page_load_request = None

    def _labels_current(self):
        return self.path is not None and self.labels.dataset == self.path

    def _navigate(self, page, app):
        self.saved_list = False
        self.recovery_list = False
        self.page_loading = self.page_load_request = None
        self.page_load_error = ''
        if page in ('home', 'data'):
            self.page = page
        elif page == 'teacher':
            self.page = 'teacher'
            if (self.path and self.teacher.path and self.teacher.state.get('choice') and not self.labels.active()
                    and not (self._labels_current() and (self.labels.path or self.labels.loading))):
                key = f'labeling:{self.path}:{self.teacher.path}'
                self.labels.open(self.path, self.teacher.path, app.read_executor, self.saved_state.get('selected', {}).get(key))
        elif page == 'labeling':
            if self.path and self.teacher.path and self.teacher.state.get('choice'):
                if not self.labels.active() and not (self._labels_current() and (self.labels.path or self.labels.loading)):
                    self._preserve_browsing_context()
                    key = f'labeling:{self.path}:{self.teacher.path}'
                    self.labels.open(self.path, self.teacher.path, app.read_executor, self.saved_state.get('selected', {}).get(key))
            self.page = 'labeling'
        elif page == 'groups':
            if self.group_training.labels:
                self.page = 'groups'
                return
            if not self.group_training.labels:
                self.label_choice_purpose = 'training'
                self._open_page('label_choices', 'label_choices', _LabelChoices, self.root, 'home', app.read_executor)
                return
        elif page == 'results':
            self._open_page('results', 'result_browser', _SavedGroupResults, self.root, 'home', app.read_executor)
        elif page == 'inventory':
            self.inventory_return = 'groups'
            self._open_page('inventory', 'inventory', InventoryView, self.root, 'data', app.read_executor, 'open_first')

    def _render_navigation(self, app):
        for x, action, title in ((25, 'data', '資料準備'), (240, 'teacher', '教師評分'),
                                  (455, 'groups', '評分權重學習'), (670, 'inventory', '比較候選')):
            app.button('learning_nav_' + action, title, (x, 60, 205, 30))
        parents = {'teacher': ('teacher', '教師評分'), 'labeling': ('teacher', '教師評分'),
                   'groups': ('groups', '評分權重學習'), 'results': ('groups', '評分權重學習'), 'training': ('groups', '評分權重學習'),
                   'combination': ('groups', '評分權重學習'), 'inventory': ('inventory', '比較候選'),
                   'screening': ('inventory', '比較候選'), 'history': ('inventory', '比較候選'), 'history_bundle': ('inventory', '比較候選'), 'setup': ('inventory', '比較候選'), 'comparison': ('inventory', '比較候選'),
                   'heldout': ('inventory', '比較候選')}
        app.button('learning_breadcrumb_data', '學習實驗', (25, 98, 120, 27))
        if self.page in parents:
            parent, label = parents[self.page]
            app.button('learning_breadcrumb_' + parent, label, (160, 98, 190, 27))
        titles = {'home':'首頁', 'data':'資料準備', 'teacher':'教師評分', 'labeling':'教師評分', 'training':'棋子位置學習',
                  'groups':'評分權重學習', 'results':'學習成果', 'combination':'組合', 'inventory':'候選清單',
                  'screening':'快速篩選', 'history':'比較紀錄', 'history_bundle':'比較紀錄', 'setup':'比較用途', 'comparison':'比較', 'heldout':'教師誤差評估'}
        app.text('› ' + titles.get(self.page, ''), 365 if self.page in parents else 160, 101, width=260)
        if self.path:
            teacher = ('完成' if self.teacher.state.get('choice') else '未完成') if self.teacher.dataset == self.path and self.teacher.loading is None else '尚未載入'
            labels = ('完成' if self.labels.state.get('ready') else '未完成') if self._labels_current() and self.labels.loading is None else '尚未載入'
            group = '尚未載入'
            if self._labels_current() and self.labels.path and self.group_training.labels == self.labels.path:
                group = '完成' if self.group_training.state.get('status') == 'completed' else '未完成'
            app.text(f'資料 {self.path.name[-8:]} · 教師先導 {teacher} · 教師標記 {labels} · 學習 {group}', 25, 135, width=850)

    def action(self, action, app):
        if action in ('learning_teacher', 'learning_labels'):
            self._navigate('teacher', app)
            return
        if action in ('learning_choose_training_labels', 'learning_teacher_select_labels'):
            self.label_choice_purpose = 'training' if action == 'learning_choose_training_labels' else 'teacher'
            self._open_page('label_choices', 'label_choices', _LabelChoices, self.root, self.page, app.read_executor)
            return
        if action == 'learning_teacher_rename_labels' and self.labels.path:
            self.rename_target = self.labels.path
            self.rename_draft = self.saved_name(self.labels.path, '教師評分')
            self.rename_focus = True
            pygame.key.start_text_input()
            return
        if action.startswith('learning_label_choice:'):
            entry = self.label_choices.entries[int(action.split(':')[1])]
            path = entry['path']
            dataset = Path(entry['snapshot']['dataset_path'])
            pilot = Path(entry['snapshot']['pilot_path'])
            self._remember('data', dataset)
            self._remember(f'teacher:{dataset}', pilot)
            self._remember(f'labeling:{dataset}:{pilot}', path)
            running_labels = self.running_labels(path)
            self._preserve_browsing_context()
            if self.label_choice_purpose == 'training':
                self.browse_result = False
                self._open_page('groups', 'group_training', lambda: _SelectedLabels(self.teacher.project_root),
                                (path, self.saved_state.get('selected', {})), 'label_choices', app.read_executor)
            else:
                self._open_page('teacher', 'teacher_selection', lambda: _SelectedTeacher(self.teacher.project_root),
                                (path, running_labels), 'label_choices', app.read_executor)
            return
        if action in ('learning_label_choices_next', 'learning_label_choices_prev'):
            self.label_choices.page = max(0, self.label_choices.page + (1 if action.endswith('next') else -1))
            return
        if action.startswith('learning_training'):
            self._navigate('inventory', app)
            return
        routes = {'learning_nav_data':'data', 'learning_nav_teacher':'teacher', 'learning_nav_groups':'groups',
                  'learning_nav_inventory':'inventory', 'learning_breadcrumb_data':'home',
                  'learning_goal_create':'data', 'learning_goal_resume':'groups',
                  'learning_goal_compare':'inventory', 'learning_goal_results':'results',
                  'learning_breadcrumb_teacher':'teacher', 'learning_breadcrumb_groups':'groups',
                  'learning_breadcrumb_inventory':'inventory', 'learning_need_data':'data',
                  'learning_need_teacher':'teacher', 'learning_need_labels':'labeling', 'learning_need_groups':'groups'}
        if action in routes:
            self._navigate(routes[action], app)
            return
        if self.recovery_list and action not in ('learning_task_return', 'learning_task_stop'):
            if action == 'learning_recovery_back': self.recovery_list = False
            elif action == 'learning_recovery_retry': self.scan_unfinished(app._scan_executor)
            elif action == 'learning_recovery_next': self.recovery_page += 1
            elif action == 'learning_recovery_prev': self.recovery_page = max(0, self.recovery_page - 1)
            elif action.startswith('learning_recovery_open:'):
                if self.active_task() or (app.batch and not app.batch.future.done()): return
                item = self.recovery_entries[int(action.split(':')[1])]
                self.loading = None
                self.recovery_list = False
                self._open_page({'combination_batch': 'combination', 'comparison_bundle': 'history_bundle'}.get(item['kind'], item['kind']), 'recovery', lambda: RecoveredWork(self.teacher.project_root), item, 'data', app.read_executor)
            return
        if action == 'learning_recovery_list':
            if self.active_task() or (app.batch and not app.batch.future.done()): return
            self.saved_list = False
            if self.rename_focus:
                self.rename_focus = False; pygame.key.stop_text_input()
            self.recovery_list = True; self.recovery_page = 0
            return
        if self.page == 'home' and not action.startswith('learning_task_'):
            self.page = 'data'

        if self.saved_list and action not in ('learning_task_return', 'learning_task_stop'):
            if action == 'learning_saved_back': self.saved_list = False
            elif action == 'learning_saved_next': self.saved_page += 1
            elif action == 'learning_saved_prev': self.saved_page = max(0, self.saved_page - 1)
            elif action.startswith('learning_saved_select:'):
                path = self.saved_entries[int(action.split(':')[1])]
                context = self._saved_context()
                if context is None: return
                key, view, entries, purpose = context
                if (view is self and self.run and not self.run.future.done()) or (view is not self and view.active()): return
                self.saved_list = False
                if self.page != 'data':
                    self._preserve_browsing_context()
                    key, view, entries, purpose = self._saved_context()
                self._remember(key, path)
                if self.page == 'data':
                    self._open_async(path, app.read_executor)
                elif self.page == 'teacher':
                    view.index = entries.index(path); view.path = path; view.state = {}; view.message = ''
                    view.loading = app.read_executor.submit(view._read_pilot, path)
                elif self.page == 'labeling':
                    view.index = entries.index(path); view.path = path; view.state = {}; view.message = ''
                    view._loading_runtime = None
                    view.loading = app.read_executor.submit(view._read_saved, view.dataset, path, view.pilot)
                else:
                    attribute = {'training':'training', 'groups':'group_training', 'combination':'combination'}[self.page]
                    index = entries.index(path)
                    def selected_view():
                        selected = copy(view); selected.index = index
                        selected.run = selected._loaded_run = None
                        return selected
                    self._open_page(self.page, attribute, selected_view, path, self.page, app.read_executor, 'load')
            return
        if action == 'learning_saved_list':
            if self.page == 'data' and self.run and not self.run.future.done(): return
            context = self._saved_context()
            if context:
                self.saved_kind = context[3]; self.saved_entries = context[2]
                self.saved_page = 0; self.saved_list = True
            return
        if action == 'learning_saved_rename':
            self.rename_target = None
            context = self._saved_context()
            path = self._current_saved_path()
            if path and (context or self.page in ('history_bundle', 'comparison')):
                self.rename_draft = self.saved_name(path, context[3] if context else '比較紀錄')
                self.rename_focus = True; pygame.key.start_text_input()
            return
        task = self.active_task()
        if self.teacher.active() and action.startswith('learning_budget:'):
            self.teacher.message = f'目前執行中：{task[1]}，請先停止或等待完成'
            return
        if action in START_ACTIONS:
            batch = getattr(app, 'batch', None)
            view = {'teacher': self.teacher, 'labeling': self.labels, 'groups': self.group_training,
                    'combination': self.combination}.get(self.page)
            if action.startswith('learning_labels_'): view = self.labels
            running = ('此作業' if view and view.active() else
                       '比較' if action in ('learning_setup_start', 'learning_compare_start', 'learning_screening_start', 'learning_bundle_resume') and batch and not batch.future.done() else None)
            if running:
                view = {'teacher': self.teacher, 'labeling': self.labels, 'training': self.training,
                        'groups': self.group_training, 'combination': self.combination,
                        'comparison': self.comparison, 'screening': self.screening}.get(self.page, self)
                view.message = f'目前執行中：{running}，請先停止或等待完成'
                return
        if action in START_ACTIONS and (self.page_load_request is not None or self.loading is not None):
            return
        if action in ('learning_groups_new', 'learning_groups_resume') and self.group_training.labels is None:
            self.group_training.message = '請先選擇完成的教師評分'
            return
        if action in ('learning_training_new', 'learning_training_resume') and self.training.labels != self.labels.path:
            self.training.message = '請先載入對應教師標記'
            return
        if action in ('learning_training_new', 'learning_training_resume') and (self.labels.loading is not None or not self.labels.state.get('ready')):
            self.message = '請先完成對應教師標記'
            return
        if action == 'learning_pilot_start' and (not self.data or self.teacher.dataset != self.path or self.teacher.loading is not None or self.teacher.load_error):
            self.teacher.message = '請先選擇有效資料'
            return
        if action in ('learning_labels_new', 'learning_labels_recreate') and (not self.teacher.state.get('choice') or self.labels.loading is not None):
            self.labels.message = '請先選定對應教師先導'
            return
        if action.startswith(('learning_labels_', 'learning_pilot_', 'learning_budget:', 'learning_engine', 'learning_teacher_')) and self.page in ('teacher', 'labeling'):
            if action.startswith('learning_labels_'):
                if action in ('learning_labels_new', 'learning_labels_recreate'):
                    self.labels.dataset, self.labels.pilot = self.teacher.dataset, self.teacher.path
                self.labels.action(action, app)
                if self.labels.path: self._remember_new(f'labeling:{self.labels.dataset}:{self.labels.pilot}', self.labels.path)
            else:
                self.teacher.action(action, app)
                if self.teacher.run: self._remember_new(f'teacher:{self.teacher.dataset}', self.teacher.run.path)
            return
        if self.browse_result and action == 'learning_groups_draft':
            self.loading = self.loading_path = None
            item = dict(kind='groups', path=self.group_training.path, new_draft=True)
            self._open_page('groups', 'recovery', lambda: RecoveredWork(self.teacher.project_root), item, 'groups', app.read_executor)
            return
        if self.browse_result and action in ('learning_groups_new', 'learning_groups_resume'):
            self.group_training.message = '請先選擇對應教師標記'
            return
        if action == 'learning_task_return' and (task or self.failed_task()):
            target = task or self.failed_task()
            background = next((item for item in self.background_contexts if item[0][2] is target[2]), None)
            if background:
                self._preserve_browsing_context()
                self.background_contexts.remove(background)
                for key, value in background[1].items(): setattr(self, key, value)
            if target[0] == 'setup': self.setup = target[2].view
            if self._task_context and target is self._detached_task:
                for key, value in self._task_context.items(): setattr(self, key, value)
                self._task_context = self._detached_task = None
            self.saved_list = False
            self.recovery_list = False
            self.page_loading = self.page_load_request = None
            self.loading = None
            self.page_load_error = ''
            self.page = target[0]
            return
        if action == 'learning_task_stop' and task:
            task[2].stop()
            return
        if self.page_load_request is not None:
            if action == 'learning_loading_back':
                self.page = self.page_load_request[4]
                self.page_loading = self.page_load_request = None
                self.page_load_error = ''
            elif action == 'learning_loading_retry' and self.page_loading is None:
                page, attribute, factory, path, back, method = self.page_load_request
                self._open_page(page, attribute, factory, path, back, app.read_executor, method)
            return
        selected_pages = {'training': ('training', 'learning_training_'),
                          'groups': ('group_training', 'learning_groups_'),
                          'combination': ('combination', 'learning_combination_')}
        if self.page in selected_pages:
            attribute, prefix = selected_pages[self.page]
            if action in (prefix + 'prev', prefix + 'next'):
                current = getattr(self, attribute)
                if current.active() or not current.entries: return
                index = (current.index + (1 if action.endswith('next') else -1)) % len(current.entries)
                entry = current.entries[index]
                path = entry.parent
                self._remember(self._saved_context()[0], path)
                def selected_view():
                    view = copy(current)
                    view.index = index
                    view.run = view._loaded_run = None
                    return view
                self._open_page(self.page, attribute, selected_view, path, self.page, app.read_executor, 'load')
                return
        if self.page == 'results':
            if action in ('learning_results_prev', 'learning_results_next'):
                self.result_browser.page = max(0, self.result_browser.page + (1 if action.endswith('next') else -1))
            elif action.startswith('learning_results_open:'):
                index = int(action.split(':')[1])
                path = self.result_browser.entries[index].parent
                self._preserve_browsing_context()
                self.browse_result = True
                self._open_page('groups', 'group_training', lambda: GroupTrainingView(self.teacher.project_root),
                                (path.parents[1], path), 'results', app.read_executor)
            return
        if self.page == 'inventory':
            if action == 'learning_inventory_back': self.page = self.inventory_return
            elif action == 'learning_inventory_history':
                self._open_page('history', 'comparison_history', ComparisonHistoryView, (self.teacher.project_root, self.saved_state.get('selected', {}).get('comparison_history')), 'inventory', app.read_executor)
            elif action == 'learning_inventory_setup' and self.inventory.report.get('all_sources'):
                rows = [self.inventory.report['candidates'][i] for i in sorted(self.inventory.selected_indices)]
                if not rows: return
                self._open_page('setup', 'setup', lambda: ComparisonSetupView(self.teacher.project_root),
                                (self.root, rows), 'inventory', app.read_executor)
            elif action == 'learning_inventory_compare' and self.inventory.report.get('all_sources'):
                if len(self.inventory.selected_indices) != 1: return
                selected = self.inventory.report['candidates'][self.inventory.selected]
                self._open_page('comparison', 'comparison', lambda: LearnedComparisonView(self.teacher.project_root),
                                (self.root, selected), 'inventory', app.read_executor, 'open_selected')
            elif action == 'learning_inventory_screen':
                if self.inventory.report.get('all_sources') and len(self.inventory.selected_indices) != 1:
                    return
                try:
                    selected = self.inventory.report['candidates'][self.inventory.selected]
                    self._open_page('screening', 'screening', lambda: ScreeningView(self.teacher.project_root),
                                    (selected['source'], self.inventory.report.get('source_identity', selected['source']['snapshot_identity'])), 'inventory', app.read_executor)
                except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                    self.combination.message = str(exc)
            else: self.inventory.action(action, app)
            return
        if self.page == 'heldout':
            self.heldout.action(action, app)
            return
        if self.page == 'history':
            if action == 'learning_history_back': self.page = 'inventory'
            elif action == 'learning_history_prev': self.comparison_history.page = max(0, self.comparison_history.page - 1)
            elif action == 'learning_history_next': self.comparison_history.page += 1
            elif action.startswith('learning_history_open:'):
                entry = self.comparison_history.entries[int(action.split(':')[1])]
                self._remember('comparison_history', entry['path'])
                if entry.get('bundle'):
                    self._open_page('history_bundle', 'history_bundle', ComparisonBundleHistory, entry['path'], 'history', app.read_executor)
                else:
                    self._open_page('comparison', 'comparison', lambda: LearnedComparisonView(self.teacher.project_root), entry['path'], 'history', app.read_executor, 'open_history')
            return
        if self.page == 'history_bundle':
            if action == 'learning_bundle_back': self.page = 'history'
            elif action == 'learning_bundle_prev': self.history_bundle.page = max(0, self.history_bundle.page-1)
            elif action == 'learning_bundle_next': self.history_bundle.page += 1
            elif action.startswith('learning_bundle_open:'):
                work = self.history_bundle.data['work'][int(action.split(':')[1])]
                self._open_page('comparison', 'comparison', lambda: LearnedComparisonView(self.teacher.project_root), (work['path'], work['baseline']), 'history_bundle', app.read_executor, 'open_history')
            elif action == 'learning_bundle_resume':
                from engine.learning.comparison_setup import ComparisonBundleRun
                data = self.history_bundle.data
                app.batch = ComparisonBundleRun(data['work'], data['planned_games'], app.executor, bundle_path=self.history_bundle.path)
                app.learning_batch = app.batch; app.batch_mode = 'evaluation'; app.mode = 'auto'; app.batch_games_page = 0
                self.batch_return_page = 'history_bundle'
                self.batch_history_bundle = self.history_bundle
            return
        if self.page == 'screening':
            if action == 'learning_screening_heldout':
                try:
                    self._open_page('heldout', 'heldout', lambda: HeldoutView(self.teacher.project_root), self.screening.final_path, 'screening', app.read_executor)
                except (OSError, ValueError, KeyError, TypeError) as exc: self.screening.message = str(exc)
                return
            self.screening.action(action, app)
            return
        if action == 'learning_inventory' and self.page == 'combination':
            try:
                self.inventory_return = 'combination'
                self._open_page('inventory', 'inventory', InventoryView, self.combination.source_path, 'combination', app.read_executor)
            except (OSError, ValueError, KeyError) as exc: self.combination.message = str(exc)
            return
        if self.page == 'comparison' and action in ('learning_compare_prev_plan', 'learning_compare_next_plan'):
            current = self.comparison
            if not current.entries: return
            index = (current.index + (1 if action.endswith('next_plan') else -1)) % len(current.entries)
            def selected_comparison():
                view = copy(current)
                view.index = index
                return view
            self._open_page('comparison', 'comparison', selected_comparison, current.entries[index],
                            'comparison', app.read_executor, 'open_plan')
            return
        if self.page == 'setup':
            self.setup.action(action, app)
            return
        if self.page == 'comparison':
            self.comparison.action(action,app)
            return
        if action == 'learning_combinations' and self.group_training.path:
            try:
                if self.combination.active(): self.page = 'combination'
                else: self._open_page('combination', 'combination', lambda: CombinationView(self.teacher.project_root), (self.group_training.path, self.saved_state.get('selected', {}).get(f'combination:{self.group_training.path}')), 'groups', app.read_executor)
            except (OSError,ValueError,KeyError) as exc: self.group_training.message = str(exc)
            return
        if action == 'learning_groups' and self.labels.path and self.labels.loading is None and self.labels.state.get('ready'):
            try:
                if self.group_training.active(): self.page = 'groups'
                else: self._open_page('groups', 'group_training', lambda: GroupTrainingView(self.teacher.project_root), (self.labels.path, self.saved_state.get('selected', {}).get(f'groups:{self.labels.path}')), 'labeling', app.read_executor)
            except (OSError,ValueError,KeyError) as exc: self.labels.message = str(exc)
            return
        if self.page == 'combination':
            previous = self.combination.run
            self.combination.action(action,app)
            if action == 'learning_combination_new' and self.combination.run is not previous and self.combination.run:
                self._remember_new(self._saved_context()[0], self.combination.run.path)
            return
        if self.page == 'groups':
            previous = self.group_training.run
            self.group_training.action(action,app)
            if action == 'learning_groups_new' and self.group_training.run is not previous and self.group_training.run:
                self._remember_new(self._saved_context()[0], self.group_training.run.path)
            return
        if self.loading is not None and not action.startswith('learning_open:'):
            return
        if not self.commit():
            return
        try:
            if action == 'learning_stop' and self.run and not self.run.future.done():
                self.run.stop()
                return
            if self.run and not self.run.future.done() and not (action in ('learning_teacher', 'learning_prev', 'learning_next', 'learning_sample', 'learning_recent_prev', 'learning_recent_next') or action.startswith('learning_open:')):
                return
            if action == 'learning_source':
                self.source = 'local' if self.source == 'lichess' else 'lichess'
                self._save_source_options()
            elif action == 'learning_source_pick':
                self.pick_source()
            elif action == 'learning_seed_random':
                from time import time_ns
                self.seed = str(max(time_ns() // 1_000_000, int(self.seed) + 1))
                self._save_source_options()
            elif action.startswith('learning_field:'):
                self.focus = action.split(':')[1]
                self.draft = self.local_path if self.focus == 'path' else self.seed
                pygame.key.start_text_input()
            elif action == 'learning_create':
                source = SOURCE_URL if self.source == 'lichess' else self.local_path
                if not source:
                    raise ValueError('請輸入本機 PGN 路徑')
                self.run = DatasetRun(self.root, source, int(self.seed), app.executor)
                self._remember_new('data', self.run.path)
                self.data = None
                self.message = ''
            elif action == 'learning_teacher' and self.path and self.data is not None:
                self.page = 'teacher'
            elif action.startswith('learning_open:'):
                path = self.entries()[int(action.split(':')[1])].parent
                self._remember('data', path)
                if (path / 'dataset.json').exists():
                    self._open_async(path, app.read_executor)
                else:
                    self._preserve_task_context()
                    self.loading = None
                    self.path = path
                    self.data = None
                    self.run = None
                    saved = json.loads((path / 'status.json').read_text(encoding='utf-8'))
                    self.message = f'{path}：' + saved.get('error', '資料尚未完成或不可用；請建立新實驗重試')
            elif action in ('learning_prev', 'learning_next') and self.data:
                self.sample_index = (self.sample_index + (1 if action.endswith('next') else -1)) % max(1, len(self.data['positions']))
            elif action in ('learning_recent_prev', 'learning_recent_next'):
                self.recent_page = max(0, self.recent_page + (1 if action.endswith('next') else -1))
            elif action == 'learning_sample' and self.data and self.data['positions']:
                sample = self.data['positions'][self.sample_index]
                app._set_replay(dict(initial_fen=sample['initial_fen'], moves_uci=sample['moves_uci'],
                                     result='*', metadata={'name': '學習局面', 'game_id': sample['game_id']}), '學習資料預覽')
                app.replay.goto_ply(len(sample['moves_uci']))
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            self.message = f'無法開啟資料 {self.path or self.root}：{exc}'

    def render(self, app):
        self._render_navigation(app)
        app = _LearningContent(app)
        self._poll_loading()
        self._poll_page()
        self.poll_unfinished()
        if self.recovery_list:
            app.text('未完成工作', 50, 78, large=True)
            app.button('learning_recovery_back', '返回', (50, 122, 130, 34))
            if self.recovery_error:
                app.text(self.recovery_error, 50, 180, width=790)
                app.button('learning_recovery_retry', '重新讀取', (50, 230, 180, 34))
                return
            if self.recovery_future is not None:
                app.text('載入未完成工作…', 50, 180, width=790)
                return
            pages = max(1, (len(self.recovery_entries) + 7) // 8)
            self.recovery_page = min(self.recovery_page, pages - 1)
            titles = {'teacher':'教師評分', 'labeling':'教師評分', 'training':'棋子位置學習', 'groups':'評分權重學習', 'combination':'組合', 'combination_batch':'組合批次', 'comparison':'比較', 'comparison_bundle':'整組比較'}
            for row, item in enumerate(self.recovery_entries[self.recovery_page * 8:self.recovery_page * 8 + 8]):
                name = self.saved_name(item['path'], titles[item['kind']])
                app.button(f'learning_recovery_open:{self.recovery_page * 8 + row}', name, (50, 180 + row * 50, 485, 40))
                statuses = {'ready':'待開始', 'queued':'未完成', 'running':'未完成', 'stopped':'已停止', 'failed':'失敗', 'interrupted':'未完成', 'unavailable':'不可用', 'generating':'未完成', 'partial':'部分失敗', 'not-started':'待開始'}
                status = statuses.get(item['status'], item['status'])
                if item['kind'] == 'teacher': status += ' · 需重新量測'
                baseline = {'material': '純子力', 'stable': 'stable'}.get(item.get('baseline'), '')
                app.text(item['path'].name[-8:] + (' · ' + baseline if baseline else '') + ' · ' + status, 550, 190 + row * 50, muted=True, width=290)
            app.button('learning_recovery_prev', '上頁', (50, 615, 150, 34), enabled=self.recovery_page > 0)
            app.button('learning_recovery_next', '下頁', (220, 615, 150, 34), enabled=self.recovery_page < pages - 1)
            return
        if self.saved_list:
            app.text('選擇' + self.saved_kind, 50, 78, large=True)
            app.button('learning_saved_back', '返回', (50, 122, 130, 34))
            pages = max(1, (len(self.saved_entries) + 7) // 8)
            self.saved_page = min(self.saved_page, pages - 1)
            for row, path in enumerate(self.saved_entries[self.saved_page * 8:self.saved_page * 8 + 8]):
                app.button(f'learning_saved_select:{self.saved_page * 8 + row}', self.saved_name(path, self.saved_kind), (50, 180 + row * 50, 485, 40))
                app.text(self._saved_label(path), 550, 190 + row * 50, muted=True, width=290)
            app.button('learning_saved_prev', '上頁', (50, 615, 150, 34), enabled=self.saved_page > 0)
            app.button('learning_saved_next', '下頁', (220, 615, 150, 34), enabled=self.saved_page < pages - 1)
            return
        if self.page_load_request is not None:
            app.text('學習實驗', 50, 78, large=True)
            app.button('learning_loading_back', '返回', (50, 122, 130, 34))
            app.text(self.page_load_error or '載入已保存成果…', 50, 190, width=790)
            if self.page_load_error: app.button('learning_loading_retry', '重新讀取', (50, 240, 180, 34))
            return
        if self.page == 'home':
            app.text('學習實驗', 50, 78, large=True)
            app.button('learning_goal_create', '建立新實驗', (50, 160, 370, 46), primary=True)
            app.button('learning_goal_resume', '接續學習', (470, 160, 370, 46))
            app.button('learning_goal_compare', '比較候選', (50, 230, 370, 46))
            app.button('learning_goal_results', '查看學習成果', (470, 230, 370, 46))
            if self.loading is not None: app.text('載入已選資料…', 50, 320)
            elif self.path: app.text('目前資料：' + self.saved_name(self.path, '資料'), 50, 320, width=790)
            return
        context = self._saved_context()
        if context and self.page not in ('home', 'data', 'teacher', 'labeling'):
            app.button('learning_saved_list', '選擇成果', (360, 74, 130, 36), enabled=not context[1].active())
            app.button('learning_saved_rename', self.rename_draft + ' |' if self.rename_focus else '重新命名', (500, 74, 140, 36), enabled=self._current_saved_path() is not None)
        if self.page == 'label_choices':
            app.text('選擇教師評分', 50, 78, large=True)
            entries = self.label_choices.entries
            pages = max(1, (len(entries) + 7) // 8)
            self.label_choices.page = min(self.label_choices.page, pages - 1)
            for row, entry in enumerate(entries[self.label_choices.page * 8:self.label_choices.page * 8 + 8]):
                index = self.label_choices.page * 8 + row
                title = self.saved_name(entry['path'], '教師評分')
                state = {'completed':'完成', 'running':'執行中', 'failed':'失敗', 'stopped':'已停止', 'ready':'待開始'}.get(entry['status'], '待續跑')
                app.button(f'learning_label_choice:{index}', f'{title} · {state} · {entry["snapshot"]["nodes"]:,} 節點',
                           (50, 140 + row * 55, 790, 40),
                           enabled=self.label_choice_purpose != 'training' or entry['status'] == 'completed')
            if not entries: app.text('尚無教師評分', 50, 150)
            app.button('learning_label_choices_prev', '上頁', (50, 620, 150, 34), enabled=self.label_choices.page > 0)
            app.button('learning_label_choices_next', '下頁', (220, 620, 150, 34), enabled=self.label_choices.page + 1 < pages)
            return
        if self.page == 'results':
            entries = self.result_browser.entries
            pages = max(1, (len(entries) + 7) // 8)
            self.result_browser.page = min(self.result_browser.page, pages - 1)
            app.text('學習成果', 50, 78, large=True)
            if not entries: app.text('尚無學習成果', 50, 150)
            for row, entry in enumerate(entries[self.result_browser.page * 8:self.result_browser.page * 8 + 8]):
                index = self.result_browser.page * 8 + row
                app.button(f'learning_results_open:{index}', self.saved_name(entry.parent, '單群組學習') + ' · ' + self._saved_label(entry.parent), (50, 140 + row * 55, 790, 40))
            app.button('learning_results_prev', '上頁', (50, 620, 150, 34), enabled=self.result_browser.page > 0)
            app.button('learning_results_next', '下頁', (220, 620, 150, 34), enabled=self.result_browser.page + 1 < pages)
            return
        if self.page == 'inventory':
            if not self.inventory.report:
                app.text('尚無可用候選', 50, 78, large=True)
                app.button('learning_need_groups', '前往評分權重學習', (50, 140, 250, 36))
                return
            self.inventory.render(app)
            return
        if self.page == 'history_bundle':
            app.button('learning_saved_rename', self.rename_draft + ' |' if self.rename_focus else '重新命名', (500, 74, 140, 36), enabled=self.history_bundle.path is not None)
            self.history_bundle.render(app)
            return
        if self.page == 'history':
            self.comparison_history.render(app)
            return
        if self.page == 'heldout':
            self.heldout.render(app)
            return
        if self.page == 'screening':
            self.screening.render(app)
            return
        if self.page == 'setup':
            self.setup.render(app)
            return
        if self.page == 'comparison':
            if self.comparison.return_page in ('history', 'history_bundle'):
                app.button('learning_saved_rename', self.rename_draft + ' |' if self.rename_focus else '重新命名', (500, 74, 140, 36), enabled=self.comparison.path is not None)
            self.comparison.render(app)
            return
        if self.page == 'combination':
            self.combination.render(app)
            return
        if self.page == 'groups':
            app.button('learning_choose_training_labels', '選擇教師評分', (260, 120, 250, 32))
            if not self.browse_result and not self.group_training.labels:
                app.text('教師標記尚未完成', 50, 78, large=True)
                app.button('learning_need_labels', '前往接續標記', (50, 140, 230, 36))
                return
            self.group_training.render(app)
            return
        if self.page == 'training':
            app.text('此頁已移除，請使用比較候選', 50, 78)
            return
        if self.page in ('teacher', 'labeling'):
            from ui.teacher_workspace import render_teacher
            render_teacher(self, app)
            return
        active = bool(self.run and not self.run.future.done())
        app.text('學習實驗' if self.page == 'home' else '學習實驗 · 資料準備', 50, 78, large=True)
        app.button('learning_saved_list', '選擇資料', (340, 74, 140, 36), enabled=not (self.run and not self.run.future.done()))
        app.button('learning_saved_rename', self.rename_draft + ' |' if self.rename_focus else '重新命名', (490, 74, 150, 36), enabled=self.path is not None)
        app.button('learning_teacher', '教師評分', (650, 74, 190, 36), enabled=self.data is not None)
        app.button('learning_source', 'Lichess 2013-01 · CC0' if self.source == 'lichess' else '本機棋譜（授權自查）',
                   (50, 125, 470, 36), enabled=not active)
        if self.source == 'local':
            value = self.draft + ' |' if self.focus == 'path' else self.local_path or '輸入／貼上 .pgn、.zst、.gz、.bz2 路徑'
            app.button('learning_field:path', value, (50, 172, 620, 36), enabled=not active)
            app.button('learning_source_pick', '選擇檔案', (685, 172, 155, 36), enabled=not active)
        else:
            app.text(SOURCE_URL, 50, 178, muted=True, width=790)
        app.button('learning_field:seed', '種子：' + (self.draft + ' |' if self.focus == 'seed' else self.seed),
                   (50, 220, 270, 36), enabled=not active)
        app.button('learning_seed_random', '隨機', (335, 220, 100, 36), enabled=not active)
        app.button('learning_create', '建立新實驗', (450, 220, 220, 36), enabled=not active and self.loading is None, primary=True)
        app.button('learning_stop', '停止', (690, 220, 110, 36), enabled=active)
        state = self.run.snapshot() if self.run else {}
        if state.get('status') == 'completed' and self._loaded_run is not self.run:
            try:
                self.open(self.run.path)
                self._loaded_run = self.run
            except (OSError, ValueError, KeyError) as exc:
                self.message = str(exc)
        stages = {'acquiring': '取得來源', 'reading': '串流讀取棋譜', 'sampling': '抽樣及排除重複', 'completed': '資料已保存'}
        statuses = {'queued': '排隊', 'running': '處理中', 'completed': '完成', 'stopped': '已停止', 'failed': '失敗'}
        if state and not (self.message or state.get('error') or self.loading is not None):
            app.text(f'{statuses.get(state["status"], state["status"])} · {stages.get(state["stage"], state["stage"])}'
                     f' · {state.get("bytes", 0) / 1048576:.1f} MB · {state.get("source_games", 0)} 盤 · {state.get("elapsed_seconds", 0):.1f} 秒', 50, 276, width=790)
        if self.loading is not None:
            app.text('載入已保存資料…', 50, 278, width=790)
        elif self.message or state.get('error'):
            app.text(self.message or state['error'], 50, 278, width=790)
        if self.data and self.page != 'home':
            data = self.data
            summary = data['summary']
            app.text(f'{summary["selected_games"]}/500 盤 · {summary["positions"]}/6000 局面 · 來源不足 {summary["shortfall_games"]} 盤 · 重複棋譜 {summary["duplicate_games"]}', 50, 310, width=790)
            for index, (split, title) in enumerate(SPLIT_LABELS.items()):
                group = summary['splits'][split]
                phases = ' / '.join(f'{label} {group["stages"].get(stage, 0)}' for stage, label in STAGE_LABELS.items())
                app.text(f'{title}：{group["games"]} 盤 / {group["positions"]} 局面　{phases}', 50, 348 + index * 30, width=790)
            excluded = summary['excluded']
            for row, keys in enumerate((('first_8_plies', 'terminal', 'in_check'), ('not_sampled', 'cross_split_duplicate', 'within_split_duplicate'))):
                app.text(' · '.join(f'{EXCLUSION_LABELS[k]} {excluded.get(k, 0)}' for k in keys), 50, 445 + row * 27, muted=True, width=790)
            source = data['source']
            app.text(f'{source["license"]} · 種子 {data["seed"]} · 處理 v{data["processing_version"]} · SHA256 {source["sha256"][:16]}…', 50, 505, muted=True, width=790)
            if data['positions']:
                sample = data['positions'][self.sample_index]
                app.text(f'局面 {self.sample_index + 1}/{len(data["positions"])} · {SPLIT_LABELS[sample["split"]]} · {STAGE_LABELS[sample["stage"]]} · 第 {sample["ply"]} 手', 50, 537, width=790)
                app.button('learning_prev', '上一局面', (50, 573, 170, 34))
                app.button('learning_next', '下一局面', (235, 573, 170, 34))
                app.button('learning_sample', '棋盤與完整歷史', (420, 573, 270, 34))
        entries = self.entries()
        pages = max(1, (len(entries) + 2) // 3)
        self.recent_page = min(self.recent_page, pages - 1)
        app.text(f'已保存實驗 {self.recent_page + 1}/{pages}', 50, 620)
        app.button('learning_recent_prev', '上頁', (570, 617, 120, 32), enabled=self.recent_page > 0 and not (self.run and not self.run.future.done()))
        app.button('learning_recent_next', '下頁', (705, 617, 120, 32), enabled=self.recent_page < pages - 1 and not (self.run and not self.run.future.done()))
        for row, entry in enumerate(entries[self.recent_page * 3:self.recent_page * 3 + 3]):
            try:
                saved = json.loads(entry.read_text(encoding='utf-8'))
                status = 'completed' if (entry.parent / 'dataset.json').exists() else saved['status']
                label = statuses.get(status, '未完成')
                if status in ('running', 'queued'):
                    label = '未完成，請重建'
                label = f'{entry.parent.name[:12]} · {label} · 種子 {saved["seed"]}'
            except (OSError, ValueError, KeyError):
                label, status = '紀錄損壞', 'failed'
            app.button(f'learning_open:{self.recent_page * 3 + row}', label,
                       (50, 658 + row * 30, 775, 28), enabled=not (self.run and not self.run.future.done()))
