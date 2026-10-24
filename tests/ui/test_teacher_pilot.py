"""使用實際 UI 事件完成教師先導、停止、選擇及保存重開。"""
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


class PilotUiTest(unittest.TestCase):
    def test_events_start_cancel_choose_and_reopen_saved_teacher(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(16), encoding='utf-8')
            dataset = create_dataset(root / 'data/learning', source)
            command = make_engine(root)
            with patch('apps.chess_application.PROJECT_ROOT', root):
                executor = ManualExecutor()
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                app.learning.teacher.command = command
                click('learning_pilot_start')
                click('learning_pilot_stop')
                executor.finish()
                app.render()
                self.assertEqual(app.learning.teacher.state['status'], 'stopped')
                click('learning_pilot_start')
                executor.finish()
                app.render()
                self.assertEqual(app.learning.teacher.state['status'], 'completed')
                click('learning_budget:50000')
                choice = app.learning.teacher.state['choice']
                self.assertEqual(choice['nodes'], 50000)
                app.close()
                app = ChessApplication(app.screen, executor=executor)
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                self.assertEqual(app.learning.teacher.state['choice'], choice)
                app.learning.teacher.command = str(root / 'missing-stockfish.exe')
                click('learning_pilot_start')
                executor.finish()
                app.render()
                self.assertEqual(app.learning.teacher.state['status'], 'failed')
                self.assertIn('執行檔', app.learning.teacher.state['error'])
                app.learning.teacher.command = command
                click('learning_pilot_start')
                app.close()
                executor.finish()
                app.render()
                self.assertEqual(app.learning.teacher.state['status'], 'stopped')
