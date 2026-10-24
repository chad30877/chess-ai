"""UI 事件完成學習、保存重開、另存及對戰載入。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures
from tests.helpers.executors import ManualExecutor

class TrainingUiTest(unittest.TestCase):
    setUp=fixtures.TrainingFlowTest.setUp
    def test_events_train_reopen_save_and_load_battle(self):
        pygame.init(); self.addCleanup(pygame.quit)
        executor=ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT',self.root):
            app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor)
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action)
                self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            click('mode:learning')
            app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_training')
            click('learning_training_new'); executor.finish(); app.render()
            view=app.learning.training
            self.assertEqual(view.state['status'],'completed',view.state.get('error'))
            path=view.path; test_report=(path/'report.json').read_bytes()
            click('learning_training_stage'); click('learning_training_advanced')
            app.close()
            app=ChessApplication(app.screen,executor=executor)
            click('mode:learning'); app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_training')
            self.assertEqual(app.learning.training.path,path)
            self.assertEqual((path/'report.json').read_bytes(),test_report)
            click('learning_training_save')
            saved=app.learning.training.saved
            self.assertTrue(saved.exists())
            click('learning_training_battle')
            self.assertEqual(app.mode,'human')
            self.assertEqual(app.live_evaluation_file,saved)
            app.opponent='Greedy'; app.start_game()
            self.assertEqual(app.live.settings.black_evaluation.to_dict(),app.learning.training.state['frozen']['config'])
            app.close()

