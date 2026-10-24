"""組合 UI 的勾選預覽、直接／聯合另存及真人對戰載入。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests import test_weight_training as fixtures
from engine.learning.group_training import create_group_training, run_group_training
from engine.learning.combination_training import load_combination_candidate


class CombinationUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_select_preview_train_reopen_export_both_kinds_and_load_battle(self):
        source = create_group_training(self.labels,['mobility','king-safety']); run_group_training(source)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT',self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            def open_view():
                click('mode:learning'); app.learning.open(self.labels.parents[1])
                click('learning_teacher'); click('learning_labels'); click('learning_groups'); click('learning_combinations')
            open_view(); view = app.learning.combination
            self.assertEqual(view.selected,{'mobility','king-safety'})
            click('learning_combination_toggle:king-safety')
            self.assertFalse(view.preview['direct']['terms']['king_pawn_shield']['enabled'])
            click('learning_combination_toggle:king-safety'); click('learning_combination_new')
            view.run.future.result(timeout=35); app.render()
            self.assertEqual(view.state['status'],'completed',view.message)
            path = view.path
            click('learning_combination_toggle:king-safety'); app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_combination_save').enabled)
            self.assertFalse(view.preview['direct']['terms']['king_pawn_shield']['enabled'])
            click('learning_combination_toggle:king-safety')
            for kind in ('direct','joint'):
                click('learning_combination_kind:'+kind); click('learning_combination_weights'); click('learning_combination_weights')
                click('learning_combination_save')
                self.assertTrue(view.saved.exists())
                click('learning_combination_compare')
                self.assertEqual(app.learning.page,'comparison')
                click('learning_compare_freeze')
                plan=app.learning.comparison.report['plan']
                expected=load_combination_candidate(path,kind)
                self.assertEqual(plan['source'],expected)
                self.assertEqual(plan['definitions']['material']['candidates'][1]['config'],expected['config'])
                self.assertEqual(plan['planned_games'],128)
                click('learning_compare_back'); click('learning_combinations')
            app.close(); app = ChessApplication(app.screen,executor=executor); open_view()
            self.assertEqual(app.learning.combination.path,path)
            click('learning_combination_kind:direct'); click('learning_combination_battle')
            app.opponent = 'Greedy'; app.start_game()
            self.assertEqual(app.live.settings.black_evaluation.to_dict(),load_combination_candidate(path,'direct')['config'])
            app.close()
