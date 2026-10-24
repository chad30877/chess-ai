"""實際 UI 事件跨五群組停止、關閉續跑及另存。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import time
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures
from engine.learning.group_training import load_group_training


class GroupTrainingUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_events_two_groups_then_stop_close_reopen_resume_save_and_reload(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT',self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            click('mode:learning'); app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_groups')
            click('learning_groups_new')
            view = app.learning.group_training
            deadline = time.monotonic()+45
            while view.run.snapshot()['completed_groups'] < 2:
                self.assertLess(time.monotonic(),deadline)
                app.render(); time.sleep(.01)
            click('learning_groups_stop'); view.run.future.result(timeout=5); app.render()
            path = view.path
            saved = load_group_training(path)
            self.assertEqual(saved['completed_groups'],2)
            self.assertEqual(saved['status'],'stopped')
            committed = {str(p.relative_to(path)):p.read_bytes() for p in path.glob('groups/*/report.json')}
            committed.update({str(p.relative_to(path)):p.read_bytes() for p in path.glob('groups/*/candidates/*.json')})
            app.close()
            app = ChessApplication(app.screen,executor=executor)
            click('mode:learning'); app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_groups')
            self.assertEqual(app.learning.group_training.state['completed_groups'],2)
            click('learning_groups_resume'); app.learning.group_training.run.future.result(timeout=45); app.render()
            self.assertEqual(app.learning.group_training.state['completed_groups'],5)
            self.assertEqual(app.learning.group_training.state['completed'],15)
            for name,data in committed.items(): self.assertEqual((path/name).read_bytes(),data)
            click('learning_groups_select:mobility'); click('learning_groups_detail')
            click('learning_groups_weights_next'); click('learning_groups_stage')
            click('learning_groups_detail'); click('learning_groups_select:king-safety'); click('learning_groups_detail')
            click('learning_groups_advanced'); click('learning_groups_save')
            exported = app.learning.group_training.saved
            self.assertTrue(exported.exists())
            click('learning_groups_battle')
            self.assertEqual(app.mode,'human')
            app.opponent='Greedy'; app.start_game()
            self.assertEqual(app.live.settings.black_evaluation.to_dict(),app.learning.group_training.state['groups']['king-safety']['frozen']['config'])
            app.close()
