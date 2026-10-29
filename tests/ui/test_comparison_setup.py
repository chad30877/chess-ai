"""從跨來源候選直接建立比較用途的介面事件。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import unittest
from unittest.mock import patch
from pathlib import Path
import pygame
from tests import test_weight_training as fixtures
from tests.helpers.executors import ManualExecutor
from engine.learning.training import create_training, run_training
from apps.chess_application import ChessApplication, APP_SIZE

class ComparisonSetupUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_legacy_candidate_can_open_independent_original_comparison(self):
        path = create_training(self.labels); run_training(path)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_candidate:0')
            from engine.learning.candidate_inventory import validate_candidate_row
            selected = validate_candidate_row(app.learning.inventory.report['candidates'][0])
            broken = self.root / 'data/learning-comparisons/broken'
            broken.mkdir(parents=True)
            (broken / 'snapshot.json').write_text('{broken', encoding='utf-8')
            click('learning_inventory_details'); click('learning_inventory_compare'); executor.finish(); app.render()
            self.assertEqual(app.learning.page, 'comparison')
            self.assertEqual(app.learning.comparison.source, selected)
            self.assertEqual(app.learning.comparison.roles, {'original', 'learned'})
            (path / 'report.json').unlink()
            click('learning_compare_freeze')
            self.assertIsNone(app.learning.comparison.path)
            self.assertTrue(app.learning.comparison.message)
            self.assertIsNone(app.batch)

    def test_three_candidates_preview_and_start_one_48_game_work(self):
        import json
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        for index in range(3):
            path = create_training(self.labels)
            file = path / 'snapshot.json'
            snapshot = json.loads(file.read_text(encoding='utf-8'))
            weight = .5 + index * .2
            snapshot['original']['terms']['piece_square']['weight'] = weight
            snapshot['original_weights'][0] = snapshot['scales'][0] = weight
            snapshot.pop('identity'); snapshot['identity'] = digest(snapshot)
            write_json_atomic(file, snapshot); run_training(path)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            for index in range(3): click('learning_inventory_candidate:' + str(index))
            click('learning_inventory_setup'); executor.finish(); app.render()
            self.assertEqual(app.learning.page, 'setup')
            self.assertEqual(app.learning.setup.quick['planned_games'], 48)
            self.assertEqual(len(app.learning.setup.quick['sources']), 3)
            click('learning_setup_final'); app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_setup_start').enabled)
            click('learning_setup_to_screening')
            self.assertEqual(app.learning.setup.purpose, 'screening')
            from engine.learning.screening import create_screening
            for row in app.learning.setup.rows: create_screening(self.root, row['source'])
            click('learning_setup_back')
            with patch('engine.learning.comparison_setup.screening_report', return_value={'complete': True, 'eliminated': False}):
                click('learning_inventory_setup'); executor.finish(); app.render()
            click('learning_setup_final')
            with patch.object(app, 'text', wraps=app.text) as draw: app.render()
            self.assertTrue(any('384' in str(call.args[0]) for call in draw.call_args_list))
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_setup_start').enabled)
            click('learning_setup_screening')
            click('learning_setup_start')
            self.assertIsNone(app.batch)
            self.assertEqual(app.learning.active_task()[0], 'setup')
            pending = app.learning.pending_setup
            pending_index = next(i for i, item in enumerate(executor.jobs) if item[0] is pending.future)
            original = app.learning.setup
            click('learning_setup_back')
            click('learning_inventory_candidate:0')
            click('learning_inventory_setup'); executor.finish(); app.render()
            self.assertIsNot(app.learning.setup, original)
            click('learning_task_return')
            self.assertIs(app.learning.setup, original)
            executor.finish(pending_index); app.render()
            self.assertIsNotNone(app.batch)
            self.assertEqual(app.batch.snapshot()['requested_games'], 48)
            app.batch.stop(); executor.finish(); app.render()
            self.assertEqual(app.batch.snapshot()['status'], 'stopped')

    def test_source_disappearing_after_preview_does_not_start_or_freeze(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning import comparison_setup
        path = create_training(self.labels); run_training(path)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); app.learning.page_loading.result(timeout=30); app.render()
            click('learning_inventory_candidate:0'); click('learning_inventory_setup')
            app.learning.page_loading.result(timeout=30); app.render()
            entered, release = threading.Event(), threading.Event()
            original = comparison_setup.freeze_setup
            def delayed(*args):
                entered.set(); self.assertTrue(release.wait(10)); return original(*args)
            with patch('engine.learning.comparison_setup.freeze_setup', side_effect=delayed):
                click('learning_setup_start')
                self.assertTrue(entered.wait(10))
                (path / 'report.json').unlink()
                release.set()
                with self.assertRaises(ValueError): app.learning.pending_setup.future.result(timeout=30)
                app.render()
            self.assertIsNone(app.batch)
            self.assertIn('來源已失效', app.learning.setup.message)
            self.assertFalse((self.root / 'data/learning-setup').exists())
            self.assertFalse((self.root / 'data/learning-screening').exists())

    def test_short_bundle_continues_across_pages_blocks_other_work_and_saves_on_stop(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.comparison import create_comparison
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        path = create_training(self.labels); run_training(path)
        row = next(item for item in load_all_candidate_inventory(self.root / 'data')['candidates'] if item['path'] == str(path))
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name=str(i), source={}) for i in range(8)]
        plan = create_comparison(self.root, row['source'], roles=('learned',), screening=True, opening_lines=lines, max_plies=1)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); app.learning.page_loading.result(timeout=30); app.render()
            click('learning_inventory_candidate:0'); click('learning_inventory_setup')
            app.learning.page_loading.result(timeout=30); app.render()
            with patch('engine.learning.comparison_setup.freeze_setup', return_value={'work': [dict(path=str(plan), baseline='stable')], 'planned_games': 16}):
                click('learning_setup_start')
                app.learning.pending_setup.future.result(timeout=10); app.render()
            run = app.batch
            self.assertEqual(app.mode, 'auto')
            click('learning_comparison_return'); click('learning_nav_data')
            app.dispatch('learning_pilot_start')
            self.assertIsNone(app.learning.teacher.run)
            deadline = time.monotonic() + 30
            while run.snapshot()['saved_games'] < 1:
                self.assertFalse(run.future.done())
                self.assertLess(time.monotonic(), deadline)
                app.render(); time.sleep(.02)
            click('learning_task_stop'); run.future.result(timeout=20)
            self.assertEqual(run.snapshot()['status'], 'stopped')
            self.assertTrue(Path(run.snapshot()['last_replay']).exists())

    def test_original_comparison_workload_tracks_roles_and_references(self):
        path = create_training(self.labels); run_training(path)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_candidate:0'); click('learning_inventory_details'); click('learning_inventory_compare'); executor.finish(); app.render()
            click('learning_compare_role:original')
            with patch.object(app, 'text', wraps=app.text) as draw: app.render()
            self.assertTrue(any('共64局' in str(call.args[0]) for call in draw.call_args_list))
            click('learning_compare_stable')
            with patch.object(app, 'text', wraps=app.text) as draw: app.render()
            self.assertTrue(any('共128局' in str(call.args[0]) for call in draw.call_args_list))
            click('learning_compare_freeze')
            plan = app.learning.comparison.report['plan']
            self.assertEqual(plan['roles'], ['learned'])
            self.assertEqual(set(plan['definitions']), {'material', 'stable'})
            self.assertEqual(plan['planned_games'], 128)
            self.assertEqual(plan['source']['experiment_id'], path.name)
