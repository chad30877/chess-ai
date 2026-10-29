"""跨來源學習比較與回放的整合事件。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest
from pathlib import Path
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures

class LearningIntegrationTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_legacy_and_group_short_results_keep_sources_through_replay(self):
        from engine.learning.training import create_training, run_training
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.candidate_inventory import load_legacy_candidate
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        legacy = create_training(self.labels); run_training(legacy)
        group = create_group_training(self.labels, ['mobility']); run_group_training(group)
        sources = [load_legacy_candidate(legacy), load_group_candidate(group, 'mobility')]
        lines = [dict(initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', moves_uci=[], name='短局', source={})]
        plans = []
        for source in sources:
            plan = create_comparison(self.root, source, roles=('learned',), opening_lines=lines)
            run_evaluation_comparison(**comparison_options(plan, 'material')); plans.append(plan)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.new_setup('learning'); app.learning.root = self.labels.parents[1].parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if app.learning.page_loading is not None:
                    app.learning.page_loading.result(timeout=30); app.render()
            click('learning_goal_compare')
            self.assertEqual(len(app.learning.inventory.report['candidates']), 2)
            click('learning_inventory_history')
            for source, plan in zip(sources, plans):
                index = next(i for i, row in enumerate(app.learning.comparison_history.entries) if row['path'] == plan)
                click('learning_history_open:' + str(index))
                self.assertEqual(app.learning.comparison.source, source)
                row = app.learning.comparison.report['baselines']['material']['candidates'][0]
                self.assertEqual(row['config'], source['config'])
                self.assertGreater(row['wins'] + row['draws'] + row['losses'], 0)
                click('learning_compare_config'); click('learning_compare_config')
                click('learning_compare_replay'); self.assertEqual(app.mode, 'replay')
                click('learning_comparison_return')
                self.assertEqual(app.learning.comparison.path, plan)
                self.assertEqual(app.learning.comparison.source, source)
                click('learning_compare_back')
    def test_ui_creates_cross_source_bundle_and_replays_both_candidates(self):
        from engine.learning.training import create_training, run_training
        from engine.learning.group_training import create_group_training, run_group_training
        from engine.learning.comparison_setup import load_saved_setup
        legacy = create_training(self.labels); run_training(legacy)
        group = create_group_training(self.labels, ['mobility']); run_group_training(group)
        lines = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in range(1, 41)]
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.new_setup('learning'); app.learning.root = self.labels.parents[1].parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if app.learning.page_loading is not None:
                    app.learning.page_loading.result(timeout=30); app.render()
            click('learning_goal_compare')
            rows = app.learning.inventory.report['candidates']
            selected = [next(i for i, row in enumerate(rows) if Path(row['path']).is_relative_to(path)) for path in (legacy, group)]
            from engine.learning.candidate_inventory import validate_candidate_row
            expected = [validate_candidate_row(rows[i]) for i in sorted(selected)]
            for index in selected: click('learning_inventory_candidate:' + str(index))
            click('learning_inventory_setup')
            self.assertEqual(app.learning.setup.quick['planned_games'], 32)
            with patch('engine.learning.screening.common_opening_lines', return_value=lines):
                click('learning_setup_start')
                app.learning.pending_setup.future.result(timeout=30); app.render()
            run = app.batch; run.future.result(timeout=120); app.render()
            self.assertEqual(run.snapshot()['status'], 'completed')
            bundle = next((self.root / 'data/learning-setup').iterdir())
            saved, reports = load_saved_setup(bundle)
            self.assertEqual(saved['sources'], expected)
            self.assertEqual([row['status'] for row in reports], ['completed', 'completed'])
            click('learning_comparison_return'); click('learning_nav_inventory'); click('learning_inventory_history')
            index = next(i for i, item in enumerate(app.learning.comparison_history.entries) if item['path'] == bundle)
            click('learning_history_open:' + str(index))
            self.assertEqual(app.learning.history_bundle.path, bundle)
            for index, source in enumerate(expected):
                click('learning_bundle_open:' + str(index))
                self.assertEqual(app.learning.comparison.source, source)
                click('learning_compare_config'); click('learning_compare_config')
                click('learning_compare_replay'); self.assertEqual(app.mode, 'replay')
                click('learning_comparison_return')
                self.assertEqual(app.learning.comparison.source, source)
                click('learning_compare_back')
