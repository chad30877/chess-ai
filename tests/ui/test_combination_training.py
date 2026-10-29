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
from tests.helpers.learning_ui import choose_labels
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
                if action in ('learning_groups', 'learning_training', 'learning_combinations', 'learning_inventory', 'learning_combination_compare', 'learning_groups_compare') and app.learning.page_loading is not None:
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: app.learning.page_loading.result(timeout=30)
                    app.render()
                if action == 'learning_labels':
                    future = app.learning.labels.loading
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: future.result(timeout=15)
                    app.render()
            def open_view():
                click('mode:learning'); click('learning_nav_data'); app.learning.open(self.labels.parents[1])
                choose_labels(app, self.labels, training=True); click('learning_combinations')
            open_view(); view = app.learning.combination
            click('learning_nav_groups'); click('learning_groups_select:mobility'); click('learning_groups_compare')
            app.render()
            group_breadcrumb = next(b.label for b in app.buttons if b.action == 'learning_breadcrumb_inventory')
            click('learning_compare_back'); click('learning_combinations')
            view = app.learning.combination
            self.assertEqual(view.selected,{'mobility','king-safety'})
            click('learning_combination_toggle:king-safety')
            self.assertFalse(view.preview['direct']['terms']['king_pawn_shield']['enabled'])
            click('learning_combination_toggle:king-safety'); click('learning_combination_new')
            view.run.future.result(timeout=35); app.render()
            self.assertEqual(view.state['status'],'completed',view.message)
            path = view.path
            click('learning_inventory')
            self.assertEqual(app.learning.page, 'inventory')
            self.assertIsNone(app.learning.comparison.path)
            click('learning_inventory_back')
            click('learning_combination_kind:controls')
            self.assertEqual(set(view.state['controls']['validation']['metrics']), {'material', 'mobility', 'king-safety', 'both'})
            click('learning_combination_kind:direct')
            click('learning_combination_toggle:king-safety'); app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_combination_save').enabled)
            self.assertFalse(view.preview['direct']['terms']['king_pawn_shield']['enabled'])
            click('learning_combination_toggle:king-safety')
            breadcrumb = None
            for kind in ('direct','joint'):
                click('learning_combination_kind:'+kind); click('learning_combination_weights'); click('learning_combination_weights')
                click('learning_combination_save')
                self.assertTrue(view.saved.exists())
                click('learning_combination_compare')
                self.assertEqual(app.learning.page,'comparison')
                app.render()
                current = next(b.label for b in app.buttons if b.action == 'learning_breadcrumb_inventory')
                if breadcrumb is None: breadcrumb = current
                self.assertEqual(current, breadcrumb)
                self.assertEqual(current, group_breadcrumb)
                selected_source = app.learning.path
                source_file = path / 'inputs.json'
                saved_inputs = source_file.read_bytes(); source_file.unlink()
                click('learning_compare_freeze')
                self.assertIsNone(app.learning.comparison.path)
                self.assertTrue(app.learning.comparison.message)
                source_file.write_bytes(saved_inputs)
                click('learning_compare_freeze')
                plan=app.learning.comparison.report['plan']
                expected=load_combination_candidate(path,kind)
                self.assertEqual(plan['source'],expected)
                self.assertEqual(plan['definitions']['material']['candidates'][1]['config'],expected['config'])
                self.assertEqual(plan['planned_games'],128)
                click('learning_compare_back')
                self.assertEqual(app.learning.page, 'combination')
                self.assertEqual(app.learning.path, selected_source)
            app.close(); app = ChessApplication(app.screen,executor=executor); open_view()
            self.assertEqual(app.learning.combination.path,path)
            click('learning_combination_kind:direct'); click('learning_combination_battle')
            app.opponent = 'Greedy'; app.start_game()
            self.assertEqual(app.live.settings.black_evaluation.to_dict(),load_combination_candidate(path,'direct')['config'])
            app.close()

    def test_batch_selection_runs_and_reopens_through_application_events(self):
        source = create_group_training(self.labels, ['mobility', 'king-safety']); run_group_training(source)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if action in ('learning_groups', 'learning_training', 'learning_combinations', 'learning_inventory', 'learning_combination_compare', 'learning_groups_compare') and app.learning.page_loading is not None:
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: app.learning.page_loading.result(timeout=30)
                    app.render()
                if action == 'learning_labels':
                    future = app.learning.labels.loading
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: future.result(timeout=15)
                    app.render()
            click('mode:learning'); click('learning_nav_data'); app.learning.open(self.labels.parents[1])
            choose_labels(app, self.labels, training=True); click('learning_combinations')
            view = app.learning.combination
            click('learning_combination_batch')
            view.run.future.result(timeout=45); app.render()
            self.assertEqual(view.batch_state['status'], 'completed', view.message)
            path = view.batch_path
            view.open(source)
            self.assertEqual(view.batch_path, path)
            self.assertEqual(view.batch_state['completed'], 1)
            app.close()
