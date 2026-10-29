"""跨頁操作不得中斷正在執行的教師先導。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset
from tests.helpers.executors import ManualExecutor
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games

class TaskNavigationTest(unittest.TestCase):
    def test_pilot_can_leave_and_return_without_losing_running_job(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            create_dataset(root / 'data/learning', source)
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                app.learning.teacher.command = make_engine(root)
                click('learning_pilot_start')
                run = app.learning.teacher.run
                click('learning_data')
                self.assertEqual(app.learning.page, 'data')
                self.assertFalse(run.future.done())
                click('learning_task_return')
                self.assertEqual(app.learning.page, 'teacher')
                self.assertIs(app.learning.teacher.run, run)

    def test_another_start_is_blocked_while_pilot_is_running(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            dataset = create_dataset(root / 'data/learning', source)
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close)
                app.new_setup('learning')
                app.learning.open(dataset)
                app.learning.page = 'teacher'
                app.learning.teacher.command = make_engine(root)
                app.dispatch('learning_pilot_start')
                self.assertEqual(len(executor.jobs), 1)
                app.learning.page = 'labeling'
                app.dispatch('learning_labels_new')
                self.assertEqual(len(executor.jobs), 1)
                self.assertIn('教師先導', app.learning.labels.message)
