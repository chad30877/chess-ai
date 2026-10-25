"""透過 UI 選檔與外部教師程序驗證路徑、取消及重開。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset
from tests.helpers.executors import ManualExecutor
from tests.test_learning_dataset import pgn_games


class TeacherPickerTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.executor = ManualExecutor()
        self.screen = pygame.display.set_mode(APP_SIZE)

    def app_at(self, root):
        with patch('apps.chess_application.PROJECT_ROOT', root):
            app = ChessApplication(self.screen, executor=self.executor)
        self.addCleanup(app.close)
        return app

    def click(self, app, action):
        app.render()
        button = next(b for b in app.buttons if b.action == action)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))

    def open_teacher(self, app, root):
        source = root / 'games.pgn'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(pgn_games(2), encoding='utf-8')
        create_dataset(root / 'data/learning', source)
        for action in ('mode:learning', 'learning_open:0', 'learning_teacher'):
            self.click(app, action)

    def test_new_project_default_and_cancel_picker(self):
        for name in ('first', '第二個 專案'):
            root = self.root / name
            app = self.app_at(root)
            self.open_teacher(app, root)
            expected = str(root / 'tools/stockfish/stockfish-windows-x86-64-universal.exe')
            self.assertEqual(app.learning.teacher.command, expected)
            with patch('tkinter.filedialog.askopenfilename', return_value=''):
                self.click(app, 'learning_engine_pick')
            self.assertEqual(app.learning.teacher.command, expected)

    def test_picked_unicode_path_runs_teacher_recovers_and_reopens(self):
        from tests.helpers.uci_teacher import make_engine
        import sys
        app = self.app_at(self.root)
        self.open_teacher(app, self.root)
        engine_dir = self.root / '教師 引擎'
        engine_dir.mkdir()
        command = make_engine(engine_dir)
        if os.name == 'nt':
            engine = engine_dir / '測試 教師.cmd'
            engine.write_text(f'@chcp 65001 >nul\n@"{sys.executable}" "{command[1]}"\n', encoding='utf-8')
        else:
            engine = engine_dir / '測試 教師'
            engine.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{command[1]}"\n', encoding='utf-8')
            engine.chmod(0o755)
        def pick(path):
            with patch('tkinter.filedialog.askopenfilename', return_value=str(path)):
                self.click(app, 'learning_engine_pick')
        invalid = self.root / 'invalid.exe'
        invalid.write_text('not an executable', encoding='utf-8')
        for bad in (self.root / 'missing.exe', invalid):
            pick(bad)
            self.click(app, 'learning_pilot_start')
            self.executor.finish()
            app.render()
            self.assertEqual(app.learning.teacher.state['status'], 'failed')
            self.assertTrue(app.learning.teacher.state['error'])
        pick(engine)
        self.click(app, 'learning_pilot_start')
        self.executor.finish()
        app.render()
        self.assertEqual(app.learning.teacher.state['status'], 'completed', app.learning.teacher.state)
        teacher = app.learning.teacher.state['snapshot']['teacher']
        self.assertEqual(teacher['command'], [str(engine)])
        self.assertEqual(teacher['identification']['name'], 'Stockfish 19')
        saved_path = app.learning.teacher.path
        saved = (saved_path / 'snapshot.json').read_bytes()
        pick(self.root / 'another.exe')
        self.assertEqual((saved_path / 'snapshot.json').read_bytes(), saved)
        app.close()
        app = self.app_at(self.root)
        for action in ('mode:learning', 'learning_open:0', 'learning_teacher'):
            self.click(app, action)
        self.assertEqual(app.learning.teacher.command, str(engine))
        self.assertEqual((saved_path / 'snapshot.json').read_bytes(), saved)
