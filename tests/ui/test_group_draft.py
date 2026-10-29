"""單群組草稿與既有成果的事件驗收。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures
from engine.learning.group_training import GROUPS

class GroupDraftTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_existing_result_opens_separate_draft_with_all_groups_selected(self):
        from engine.learning.group_training import create_group_training
        original = create_group_training(self.labels, groups=['piece-square'])
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.open(self.labels.parents[1])
            app.learning.labels.open(self.labels.parents[1], app.learning.teacher.path, executor, self.labels)
            app.learning.labels.loading.result(timeout=30)
            app.learning.labels.render(app)
            app.learning.group_training.open(self.labels, original)
            app.mode = 'learning'; app.learning.page = 'groups'
            app.render()
            self.assertFalse(any(b.action.startswith('learning_groups_toggle:') for b in app.buttons))
            button = next(b for b in app.buttons if b.action == 'learning_groups_draft')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            app.render()
            self.assertEqual(len([b for b in app.buttons if b.action.startswith('learning_groups_toggle:')]), len(GROUPS))
            self.assertEqual(app.learning.group_training.selected, set(GROUPS))
            self.assertIn('5', next(b.label for b in app.buttons if b.action == 'learning_groups_new'))
            self.assertEqual(app.learning.group_training.path, original)

    def test_single_group_saved_and_new_draft_preserves_result(self):
        from engine.learning.group_training import load_group_training
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.open(self.labels.parents[1])
            app.learning.labels.open(self.labels.parents[1], app.learning.teacher.path, executor, self.labels)
            app.learning.labels.loading.result(timeout=30); app.learning.labels.render(app)
            app.learning.group_training.open(self.labels)
            app.mode = 'learning'; app.learning.page = 'groups'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            for group in GROUPS: click('learning_groups_toggle:' + group)
            app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_groups_new').enabled)
            app.dispatch('learning_groups_new')
            self.assertIsNone(app.learning.group_training.run)
            click('learning_groups_toggle:mobility'); click('learning_groups_new')
            view = app.learning.group_training
            view.run.future.result(timeout=60); app.render()
            first = view.path
            state = load_group_training(first)
            self.assertEqual(list(state['snapshot']['groups']), ['mobility'])
            self.assertEqual(state['completed'], 3)
            self.assertEqual(state['status'], 'completed')
            saved = (first / 'snapshot.json').read_bytes()
            click('learning_groups_stage')
            metric = state['groups']['mobility']['report']['validation']['original']['stages']['opening']['mae']
            expected_metric = '無資料' if metric is None else f'{metric:.4f}'
            with patch.object(app, 'button', wraps=app.button) as draw:
                app.render()
            self.assertTrue(any(call.args[0] == 'learning_groups_select:mobility' and expected_metric in call.args[1]
                                for call in draw.call_args_list))
            click('learning_groups_detail')
            self.assertTrue(view.detail)
            click('learning_groups_advanced')
            self.assertTrue(view.advanced)
            click('learning_groups_draft')
            for group in GROUPS:
                if group != 'piece-square': click('learning_groups_toggle:' + group)
            click('learning_groups_new')
            view.run.future.result(timeout=60); app.render()
            self.assertNotEqual(view.path, first)
            self.assertEqual(list(load_group_training(view.path)['snapshot']['groups']), ['piece-square'])
            self.assertEqual((first / 'snapshot.json').read_bytes(), saved)
            expected = load_group_training(view.path)['groups']['piece-square']['frozen']['config']
            if view.comparison_future is not None: view.comparison_future.result(timeout=30)
            with patch.object(app, 'text', wraps=app.text) as draw:
                app.render()
            self.assertTrue(any('尚未比較' in str(call.args[0]) for call in draw.call_args_list))
            click('learning_groups_detail'); click('learning_groups_select:piece-square'); click('learning_groups_compare')
            app.learning.page_loading.result(timeout=30); app.render()
            self.assertEqual(app.learning.comparison.source['config'], expected)
            click('learning_compare_back'); click('learning_groups_save')
            import json
            self.assertEqual(json.loads(view.saved.read_text(encoding='utf-8')), expected)
            click('learning_groups_battle')
            app.opponent = 'Greedy'; app.start_game()
            self.assertEqual(app.live.settings.black_evaluation.to_dict(), expected)
    def test_legacy_unfinished_resume_and_create_draft_from_result(self):
        from engine.learning.training import create_training, load_training
        legacy = create_training(self.labels)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.open(self.labels.parents[1])
            app.learning.labels.open(self.labels.parents[1], app.learning.teacher.path, executor, self.labels)
            app.learning.labels.loading.result(timeout=30); app.learning.labels.render(app)
            app.learning.group_training.open(self.labels)
            app.mode = 'learning'; app.learning.page = 'groups'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_training')
            app.learning.page_loading.result(timeout=30); app.render()
            self.assertEqual(app.learning.training.path, legacy)
            click('learning_training_resume')
            app.learning.training.run.future.result(timeout=60); app.render()
            self.assertEqual(load_training(legacy)['status'], 'completed')
            before = (legacy / 'snapshot.json').read_bytes()
            click('learning_training_draft'); app.render()
            self.assertEqual(app.learning.page, 'groups')
            self.assertEqual(app.learning.group_training.selected, set(GROUPS))
            self.assertEqual((legacy / 'snapshot.json').read_bytes(), before)
    def test_browsed_result_new_draft_restores_its_original_source(self):
        from engine.learning.group_training import create_group_training
        original = create_group_training(self.labels, groups=['mobility'])
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.mode = 'learning'; app.learning.root = self.labels.parents[1].parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if app.learning.page_loading is not None:
                    app.learning.page_loading.result(timeout=30); app.render()
            click('learning_goal_results')
            click('learning_results_open:0')
            self.assertEqual(app.learning.group_training.path, original)
            click('learning_groups_draft')
            self.assertEqual(app.learning.labels.path, self.labels)
            self.assertFalse(app.learning.browse_result)
            self.assertEqual(app.learning.group_training.selected, set(GROUPS))
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_groups_new').enabled)

    def test_screening_evidence_is_loaded_without_blocking_navigation(self):
        from threading import Event
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        from ui import group_training_view
        path = create_group_training(self.labels, ['mobility']); run_group_training(path)
        source = load_group_candidate(path, 'mobility')
        lines = [dict(initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', moves_uci=[], name='短局', source={})]
        screening = create_comparison(self.root, source, roles=('learned',), screening=True, opening_lines=lines)
        run_evaluation_comparison(**comparison_options(screening, 'stable'))
        entered, release = Event(), Event()
        real_report = group_training_view.comparison_report
        def slow_report(*args):
            entered.set(); self.assertTrue(release.wait(10)); return real_report(*args)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.open(self.labels.parents[1]); app.learning.labels.open(self.labels.parents[1], app.learning.teacher.path, executor, self.labels)
            app.learning.labels.loading.result(timeout=30); app.learning.labels.render(app)
            app.learning.group_training.open(self.labels, path)
            app.mode = 'learning'; app.learning.page = 'groups'
            with patch('ui.group_training_view.comparison_report', side_effect=slow_report):
                app.render()
                self.assertTrue(entered.wait(5))
                button = next(b for b in app.buttons if b.action == 'learning_nav_data')
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                self.assertEqual(app.learning.page, 'data')
                release.set(); app.learning.group_training.comparison_future.result(timeout=30)
                app.learning.page = 'groups'
                with patch.object(app, 'text', wraps=app.text) as draw: app.render()
                self.assertTrue(any('已有對戰紀錄' in str(call.args[0]) for call in draw.call_args_list))
    def test_comparison_return_refreshes_evidence(self):
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        path = create_group_training(self.labels, ['mobility']); run_group_training(path)
        source = load_group_candidate(path, 'mobility')
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.open(self.labels.parents[1]); app.learning.labels.open(self.labels.parents[1], app.learning.teacher.path, executor, self.labels)
            app.learning.labels.loading.result(timeout=30); app.learning.labels.render(app)
            app.learning.group_training.open(self.labels, path)
            app.mode = 'learning'; app.learning.page = 'groups'; app.render()
            view = app.learning.group_training
            if view.comparison_future is not None: view.comparison_future.result(timeout=30)
            app.render()
            self.assertNotIn('mobility', view.compared)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_groups_compare'); app.learning.page_loading.result(timeout=30); app.render()
            lines = [dict(initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', moves_uci=[], name='短局', source={})]
            comparison = create_comparison(self.root, source, roles=('learned',), opening_lines=lines)
            run_evaluation_comparison(**comparison_options(comparison, 'material'))
            click('learning_compare_back'); app.render()
            if view.comparison_future is not None: view.comparison_future.result(timeout=30)
            with patch.object(app, 'text', wraps=app.text) as draw: app.render()
            self.assertTrue(any('已有對戰紀錄' in str(call.args[0]) for call in draw.call_args_list))
