import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor

class LoadingUiTest(unittest.TestCase):
    def test_label_page_is_available_before_saved_records_finish_loading(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'teacher-labels' / 'one'
            saved.mkdir(parents=True)
            (saved / 'snapshot.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'
            app.learning.path = root
            app.learning.teacher.path = root / 'pilot'
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.learning.page = 'teacher'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels')
            self.assertEqual(app.learning.page, 'labeling')
            app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_labels_resume').enabled)
            button = next(b for b in app.buttons if b.action == 'learning_labels_new')
            self.assertFalse(button.enabled)
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            self.assertIsNone(app.learning.labels.run)
            self.assertEqual(len(executor.jobs), 1)
            click('learning_teacher')
            self.assertEqual(app.learning.page, 'teacher')
            app.close()


    def test_switching_saved_labels_ignores_an_older_read(self):
        from unittest.mock import patch
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('one', 'two'):
                saved = root / 'teacher-labels' / name
                saved.mkdir(parents=True)
                (saved / 'snapshot.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'
            app.learning.path = root
            app.learning.teacher.path = root / 'pilot'
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.learning.page = 'teacher'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            def read(path):
                return {'status': 'stopped', 'completed': 1, 'total': 2, 'remaining': 1, 'failed': 0, 'name': path.name}
            with patch('ui.label_view.load_labeling', side_effect=read):
                click('learning_labels'); executor.finish(); app.render()
                first = app.learning.labels.path
                click('learning_labels_next')
                click('learning_labels_next')
                executor.finish(2); app.render()
                self.assertEqual(app.learning.labels.path, first)
                executor.finish(1); app.render()
                self.assertEqual(app.learning.labels.path, first)
                self.assertEqual(app.learning.labels.state['name'], first.name)
            app.close()

    def test_unavailable_label_can_be_retried_without_switching_source(self):
        from unittest.mock import patch
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'teacher-labels' / 'broken'
            saved.mkdir(parents=True)
            (saved / 'snapshot.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.learning.saved_state_path = root / 'ui-state.json'; app.learning.saved_state = {}
            app.mode = 'learning'; app.learning.path = root
            app.learning.teacher.path = root / 'pilot'
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.learning.page = 'teacher'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            with patch('ui.label_view.load_labeling', side_effect=ValueError('損壞')):
                click('learning_labels'); executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, saved)
            self.assertIn('損壞', app.learning.labels.message)
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_labels_new').enabled)
            good = {'status': 'stopped', 'completed': 1, 'total': 2, 'remaining': 1, 'failed': 0}
            with patch('ui.label_view.load_labeling', return_value=good):
                click('learning_labels_retry'); executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, saved)
            self.assertFalse(app.learning.labels.message)
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_labels_resume').enabled)
            app.close()

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
            app.mode = 'learning'; app.learning.root = root
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
            button = next(b for b in app.buttons if b.action == 'learning_pilot_next')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            app.render()
            self.assertTrue(app.learning.teacher.loading)
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_labels').enabled)
            button = next(b for b in app.buttons if b.action == 'learning_data')
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
        button = next(b for b in app.buttons if b.action == 'learning_groups')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'groups')
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
        click('learning_labels'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, broken)
        self.assertIn(str(broken), app.learning.labels.message)
        self.assertFalse(next(b for b in app.buttons if b.action == 'learning_groups').enabled)
        snapshot.write_bytes(original)
        click('learning_labels_retry'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, broken)
        self.assertTrue(app.learning.labels.state['ready'])
        snapshot.write_text('{broken', encoding='utf-8')
        click('learning_labels_next'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, self.labels)
        self.assertTrue(app.learning.labels.state['ready'])
        snapshot.write_bytes(original)
        click('learning_labels_prev'); executor.finish(); app.render()
        self.assertEqual(app.learning.labels.path, broken)
        self.assertTrue(app.learning.labels.state['ready'])
        self.assertTrue(next(b for b in app.buttons if b.action == 'learning_groups').enabled)
        app.close()

    def test_switching_training_results_can_be_left_while_loading(self):
        from engine.learning.training import create_training
        create_training(self.labels)
        create_training(self.labels)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        app.learning.saved_state_path = self.root / 'ui-state.json'; app.learning.saved_state = {}
        app.mode = 'learning'; app.learning.page = 'training'
        app.learning.training.open(self.labels)
        selected = app.learning.training.entries[1].parent
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_training_next')
        self.assertTrue(button.enabled)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        app.render()
        self.assertTrue(app.learning.page_loading)
        button = next(b for b in app.buttons if b.action == 'learning_loading_back')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        self.assertEqual(app.learning.page, 'training')
        app.render()
        button = next(b for b in app.buttons if b.action == 'learning_training_next')
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
        executor.finish(); app.render()
        self.assertEqual(app.learning.training.path, selected)
        executor.finish(0); app.render()
        self.assertEqual(app.learning.training.path, selected)
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
        click('learning_labels'); executor.finish(); app.render()
        click('learning_labels_new'); executor.finish(); app.render()
        self.assertIsNotNone(app.learning.labels.loading)
        click('learning_teacher')
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
        button = next(b for b in app.buttons if b.action == 'learning_labels')
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
            app.mode = 'learning'; app.learning.root = dataset.parent
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_open:0'); executor.finish(); app.render()
            self.assertIsNotNone(app.learning.data)
            click('learning_teacher')
            self.assertEqual(app.learning.teacher.path, broken)
            self.assertIn(str(broken), app.learning.teacher.message)
            click('learning_pilot_next'); executor.finish(); app.render()
            self.assertEqual(app.learning.teacher.path, valid)
            self.assertTrue(app.learning.teacher.state['choice'])
            app.close()
