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
from tests.helpers.learning_ui import choose_labels
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
                if action in ('learning_groups', 'learning_training', 'learning_combinations', 'learning_inventory') and app.learning.page_loading is not None:
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: app.learning.page_loading.result(timeout=30)
                    app.render()
                if action == 'learning_labels':
                    future = app.learning.labels.loading
                    if future is not None:
                        if hasattr(app.executor, 'finish'): app.executor.finish()
                        else: future.result(timeout=15)
                        app.render()
            click('mode:learning'); click('learning_nav_data'); app.learning.open(self.labels.parents[1])
            choose_labels(app, self.labels, training=True)
            click('learning_groups_new')
            view = app.learning.group_training
            deadline = time.monotonic()+45
            while view.run.snapshot()['completed_groups'] < 2:
                self.assertLess(time.monotonic(),deadline)
                app.render(); time.sleep(.01)
            active_run = view.run
            from engine.learning.labeling import create_labeling
            newer_label = create_labeling(self.labels.parents[1], app.learning.teacher.path)
            self.assertNotEqual(newer_label, self.labels)
            app.learning.root = self.root / 'data'
            click('learning_breadcrumb_data')
            click('learning_goal_results')
            app.learning.page_loading.result(timeout=30); app.render()
            click('learning_results_open:0')
            app.learning.page_loading.result(timeout=30); app.render()
            self.assertIs(app.learning.active_task()[2], active_run)
            click('learning_task_return')
            self.assertIs(app.learning.group_training.run, active_run)
            click('learning_combinations')
            self.assertEqual(app.learning.page, 'combination')
            click('learning_task_return')
            self.assertIs(app.learning.group_training.run, active_run)
            frozen_snapshot = (view.path / 'snapshot.json').read_bytes()
            pilot_path = app.learning.teacher.path
            pilot_status = (pilot_path / 'status.json').read_bytes()
            click('learning_nav_teacher')
            self.assertIn(app.learning.page, ('teacher', 'labeling'))
            self.assertEqual(app.learning.labels.path, self.labels)
            self.assertIs(view.run, active_run)
            click('learning_nav_teacher')
            app.render()
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_pilot_start').enabled)
            click('learning_engine')
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
            app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='另一份設定'))
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
            self.assertEqual(app.learning.teacher.command, '另一份設定')
            self.assertIsNone(app.learning.teacher.run)
            self.assertEqual((pilot_path / 'status.json').read_bytes(), pilot_status)
            self.assertEqual((view.path / 'snapshot.json').read_bytes(), frozen_snapshot)
            click('learning_nav_teacher')
            app.render()
            self.assertIs(view.run, active_run)
            before = active_run.snapshot()['completed_groups']
            deadline = time.monotonic() + 30
            while active_run.snapshot()['completed_groups'] <= before:
                self.assertFalse(active_run.future.done())
                self.assertLess(time.monotonic(), deadline)
                app.render(); time.sleep(.01)
            click('learning_task_return')
            self.assertEqual(app.learning.page, 'groups')
            click('learning_nav_teacher')
            click('learning_task_stop'); view.run.future.result(timeout=5)
            click('learning_nav_groups'); app.render()
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_groups_resume').enabled)
            path = view.path
            saved = load_group_training(path)
            self.assertGreaterEqual(saved['completed_groups'],3)
            self.assertEqual(saved['status'],'stopped')
            committed = {str(p.relative_to(path)):p.read_bytes() for p in path.glob('groups/*/report.json')}
            committed.update({str(p.relative_to(path)):p.read_bytes() for p in path.glob('groups/*/candidates/*.json')})
            import shutil
            shutil.rmtree(newer_label)
            app.close()
            app = ChessApplication(app.screen,executor=executor)
            click('mode:learning'); click('learning_nav_data'); app.learning.open(self.labels.parents[1])
            choose_labels(app, self.labels, training=True)
            self.assertEqual(app.learning.group_training.state['completed_groups'],saved['completed_groups'])
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
