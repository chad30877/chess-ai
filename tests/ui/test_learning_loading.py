from tests.helpers.learning_ui import choose_labels
"""非同步選擇與過期結果不覆蓋目前頁面。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor
from ui.label_view import LabelView

class LoadingUiTest(unittest.TestCase):
    def test_leaving_selector_ignores_older_read(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode((900,768)), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'
            app.dispatch('learning_choose_training_labels')
            pending = app.learning.page_loading
            app.dispatch('learning_nav_data')
            executor.finish(); app.render()
            self.assertTrue(pending.done())
            self.assertEqual(app.learning.page, 'data')
            self.assertIsNone(app.learning.page_loading)

    def test_explicit_label_from_other_pilot_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'teacher-labels' / 'chosen'
            path.mkdir(parents=True); (path / 'snapshot.json').write_text('{}')
            state = dict(ready=True, snapshot={'pilot_path': str(root / 'original')})
            with patch('ui.label_view.load_labeling', return_value=state):
                entries, selected, loaded, error = LabelView._read_saved(root, path, root / 'other')
            self.assertIsNone(error)
            self.assertEqual(selected, path)
            self.assertTrue(loaded['ready'])

    def test_read_failure_can_be_retried(self):
        executor = ManualExecutor(); view = LabelView()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'teacher-labels' / 'chosen'
            path.mkdir(parents=True); (path / 'snapshot.json').write_text('{}')
            with patch('ui.label_view.load_labeling', side_effect=ValueError('損壞')):
                view.open(root, root / 'pilot', executor, path); executor.finish(); view._poll_loading()
            self.assertTrue(view.load_error)
            from types import SimpleNamespace
            with patch('ui.label_view.load_labeling', return_value={'ready':True}):
                view.action('learning_labels_retry', SimpleNamespace(read_executor=executor))
                executor.finish(); view._poll_loading()
            self.assertFalse(view.load_error)
            self.assertTrue(view.state['ready'])

class ExistingLoadingUiTest(unittest.TestCase):
    def test_dataset_selection_keeps_event_loop_available_during_read(self):
        import json
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'one'; saved.mkdir()
            (saved / 'status.json').write_text(json.dumps({'status': 'completed', 'seed': 1}), encoding='utf-8')
            (saved / 'dataset.json').write_text('{broken', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'; app.learning.root = root; app.learning.page = 'data'
            app.render()
            button = next(b for b in app.buttons if b.action == 'learning_open:0')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            app.render()
            self.assertTrue(app.learning.loading)
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_teacher').enabled)
            executor.finish(); app.render()
            self.assertIn(str(saved), app.learning.message)
            app.close()

    def test_teacher_selection_stays_responsive_while_saved_pilot_loads(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('one', 'two'):
                saved = root / 'teacher-pilots' / name; saved.mkdir(parents=True)
                (saved / 'status.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'; app.learning.page = 'teacher'
            app.learning.teacher.dataset = root
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.render()
            app.dispatch('learning_pilot_next')
            app.render()
            self.assertTrue(app.learning.teacher.loading)
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_labels_new').enabled)
            button = next(b for b in app.buttons if b.action == 'learning_nav_data')
            self.assertTrue(button.enabled)
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            self.assertEqual(app.learning.page, 'data')
            app.close()

    def test_learning_results_page_can_be_left_while_loading(self):
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.mode = 'learning'; app.learning.page = 'labeling'
        app.learning.labels.path = Path('saved-labels')
        app.learning.labels.state = {'status': 'completed', 'completed': 1, 'total': 1, 'remaining': 0, 'failed': 0, 'ready': True}
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_choose_training_labels')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'label_choices')
        app.render()
        self.assertTrue(app.learning.page_loading)
        button = next(b for b in app.buttons if b.action == 'learning_loading_back')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'labeling')
        app.close()


class RealLabelRecoveryTest(unittest.TestCase):
    from tests import test_weight_training as fixtures
    setUp = fixtures.TrainingFlowTest.setUp

    def test_corrupt_saved_label_can_be_repaired_and_reloaded(self):
        pygame.init(); self.addCleanup(pygame.quit)
        import shutil
        broken = self.labels.parent / 'broken'
        shutil.copytree(self.labels, broken)
        snapshot = broken / 'snapshot.json'
        original = snapshot.read_bytes()
        snapshot.write_text('{broken', encoding='utf-8')
        os.utime(snapshot, (snapshot.stat().st_mtime + 5, snapshot.stat().st_mtime + 5))
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        app.mode = 'learning'; app.learning.path = self.labels.parents[1]
        app.learning.teacher.path = next((self.labels.parents[1] / 'teacher-pilots').iterdir())
        app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
        app.learning.page = 'teacher'
        def click(action):
            app.render()
            button = next(b for b in app.buttons if b.action == action)
            self.assertTrue(button.enabled, action)
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        click('learning_nav_teacher'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, broken)
        self.assertIn(str(broken), app.learning.labels.message)
        self.assertFalse(app.learning.labels.state.get('ready', False))
        snapshot.write_bytes(original)
        click('learning_labels_retry'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, broken)
        self.assertTrue(app.learning.labels.state['ready'])
        snapshot.write_text('{broken', encoding='utf-8')
        choose_labels(app, self.labels)
        self.assertEqual(app.learning.labels.path, self.labels)
        self.assertTrue(app.learning.labels.state['ready'])
        snapshot.write_bytes(original)
        choose_labels(app, broken)
        self.assertEqual(app.learning.labels.path, broken)
        self.assertTrue(app.learning.labels.state['ready'])
        self.assertTrue(next(b for b in app.buttons if b.action == 'learning_choose_training_labels').enabled)
        app.close()

    def test_switching_training_results_can_be_left_while_loading(self):
        from engine.learning.group_training import create_group_training
        create_group_training(self.labels)
        create_group_training(self.labels)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        app.mode = 'learning'; app.learning.page = 'groups'
        app.learning.group_training.open(self.labels)
        selected = app.learning.group_training.entries[1].parent
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_groups_next')
        self.assertTrue(button.enabled)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        app.render()
        self.assertTrue(app.learning.page_loading)
        button = next(b for b in app.buttons if b.action == 'learning_loading_back')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'groups')
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_groups_next')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        executor.finish(); app.render()
        self.assertEqual(app.learning.group_training.path, selected)
        executor.finish(0); app.render()
        self.assertEqual(app.learning.group_training.path, selected)
        app.close()

    def test_completed_label_run_reloads_records_without_blocking_navigation(self):
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        dataset = self.labels.parents[1]
        app.mode = 'learning'; app.learning.path = dataset
        app.learning.teacher.path = next((dataset / 'teacher-pilots').iterdir())
        app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
        app.learning.page = 'teacher'
        def click(action):
            app.render()
            button = next(b for b in app.buttons if b.action == action)
            self.assertTrue(button.enabled, action)
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        click('learning_nav_teacher'); executor.finish(); app.render()
        app.learning.labels.dataset = dataset
        app.learning.labels.pilot = app.learning.teacher.path
        app.learning.teacher.dataset = dataset
        click('learning_labels_recreate'); executor.finish(); app.render()
        self.assertIsNotNone(app.learning.labels.loading)
        click('learning_nav_teacher')
        self.assertEqual(app.learning.page, 'teacher')
        app.close()

    def test_switching_comparison_plan_can_be_left_while_loading(self):
        from engine.learning.comparison import create_comparison
        from tests.test_learned_comparison import candidate
        source = candidate()
        create_comparison(self.root, source, roles=['learned'])
        create_comparison(self.root, source, roles=['learned'])
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        from ui.learned_comparison_view import LearnedComparisonView
        app.learning.comparison = LearnedComparisonView(self.root)
        app.mode = 'learning'; app.learning.open_comparison(source)
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_compare_next_plan')
        self.assertTrue(button.enabled)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        app.render()
        self.assertIsNotNone(app.learning.page_loading)
        button = next(b for b in app.buttons if b.action == 'learning_loading_back')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'comparison')
        app.close()

    def test_comparison_report_refresh_does_not_block_and_reports_invalid_source(self):
        from unittest.mock import patch
        from engine.learning.comparison import create_comparison
        from tests.test_learned_comparison import candidate
        from ui.learned_comparison_view import LearnedComparisonView
        source = candidate(); path = create_comparison(self.root, source, roles=['learned'])
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        app.learning.comparison = LearnedComparisonView(self.root)
        app.mode = 'learning'; app.learning.open_comparison(source)
        with patch('ui.learned_comparison_view.comparison_report', side_effect=ValueError('報告損壞')):
            app.render()
            self.assertFalse(executor.jobs[-1][0].done())
            executor.finish(); app.render()
        self.assertIn(str(path), app.learning.comparison.message)
        self.assertFalse(any(b.action == 'learning_compare_start' for b in app.buttons))
        button = next(b for b in app.buttons if b.action == 'learning_compare_back')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'groups')
        app.close()

    def test_reading_saved_labels_does_not_wait_for_busy_task_worker(self):
        from threading import Event
        pygame.init(); self.addCleanup(pygame.quit)
        gate = Event()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE))
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        self.addCleanup(app.close)
        busy = app.executor.submit(gate.wait)
        self.addCleanup(gate.set)
        dataset = self.labels.parents[1]
        app.mode = 'learning'; app.learning.path = dataset
        app.learning.teacher.path = next((dataset / 'teacher-pilots').iterdir())
        app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
        app.learning.page = 'teacher'; app.render()
        button = next(b for b in app.buttons if b.action == 'learning_nav_teacher')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        app.learning.labels.loading.result(timeout=5); app.render()
        self.assertTrue(app.learning.labels.state['ready'])
        self.assertFalse(busy.done())
        gate.set(); busy.result(timeout=5)

    def test_corrupt_latest_pilot_does_not_hide_dataset_or_older_pilot(self):
        import shutil
        from unittest.mock import patch
        dataset = self.labels.parents[1]
        valid = next((dataset / 'teacher-pilots').iterdir())
        broken = valid.parent / 'broken'; shutil.copytree(valid, broken)
        status = broken / 'status.json'; status.write_text('{broken', encoding='utf-8')
        os.utime(status, (status.stat().st_mtime + 10, status.stat().st_mtime + 10))
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'; app.learning.page = 'data'; app.learning.root = dataset.parent
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_open:0'); executor.finish(); app.render()
            self.assertIsNotNone(app.learning.data)
            click('learning_nav_teacher')
            self.assertEqual(app.learning.teacher.path, broken)
            self.assertIn(str(broken), app.learning.teacher.message)
            app.dispatch('learning_pilot_next'); executor.finish(); app.render()
            self.assertEqual(app.learning.teacher.path, valid)
            self.assertTrue(app.learning.teacher.state['choice'])
            app.close()
