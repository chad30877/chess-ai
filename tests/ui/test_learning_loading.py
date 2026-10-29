import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor

class LoadingUiTest(unittest.TestCase):
    def test_label_page_is_available_before_saved_records_finish_loading(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'teacher-labels' / 'one'
            saved.mkdir(parents=True)
            (saved / 'snapshot.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'
            app.learning.path = root
            app.learning.teacher.path = root / 'pilot'
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.learning.page = 'teacher'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels')
            self.assertEqual(app.learning.page, 'labeling')
            app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_labels_resume').enabled)
            click('learning_teacher')
            self.assertEqual(app.learning.page, 'teacher')
            app.close()


    def test_switching_saved_labels_ignores_an_older_read(self):
        from unittest.mock import patch
        pygame.init()
        self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('one', 'two'):
                saved = root / 'teacher-labels' / name
                saved.mkdir(parents=True)
                (saved / 'snapshot.json').write_text('{}', encoding='utf-8')
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'
            app.learning.path = root
            app.learning.teacher.path = root / 'pilot'
            app.learning.teacher.state = {'status': 'completed', 'choice': {'nodes': 50000}}
            app.learning.page = 'teacher'
            def click(action):
                app.render()
                button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            def read(path):
                return {'status': 'stopped', 'completed': 1, 'total': 2, 'remaining': 1, 'failed': 0, 'name': path.name}
            with patch('ui.label_view.load_labeling', side_effect=read):
                click('learning_labels'); executor.finish(); app.render()
                first = app.learning.labels.path
                click('learning_labels_next')
                click('learning_labels_next')
                executor.finish(2); app.render()
                self.assertEqual(app.learning.labels.path, first)
                executor.finish(1); app.render()
                self.assertEqual(app.learning.labels.path, first)
                self.assertEqual(app.learning.labels.state['name'], first.name)
            app.close()
