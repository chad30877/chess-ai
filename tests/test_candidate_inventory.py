import unittest
from tests import test_weight_training as fixtures
from engine.learning.group_training import create_group_training, run_group_training
from engine.learning.combination_training import create_combination, run_combination

class InventoryTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_inventory_reopens_saved_results_and_ranks_distinct_candidates(self):
        from engine.learning.candidate_inventory import load_candidate_inventory
        source = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(source)
        combination = create_combination(source, ['mobility', 'king-safety'])
        run_combination(combination)
        report = load_candidate_inventory(source)
        self.assertEqual(len(report['entries']), 31)
        self.assertFalse(report['complete'])
        self.assertEqual(report['entries'][('mobility',)]['single'], 'completed')
        self.assertEqual(report['entries'][('mobility', 'king-safety')]['direct'], 'completed')
        self.assertEqual(report['entries'][('mobility', 'king-safety')]['joint'], 'completed')
        self.assertEqual(report['entries'][('pawn',)]['single'], 'missing')
        self.assertEqual(report['candidates'], sorted(report['candidates'], key=lambda c: c['mae']))
        self.assertEqual(len({c['config_identity'] for c in report['candidates']}), len(report['candidates']))
        self.assertTrue(all(c['games'] > 0 and c['positions'] > 0 for c in report['candidates']))
        self.assertTrue(report['exposure'])
        self.assertEqual(report, load_candidate_inventory(source))

class InventoryUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_inventory_event_does_not_start_games_and_reopens(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import pygame
        from apps.chess_application import ChessApplication, APP_SIZE
        source = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(source)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning'); app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_groups'); click('learning_combinations')
            click('learning_inventory')
            self.assertEqual(app.learning.page, 'inventory')
            self.assertFalse(app.learning.inventory.report['complete'])
            self.assertEqual(app.learning.inventory.report['source_identity'], app.learning.combination.sources['mobility']['snapshot_identity'])
            self.assertFalse(app.learning.combination.active())
            click('learning_inventory_back')
            self.assertEqual(app.learning.page, 'combination')
            click('learning_inventory')
            self.assertTrue(app.learning.inventory.report['candidates'])
            app.close()
