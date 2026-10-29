"""合併教師頁、來源選擇及四個主要入口的事件驗收。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication
from tests.helpers.executors import ManualExecutor
from tests.helpers.learning_ui import settle, choose_labels

class LearningNavigationTest(unittest.TestCase):
    def test_main_entries_and_empty_states_remain_available(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            app = ChessApplication(pygame.display.set_mode((900, 768)), executor=ManualExecutor())
            self.addCleanup(app.close); app.mode = 'learning'
            for target, page in [('data','data'), ('teacher','teacher'), ('groups','label_choices'), ('inventory','inventory')]:
                for current in ('home', 'data', 'teacher'):
                    app.learning.page = current; app.render()
                    button = next(b for b in app.buttons if b.action == 'learning_nav_' + target)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                    settle(app, app.learning.page_loading)
                    self.assertEqual(app.learning.page, page)
                    app.render()
                    self.assertTrue(all(next(b for b in app.buttons if b.action == 'learning_nav_' + name).enabled for name in ('data','teacher','groups','inventory')))
            self.assertIsNone(app.batch)
            app.dispatch('learning_training'); settle(app, app.learning.page_loading)
            self.assertEqual(app.learning.page, 'inventory')

class SourceStageTest(unittest.TestCase):
    from tests.test_weight_training import TrainingFlowTest
    setUp = TrainingFlowTest.setUp

    def test_explicit_teacher_selection_opens_training_and_has_no_legacy_page(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode((900,768)), executor=ManualExecutor())
        self.addCleanup(app.close); app.mode = 'learning'
        choose_labels(app, self.labels, training=True)
        self.assertEqual(app.learning.group_training.labels, self.labels)
        app.render()
        self.assertTrue(next(b for b in app.buttons if b.action == 'learning_groups_new').enabled)
        self.assertFalse(any(b.action == 'learning_training' for b in app.buttons))
        app.dispatch('learning_nav_teacher'); settle(app, app.learning.labels.loading); app.render()
        self.assertTrue(any(b.action == 'learning_pilot_start' for b in app.buttons))
        self.assertTrue(any(b.action == 'learning_labels_new' for b in app.buttons))
        self.assertEqual(app.learning.page, 'teacher')
