"""pygame 介面在網頁介面執行重度工作時避讓，並顯示佔用者。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from apps.chess_application import APP_SIZE, ChessApplication
from engine.sessions import heavy_job
from engine.sessions.heavy_job import HeavyJobExecutor, acquire
from tests.helpers.executors import ManualExecutor


class PygameHeavyJobLockTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode(APP_SIZE)

    def tearDown(self):
        pygame.quit()

    def test_injected_executor_is_used_without_the_lock(self):
        executor = ManualExecutor()
        app = ChessApplication(self.screen, executor=executor)
        self.assertIs(app.heavy_executor, executor)
        app.close()

    def test_busy_lock_shows_owner_instead_of_starting(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            lock_path = Path(folder) / '.heavy-job.lock'
            with patch.object(heavy_job, 'DEFAULT_LOCK_PATH', lock_path), \
                 patch.object(HeavyJobExecutor.__init__, '__kwdefaults__', {'lock_path': lock_path}):
                app = ChessApplication(self.screen)
                started = []
                hold = acquire(program='網頁介面', label='一般批次 Random 對 Random', lock_path=lock_path)
                try:
                    self.assertIsInstance(app.heavy_executor, HeavyJobExecutor)
                    app._handle_event = lambda event: app.heavy_executor.submit(started.append, 1)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(1, 1)))
                    self.assertEqual(started, [])
                    self.assertIn('網頁介面', app.message)
                    self.assertIn('一般批次', app.message)
                finally:
                    hold.release()
                    app.close()


if __name__ == '__main__':
    unittest.main()
