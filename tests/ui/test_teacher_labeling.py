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
from engine.learning.teacher import run_pilot, choose_budget
from engine.learning.labeling import load_labeling
from concurrent.futures import ThreadPoolExecutor
import time
from tests.helpers.executors import ManualExecutor
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games


class LabelUiTest(unittest.TestCase):
    def test_events_stop_close_reopen_resume_only_unfinished(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            dataset = create_dataset(root / 'data/learning', source)
            command = make_engine(root)
            script = Path(command[1])
            code = script.read_text(encoding='utf-8').replace('  import chess', "  import time\n  time.sleep(.03)\n  import chess")
            script.write_text(code, encoding='utf-8')
            pilot = run_pilot(dataset, command)
            choose_budget(pilot, 50000)
            with patch('apps.chess_application.PROJECT_ROOT', root), ThreadPoolExecutor(1) as executor:
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                def click(action):
                    app.render()
                    button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                click('learning_labels')
                click('learning_labels_new')
                view = app.learning.labels
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    state = view.run.snapshot()
                    if state['completed'] > state['summary']['reused_pilot']: break
                    time.sleep(.01)
                click('learning_labels_stop')
                view.run.future.result(timeout=5)
                app.render()
                self.assertEqual(view.state['status'], 'stopped')
                path = view.path
                committed = {p.name: p.read_bytes() for p in (path / 'records').glob('*.json')}
                self.assertGreater(len(committed), view.state['summary']['reused_pilot'])
                self.assertGreater(view.state['remaining'], 0)
                app.close()
                app = ChessApplication(app.screen, executor=executor)
                click('mode:learning')
                click('learning_open:0')
                click('learning_teacher')
                click('learning_labels')
                self.assertEqual(app.learning.labels.path, path)
                self.assertEqual(app.learning.labels.state['completed'], len(committed))
                click('learning_labels_resume')
                app.learning.labels.run.future.result(timeout=15)
                app.render()
                self.assertEqual(app.learning.labels.state['status'], 'completed')
                self.assertEqual(app.learning.labels.state['remaining'], 0)
                for name, data in committed.items(): self.assertEqual((path / 'records' / name).read_bytes(), data)
                self.assertTrue(load_labeling(path)['ready'])
                click('learning_labels_advanced')
                app.render()
                manual = ManualExecutor()
                app.executor = manual
                click('learning_labels_new')
                path = app.learning.labels.path
                original = os.replace
                writes = [0]
                def fail_summary(src, target):
                    if Path(target) == path / 'status.json':
                        writes[0] += 1
                        if writes[0] >= 2: raise OSError('摘要保存中斷')
                    return original(src, target)
                with patch('os.replace', fail_summary): manual.finish()
                app.render()
                recovered = load_labeling(path)
                self.assertEqual(app.learning.labels.state['completed'], recovered['completed'])
                self.assertEqual(app.learning.labels.state['status'], 'failed')
                self.assertTrue(app.learning.labels.state['error'])
                app.close()
