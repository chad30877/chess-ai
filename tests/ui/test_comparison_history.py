"""比較紀錄入口與保存來源的介面事件。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor
from tests.test_learned_comparison import candidate
from engine.learning.comparison import create_comparison
from engine.learning.screening import create_screening
from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison

class ComparisonHistoryTest(unittest.TestCase):
    def test_open_saved_three_purposes_from_candidates(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            screening = create_screening(folder, candidate())
            direct = create_comparison(folder, candidate())
            final = freeze_final_comparison(folder, [candidate()], learned_only=True)
            final_plan = Path(load_final_comparison(final)['candidates'][0]['path'])
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            entries = app.learning.comparison_history.entries
            for purpose, path in [('screening', screening), ('final', final_plan), ('comparison', direct)]:
                index = next(i for i, row in enumerate(entries) if row['purpose'] == purpose and row['path'] == path)
                click('learning_history_open:' + str(index)); executor.finish(); app.render()
                self.assertEqual(app.learning.comparison.path, path)
                self.assertEqual(app.learning.comparison.source, candidate())
                click('learning_compare_back')
    def test_short_saved_plan_resume_replay_and_preserve_games(self):
        import json
        import time
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.comparison import comparison_options, comparison_report
        from engine.sessions.comparison_run import ComparisonRun
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)), ThreadPoolExecutor(1) as executor:
            lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name=str(i), source={}) for i in range(8)]
            path = create_comparison(folder, candidate(), roles=('learned',), opening_lines=lines, max_plies=1)
            run = ComparisonRun(comparison_options(path, 'material'), executor)
            deadline = time.monotonic() + 30
            while run.snapshot()['saved_games'] < 1:
                self.assertFalse(run.future.done()); self.assertLess(time.monotonic(), deadline); time.sleep(.02)
            run.stop(); run.future.result(timeout=30)
            before = comparison_report(path)['baselines']['material']
            self.assertGreater(len(before['replays']), 0)
            saved = {p: p.read_bytes() for p in before['replays'] if json.loads(p.read_text(encoding='utf-8'))['metadata']['termination'] != 'user_stop'}
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); app.learning.page_loading.result(timeout=30); app.render()
            click('learning_inventory_history'); app.learning.page_loading.result(timeout=30); app.render()
            click('learning_history_open:0'); app.learning.page_loading.result(timeout=30); app.render()
            row = app.learning.comparison.report['baselines']['material']['candidates'][0]
            self.assertGreater(row['pending_games'], 0)
            self.assertGreater(row['wins'] + row['draws'] + row['losses'] + row['unfinished'], 0)
            click('learning_compare_start'); app.batch.future.result(timeout=30)
            self.assertTrue(all(p.read_bytes() == data for p, data in saved.items()))
            app.mode = 'learning'; app.learning.page = 'comparison'
            app.learning.comparison.open_history(path)
            row = app.learning.comparison.report['baselines']['material']['candidates'][0]
            self.assertEqual(row['pending_games'], 0)
            self.assertEqual(row['wins'] + row['draws'] + row['losses'] + row['unfinished'], 16)
            click('learning_compare_config'); click('learning_compare_config')
            click('learning_compare_replay'); self.assertEqual(app.mode, 'replay')
            self.assertEqual(app.replay_return, 'learning')
            click('learning_comparison_return')
            self.assertEqual(app.learning.page, 'comparison')
            self.assertEqual(app.learning.comparison.path, path)
            app.close()
    def test_damaged_record_does_not_hide_valid_record(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            good = create_comparison(folder, candidate())
            bad = Path(folder) / 'data/learning-comparisons/broken'; bad.mkdir()
            (bad / 'snapshot.json').write_text('{', encoding='utf-8')
            missing = Path(folder) / 'data/learning-comparisons/missing'; missing.mkdir()
            executor = ManualExecutor()
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            rows = app.learning.comparison_history.entries
            self.assertEqual({row['path'] for row in rows if row['status'] == 'invalid'}, {bad, missing})
            index = next(i for i, row in enumerate(rows) if row['path'] == bad)
            click('learning_history_open:' + str(index)); executor.finish(); app.render()
            self.assertIn(str(bad), app.learning.page_load_error)
            click('learning_loading_back')
            index = next(i for i, row in enumerate(rows) if row['path'] == good)
            click('learning_history_open:' + str(index)); executor.finish(); app.render()
            self.assertEqual(app.learning.comparison.path, good)
            app.close()
    def test_multi_candidate_setup_can_resume_all_saved_work(self):
        import json
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name=str(i), source={}) for i in range(2)]
            sources = [candidate(), candidate()]
            sources[1]['experiment_id'] = 'other-source'
            plans = [create_comparison(folder, source, roles=('learned',), opening_lines=lines, max_plies=1, screening=True) for source in sources]
            bundle = Path(folder) / 'data/learning-setup/group'; bundle.mkdir(parents=True)
            data = dict(format_version=1, purpose='screening', sources=sources,
                        work=[dict(path=str(p), baseline='stable') for p in plans], planned_games=8)
            data['identity'] = digest(data); write_json_atomic(bundle / 'snapshot.json', data)
            executor = ManualExecutor(); app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            rows = app.learning.comparison_history.entries
            index = next(i for i, row in enumerate(rows) if row['path'] == bundle)
            click('learning_history_open:' + str(index)); executor.finish(); app.render()
            self.assertEqual(app.learning.page, 'history_bundle')
            click('learning_bundle_resume')
            self.assertEqual(app.batch.snapshot()['requested_games'], 8)
            executor.finish(); self.assertEqual(app.batch.snapshot()['status'], 'completed')
            from engine.learning.comparison import comparison_report
            self.assertTrue(all(comparison_report(p)['baselines']['stable']['status'] == 'completed' for p in plans))
            app.close()
    def test_saved_record_name_survives_reopening(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            path = create_comparison(folder, candidate())
            executor = ManualExecutor(); app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            click('learning_history_open:0'); executor.finish(); app.render()
            click('learning_saved_rename')
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
            app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='很長的比較紀錄名稱供辨識與再次查找'))
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
            click('learning_compare_back')
            with patch.object(app, 'button', wraps=app.button) as buttons: app.render()
            self.assertTrue(any('很長的比較紀錄名稱' in str(call.args[1]) for call in buttons.call_args_list))
            self.assertEqual(app.learning.saved_state['names'][str(path)], '很長的比較紀錄名稱供辨識與再次查找')
            app.close()

    def test_bundle_rejects_duplicate_source_and_missing_candidate(self):
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        from ui.comparison_history_view import load_bundle
        with tempfile.TemporaryDirectory() as folder:
            sources = [candidate(), candidate()]; sources[1]['experiment_id'] = 'other-source'
            plans = [create_screening(folder, sources[0]) for _ in range(2)]
            bundle = Path(folder) / 'data/learning-setup/broken'; bundle.mkdir(parents=True)
            data = dict(format_version=1, purpose='screening', sources=sources,
                        work=[dict(path=str(p), baseline='stable') for p in plans], planned_games=32)
            data['identity'] = digest(data); write_json_atomic(bundle / 'snapshot.json', data)
            with self.assertRaises(ValueError): load_bundle(bundle)
    def test_record_disappearing_after_list_load_can_be_bypassed(self):
        import shutil
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            good = create_comparison(folder, candidate()); gone = create_comparison(folder, candidate())
            executor = ManualExecutor(); app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            rows = app.learning.comparison_history.entries
            shutil.rmtree(gone)
            index = next(i for i, row in enumerate(rows) if row['path'] == gone)
            click('learning_history_open:'+str(index)); executor.finish(); app.render()
            self.assertIn(str(gone), app.learning.page_load_error)
            click('learning_loading_back')
            index = next(i for i, row in enumerate(rows) if row['path'] == good)
            click('learning_history_open:'+str(index)); executor.finish(); app.render()
            self.assertEqual(app.learning.comparison.path, good)
            app.close()
    def test_slow_bundle_validation_keeps_navigation_and_stop_available(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        from engine.learning.comparison_setup import load_saved_setup
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)), ThreadPoolExecutor(1) as executor:
            lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
            plan = create_comparison(folder, candidate(), roles=('learned',), opening_lines=lines, max_plies=1, screening=True)
            bundle = Path(folder) / 'data/learning-setup/group'; bundle.mkdir(parents=True)
            data = dict(format_version=1, purpose='screening', sources=[candidate()], work=[dict(path=str(plan), baseline='stable')], planned_games=2)
            data['identity'] = digest(data); write_json_atomic(bundle / 'snapshot.json', data)
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor); app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); app.learning.page_loading.result(timeout=30); app.render()
            click('learning_inventory_history'); app.learning.page_loading.result(timeout=30); app.render()
            index = next(i for i, row in enumerate(app.learning.comparison_history.entries) if row['path'] == bundle)
            click('learning_history_open:'+str(index)); app.learning.page_loading.result(timeout=30); app.render()
            entered, release = threading.Event(), threading.Event()
            def delayed(path):
                entered.set(); self.assertTrue(release.wait(10)); return load_saved_setup(path)
            try:
                with patch('engine.learning.comparison_setup.load_saved_setup', side_effect=delayed):
                    click('learning_bundle_resume'); self.assertTrue(entered.wait(10))
                    click('learning_comparison_return')
                    self.assertEqual(app.mode, 'learning')
                    click('learning_task_stop'); release.set(); app.batch.future.result(timeout=30)
                    self.assertEqual(app.batch.snapshot()['status'], 'stopped')
                    from engine.learning.comparison import comparison_report
                    self.assertEqual(comparison_report(plan)['baselines']['stable']['status'], 'not-started')
            finally:
                release.set(); app.close()
