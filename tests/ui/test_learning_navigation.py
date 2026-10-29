"""學習實驗主入口與前置引導的應用程式事件。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import pygame
from apps.chess_application import APP_SIZE, ChessApplication
from tests.helpers.executors import ManualExecutor

class LearningNavigationTest(unittest.TestCase):
    def test_home_purposes_and_main_navigation_remain_available(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode((900, 768)), executor=executor)
            self.addCleanup(app.close)
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning')
            for action in ('learning_goal_create', 'learning_goal_resume', 'learning_goal_compare', 'learning_goal_results'):
                app.render()
                self.assertTrue(next(b for b in app.buttons if b.action == action).enabled)
            click('learning_goal_compare')
            click('learning_nav_teacher')
            executor.finish()
            app.render()
            self.assertEqual(app.learning.page, 'teacher')
            click('learning_breadcrumb_data')
            click('learning_goal_compare')
            executor.finish()
            app.render()
            self.assertEqual(app.learning.page, 'inventory')
            self.assertIsNone(app.batch)
            for action, page in (('learning_nav_teacher', 'teacher'), ('learning_nav_groups', 'groups'),
                                 ('learning_nav_data', 'data')):
                click(action)
                self.assertEqual(app.learning.page, page)
                app.render()
                for name in ('data', 'teacher', 'groups', 'inventory'):
                    self.assertTrue(next(b for b in app.buttons if b.action == 'learning_nav_' + name).enabled)
            click('learning_breadcrumb_data')
            self.assertEqual(app.learning.page, 'home')
            click('learning_goal_resume')
            self.assertEqual(app.learning.page, 'groups')
            click('learning_breadcrumb_data')
            click('learning_goal_results')
            executor.finish()
            app.render()
            self.assertEqual(app.learning.page, 'results')
            click('learning_breadcrumb_data')
            click('learning_goal_create')
            self.assertEqual(app.learning.page, 'data')

    def test_learning_entry_reaches_missing_labels_and_return_to_teacher(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=ManualExecutor())
            self.addCleanup(app.close)
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning')
            click('learning_nav_groups')
            self.assertEqual(app.learning.page, 'groups')
            app.render()
            self.assertFalse(any(b.enabled for b in app.buttons if b.action in ('learning_groups_new', 'learning_groups_resume')))
            app.dispatch('learning_groups_new')
            self.assertIsNone(app.learning.group_training.run)
            app.dispatch('learning_pilot_start')
            app.dispatch('learning_labels_new')
            self.assertIsNone(app.learning.teacher.run)
            self.assertIsNone(app.learning.labels.run)
            self.assertFalse(app.executor.jobs)
            click('learning_need_labels')
            self.assertEqual(app.learning.page, 'labeling')
            app.render()
            first = next(b.label for b in app.buttons if b.action == 'learning_breadcrumb_teacher')
            click('learning_breadcrumb_teacher')
            self.assertEqual(app.learning.page, 'teacher')
            click('learning_need_labels')
            app.render()
            self.assertEqual(next(b.label for b in app.buttons if b.action == 'learning_breadcrumb_teacher'), first)
            click('learning_breadcrumb_teacher')
            self.assertEqual(app.learning.page, 'teacher')

class SourceStageTest(unittest.TestCase):
    from tests.test_weight_training import TrainingFlowTest
    setUp = TrainingFlowTest.setUp

    def test_continue_learning_finds_saved_labels_without_opening_label_page(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.new_setup('learning')
            app.learning.open(self.labels.parents[1])
            from engine.learning.labeling import create_labeling
            newer = create_labeling(self.labels.parents[1], app.learning.teacher.path)
            key = f'labeling:{app.learning.path}:{app.learning.teacher.path}'
            app.learning.saved_state.setdefault('selected', {})[key] = str(self.labels)
            app.render()
            button = next(b for b in app.buttons if b.action == 'learning_goal_resume')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            self.assertEqual(app.learning.page, 'groups')
            executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, self.labels)
            self.assertTrue(app.learning.labels.state['ready'])
            self.assertTrue(any(b.action == 'learning_groups_new' and b.enabled for b in app.buttons))
            button = next(b for b in app.buttons if b.action == 'learning_labels')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            app.render()
            button = next(b for b in app.buttons if b.action == 'learning_labels_next')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, newer)

    def test_stage_follows_selected_dataset_without_reusing_old_labels(self):
        from engine.learning.dataset import create_dataset
        from tests.test_learning_dataset import pgn_games
        pygame.init(); self.addCleanup(pygame.quit)
        source = self.root / 'other.pgn'
        source.write_text(pgn_games(8), encoding='utf-8')
        other = create_dataset(self.root / 'data', source, seed=12)
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.new_setup('learning')
            app.learning.open(self.labels.parents[1])
            app.learning.action('learning_nav_teacher', app)
            app.learning.action('learning_labels', app)
            executor.finish()
            app.render()
            self.assertTrue(app.learning.labels.state['ready'])
            selected_dataset, selected_pilot = app.learning.path, app.learning.teacher.path
            app.render()
            crumb = next(b for b in app.buttons if b.action == 'learning_breadcrumb_teacher')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=crumb.rect.center, button=1))
            self.assertEqual((app.learning.path, app.learning.teacher.path), (selected_dataset, selected_pilot))
            with patch.object(app, 'text', wraps=app.text) as draw:
                app.render()
            self.assertTrue(any('教師標記 完成' in str(call.args[0]) for call in draw.call_args_list))
            app.learning.open(other)
            app.learning.action('learning_nav_data', app)
            with patch.object(app, 'text', wraps=app.text) as draw:
                app.render()
            self.assertTrue(any('教師標記 尚未載入' in str(call.args[0]) for call in draw.call_args_list))
            app.learning.action('learning_nav_groups', app)
            app.render()
            self.assertTrue(any(b.action == 'learning_need_labels' for b in app.buttons))

class MainEntryCoverageTest(unittest.TestCase):
    from tests.test_weight_training import TrainingFlowTest
    setUp = TrainingFlowTest.setUp

    def test_all_main_entries_work_from_each_available_learning_page(self):
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.training import create_training
        create_training(self.labels)
        source = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(source)
        final_path = freeze_final_comparison(self.root, [load_group_candidate(source, 'mobility')])
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.new_setup('learning')
            app.learning.root = self.root / 'data'
            app.learning.open(self.labels.parents[1])
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if app.learning.page_loading is not None:
                    app.learning.page_loading.result(timeout=30); app.render()
                if action == 'learning_labels' and app.learning.labels.loading is not None:
                    app.learning.labels.loading.result(timeout=30); app.render()
            def goto(page):
                if page == 'home': click('learning_breadcrumb_data'); return
                if page == 'data': click('learning_nav_data'); return
                if page == 'teacher': click('learning_nav_teacher'); return
                if page in ('labeling', 'groups', 'training', 'combination', 'comparison'):
                    click('learning_nav_teacher'); click('learning_labels')
                    if page == 'labeling': return
                    click('learning_groups')
                    if page == 'training': click('learning_training'); return
                    if page == 'groups': return
                    if page == 'comparison':
                        click('learning_groups_select:mobility'); click('learning_groups_compare'); return
                    click('learning_combinations'); return
                click('learning_nav_inventory')
                if page == 'inventory': return
                if page in ('screening', 'heldout'):
                    click('learning_inventory_screen')
                    if page == 'heldout':
                        app.learning.screening.final_path = final_path
                        click('learning_screening_heldout')
                    return
                if page == 'results':
                    click('learning_breadcrumb_data'); click('learning_goal_results'); return
                raise AssertionError(page)
            for page in ('home', 'data', 'teacher', 'labeling', 'training', 'groups',
                         'combination', 'inventory', 'screening', 'comparison', 'results', 'heldout'):
                for target in ('data', 'teacher', 'groups', 'inventory'):
                    with self.subTest(page=page, target=target):
                        goto(page)
                        self.assertEqual(app.learning.page, page)
                        click('learning_nav_' + target)
                        self.assertEqual(app.learning.page, target)
