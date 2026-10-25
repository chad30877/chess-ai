"""完成先導、查看預估、凍結預算及重開的應用程式事件流程。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pygame

from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset
from engine.learning.labeling import load_labeling
from tests.helpers.executors import ManualExecutor
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games


class LabelingEstimatesUiTest(unittest.TestCase):
    def test_estimates_are_available_before_choice_and_survive_reopen_without_teacher(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            create_dataset(root / 'data/learning', source)
            command = make_engine(root)
            with patch('apps.chess_application.PROJECT_ROOT', root):
                executor = ManualExecutor()
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                def open_teacher():
                    click('mode:learning')
                    click('learning_open:0')
                    click('learning_teacher')
                open_teacher()
                app.learning.teacher.command = command
                click('learning_pilot_start')
                executor.finish()
                app.render()
                pilot = app.learning.teacher.state
                self.assertIsNone(pilot['choice'])
                estimates = pilot['labeling_estimates']
                self.assertEqual(set(estimates), {'50000', '200000'})
                self.assertTrue(all(value['seconds'] > 0 for value in estimates.values()))
                self.assertTrue(all(value['remaining'] == 36 for value in estimates.values()))
                click('learning_budget:200000')
                self.assertEqual(app.learning.teacher.state['choice']['nodes'], 200000)
                app.close()
                Path(command[1]).unlink()
                app = ChessApplication(app.screen, executor=executor)
                self.addCleanup(app.close)
                open_teacher()
                self.assertEqual(app.learning.teacher.state['labeling_estimates'], estimates)
                click('learning_labels')
                click('learning_labels_new')
                labels = load_labeling(app.learning.labels.path)
                self.assertEqual(labels['remaining'], estimates['200000']['remaining'])
                self.assertEqual(labels['snapshot']['nodes'], 200000)
