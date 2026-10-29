"""舊棋子位置成果保留資料，透過統一候選介面進入比較。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures
from tests.helpers.executors import ManualExecutor
from tests.helpers.learning_ui import settle

class TrainingUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_legacy_result_reopens_in_unified_candidates_without_mutation(self):
        from engine.learning.training import create_training, run_training
        from engine.learning.candidate_inventory import validate_candidate_row
        path = create_training(self.labels); run_training(path)
        original = (path / 'report.json').read_bytes()
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            for _ in range(2):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                app.mode = 'learning'; app.learning.root = self.labels.parents[2]
                app.dispatch('learning_nav_inventory'); settle(app, app.learning.page_loading)
                rows = app.learning.inventory.report['candidates']
                index = next(i for i, row in enumerate(rows) if path in Path(row['path']).parents)
                source = validate_candidate_row(rows[index])
                app.learning.inventory.page = next(i for i, (j, _) in enumerate(app.learning.inventory.filtered()) if j == index) // 4
                app.render()
                button = next(b for b in app.buttons if b.action == f'learning_inventory_candidate:{index}')
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                app.dispatch('learning_inventory_setup'); settle(app, app.learning.page_loading)
                self.assertEqual(app.learning.page, 'setup')
                self.assertEqual(app.learning.setup.rows[0]['source']['config'], source['config'])
                self.assertEqual((path / 'report.json').read_bytes(), original)
                app.close()
