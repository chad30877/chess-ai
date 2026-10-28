"""比較預覽的實際按鈕、背景停止與重開來源。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor
from tests.test_learned_comparison import candidate


class LearnedComparisonUiTest(unittest.TestCase):
    def test_rating_details_show_saved_comparison_source(self):
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT',Path(folder)):
            lines=[dict(initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1',moves_uci=[],name='',source={})]
            path=create_comparison(folder,candidate(),roles=('learned',),stable=True,opening_lines=lines)
            batch=run_evaluation_comparison(**comparison_options(path,'stable')).path
            app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=ManualExecutor())
            app.learning.open_comparison(candidate()); app.mode='learning'
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            click('learning_compare_baseline:stable'); click('learning_compare_rating')
            with patch.object(app,'text',wraps=app.text) as draw:
                app.render()
            self.assertTrue(any(str(batch) in str(call.args[0]) for call in draw.call_args_list))
            app.close()

    def test_events_preview_extra_reference_freeze_stop_reopen_and_resume(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT',Path(folder)):
            executor=ManualExecutor()
            app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor)
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action)
                self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            app.learning.open_comparison(candidate()); app.mode='learning'
            click('learning_compare_stable'); click('learning_compare_freeze')
            view=app.learning.comparison; path=view.path
            self.assertEqual(view.report['plan']['planned_games'],256)
            click('learning_compare_baseline:stable')
            click('learning_compare_rating')
            self.assertTrue(view.rating_details)
            self.assertEqual(view.report['baselines']['stable']['candidates'][0]['rating']['status'], 'unrated')
            click('learning_compare_rating')
            click('learning_compare_baseline:material')
            click('learning_compare_config'); click('learning_compare_config_next'); click('learning_compare_config')
            click('learning_compare_start'); self.assertEqual(app.mode,'auto')
            self.assertEqual(app.batch.options['workers'],4)
            click('stop'); executor.finish(); app.close()
            app=ChessApplication(app.screen,executor=executor)
            app.learning.open_comparison(candidate()); app.mode='learning'; app.render()
            self.assertEqual(app.learning.comparison.path,path)
            self.assertEqual(app.learning.comparison.report['baselines']['material']['status'],'stopped')
            click('learning_compare_start')
            self.assertEqual(app.batch.options['workers'],4)
            self.assertIn('resume_path',app.batch.options)
            click('stop'); executor.finish(); app.close()
