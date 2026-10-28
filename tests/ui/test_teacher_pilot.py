"""使用實際 UI 事件完成教師先導、停止、選擇及保存重開。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import time
from concurrent.futures import ThreadPoolExecutor
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset
from tests.helpers.executors import ManualExecutor
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games
from tests.test_teacher_parallel import observed_engine


class PilotUiTest(unittest.TestCase):
    def test_parallel_pilot_stop_preserves_partial_records_and_cannot_choose_budget(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            create_dataset(root / 'data/learning', source)
            command = observed_engine(root)
            with patch('apps.chess_application.PROJECT_ROOT', root), ThreadPoolExecutor(1) as executor:
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                view = app.learning.teacher
                view.command = command
                click('learning_pilot_start')
                deadline = time.monotonic() + 10
                while view.run.snapshot()['completed'] == 0:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.005)
                click('learning_pilot_stop')
                view.run.future.result(timeout=5)
                app.render()
                saved = view.state
                self.assertEqual(saved['status'], 'stopped')
                self.assertGreater(saved['completed'], 0)
                self.assertLess(saved['completed'], saved['total'])
                click('learning_data')
                click('learning_teacher')
                self.assertEqual(view.state['records'], saved['records'])
                self.assertEqual(view.state['budget_measurements'], saved['budget_measurements'])
                self.assertTrue(all(not b.enabled for b in app.buttons if b.action.startswith('learning_budget:')))

    def test_workers_input_default_validation_and_frozen_reopen(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            create_dataset(root / 'data/learning', source)
            command = make_engine(root)
            with patch('apps.chess_application.PROJECT_ROOT', root), patch('os.process_cpu_count', return_value=1, create=True):
                executor = ManualExecutor()
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                def enter(text):
                    click('learning_teacher_workers')
                    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
                    app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=text))
                    click('learning_pilot_start')
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                view = app.learning.teacher
                self.assertEqual(view.workers, 1)
                view.command = command
                enter('0')
                self.assertIsNone(view.run)
                self.assertIn('正整數', view.message)
                enter('2')
                executor.finish()
                app.render()
                self.assertEqual(view.state['snapshot']['workers'], 2)
                click('learning_budget:50000')
                self.assertEqual(view.state['choice']['workers'], 2)
                click('learning_data')
                click('learning_teacher')
                self.assertEqual(view.workers, 2)
                self.assertEqual(view.state['choice']['workers'], 2)

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
