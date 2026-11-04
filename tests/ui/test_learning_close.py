from tests.helpers.learning_ui import choose_labels
"""關閉學習工作、保存完成及手動恢復的事件測試。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset
from tests.helpers.executors import ManualExecutor
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games
try:
    import psutil
except ImportError:
    psutil = None


class LearningCloseTest(unittest.TestCase):
    def test_pilot_close_cancel_and_confirm_wait_for_saved_stop(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
            dataset = create_dataset(root / 'data/learning', source)
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close)
                app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
                app.learning.teacher.command = make_engine(root)
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('learning_pilot_start'); run = app.learning.teacher.run
                app.handle_event(pygame.event.Event(pygame.QUIT))
                self.assertEqual(app.confirm_action, 'quit')
                self.assertTrue(app.running)
                click('cancel')
                self.assertFalse(run.future.done())
                self.assertIs(app.learning.teacher.run, run)
                app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
                self.assertTrue(app.running)
                self.assertEqual(app.pending_leave, 'quit')
                with patch.object(app, 'text', wraps=app.text) as draw:
                    app.render()
                self.assertTrue(any('正在停止並保存' in str(call.args[0]) for call in draw.call_args_list))
                app.tick(); self.assertTrue(app.running)
                executor.finish(); app.tick()
                self.assertFalse(app.running)
                self.assertEqual(run.snapshot()['status'], 'stopped')
                self.assertTrue((run.path / 'status.json').exists())
                app.close(); app = ChessApplication(app.screen, executor=executor)
                self.addCleanup(app.close)
                click('mode:learning'); app.learning.recovery_future.result(timeout=15); app.render()
                click('learning_recovery_list')
                index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == run.path)
                click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
                self.assertEqual(app.learning.page, 'teacher')
                self.assertEqual(app.learning.teacher.path, run.path)
                self.assertFalse(app.learning.active())
                self.assertTrue(next(b for b in app.buttons if b.action == 'learning_pilot_start').enabled)
                self.assertFalse(any('pilot_resume' in b.action for b in app.buttons))
                with patch.object(app, 'text', wraps=app.text) as draw:
                    app.render()
                self.assertTrue(any('重新量測' in str(call.args[0]) for call in draw.call_args_list))
                from engine.storage.batch_storage import write_json_atomic
                import json
                saved = json.loads((run.path / 'status.json').read_text(encoding='utf-8'))
                saved.update(status='failed', error='測試失敗')
                write_json_atomic(run.path / 'status.json', saved)
                app.close(); app = ChessApplication(app.screen, executor=executor)
                self.addCleanup(app.close)
                click('mode:learning'); app.learning.recovery_future.result(timeout=15); app.render()
                click('learning_recovery_list')
                index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == run.path)
                click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
                self.assertEqual(app.learning.teacher.state['status'], 'failed')
                app.learning.teacher.command = make_engine(root)
                click('learning_pilot_start'); replacement = app.learning.teacher.run
                self.assertNotEqual(replacement.path, run.path)
                executor.finish(); app.render()
                self.assertEqual(replacement.snapshot()['status'], 'completed')
                self.assertEqual(app.learning.path, dataset)

class UnfinishedWorkTest(unittest.TestCase):
    from tests import test_weight_training as fixtures
    setUp = fixtures.TrainingFlowTest.setUp

    def test_reopen_lists_saved_work_and_only_runs_after_manual_resume(self):
        from engine.learning.labeling import create_labeling
        from engine.learning.group_training import create_group_training
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        from tests.test_learned_comparison import candidate
        dataset = self.labels.parents[1]
        pilot = next((dataset / 'teacher-pilots').iterdir())
        unfinished_label = create_labeling(dataset, pilot)
        training = create_group_training(self.labels, ['mobility'])
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
        comparison = create_comparison(self.root, candidate(), roles=['learned'], opening_lines=lines, max_plies=1)
        run_evaluation_comparison(**comparison_options(comparison, 'material'), control=lambda: False)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            # 此測試資料集位於臨時專案 data 下。
            app.learning.root = dataset.parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning'); app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            found = {item['path'] for item in app.learning.recovery_entries}
            self.assertTrue({unfinished_label, training, comparison}.issubset(found))
            self.assertFalse(app.learning.active()); self.assertIsNone(app.batch)
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == comparison)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.comparison.path, comparison)
            self.assertIsNone(app.batch)
            click('learning_compare_start')
            self.assertIn('resume_path', app.batch.options)
            click('stop'); executor.finish(); app.render()
            click('learning_comparison_return')
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == training)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.page, 'groups')
            self.assertEqual(app.learning.group_training.path, training)
            self.assertEqual(app.learning.saved_state['selected']['data'], str(dataset))
            self.assertEqual(app.learning.saved_state['selected'][f'groups:{self.labels}'], str(training))
            self.assertFalse(app.learning.active()); self.assertTrue(app.batch.future.done())
            click('learning_groups_resume')
            self.assertTrue(app.learning.group_training.active())
    def test_restoring_work_ignores_older_dataset_read(self):
        import json
        from engine.learning.group_training import create_group_training
        dataset = self.labels.parents[1]
        source = self.root / 'older.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
        old_data = create_dataset(self.root / 'data', source)
        training = create_group_training(self.labels, ['mobility'])
        (self.root / 'data/learning-ui.json').write_text(json.dumps({'selected': {'data': str(old_data)}}), encoding='utf-8')
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = dataset.parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning'); old_future = app.learning.loading
            app.learning.recovery_future.result(timeout=30); app.render(); click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == training)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.path, dataset)
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is old_future)); app.render()
            self.assertEqual(app.learning.path, dataset)
            self.assertEqual(app.learning.group_training.path, training)
    def test_group_training_close_cancel_then_stop_saves_progress(self):
        dataset = self.labels.parents[1]
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            choose_labels(app, self.labels, training=True)
            click('learning_groups_new'); run = app.learning.group_training.run
            app.render()
            self.assertTrue(all('未選取' not in next(b.label for b in app.buttons if b.action == 'learning_groups_select:' + group)
                                for group in run.groups))
            click('learning_nav_data')
            self.assertIs(app.learning.active_task()[2], run)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('cancel')
            self.assertIs(app.learning.group_training.run, run)
            self.assertFalse(run.future.done())
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            self.assertTrue(app.running)
            executor.finish(); app.tick()
            self.assertFalse(app.running)
            from engine.learning.group_training import load_group_training
            saved = load_group_training(run.path)
            self.assertIn(saved['status'], ('stopped', 'interrupted'))
            original = (run.path / 'snapshot.json').read_bytes()
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.learning.root = dataset.parent; app.new_setup('learning')
            app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == run.path)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.path, dataset)
            self.assertEqual(app.learning.group_training.path, run.path)
            click('learning_groups_resume'); executor.finish(); app.render()
            self.assertEqual(load_group_training(run.path)['status'], 'completed')
            self.assertEqual((run.path / 'snapshot.json').read_bytes(), original)
            app.close()
    def test_comparison_close_cancel_then_stop_waits_for_saved_batch(self):
        from engine.learning.comparison import create_comparison
        from tests.test_learned_comparison import candidate
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
        plan = create_comparison(self.root, candidate(), roles=['learned'], opening_lines=lines, max_plies=1)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'
            app.learning.comparison.open_plan(plan); app.learning.page = 'comparison'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_compare_start'); run = app.batch
            click('learning_comparison_return'); click('learning_nav_data')
            self.assertIs(app.batch, run)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('cancel')
            self.assertIs(app.batch, run); self.assertFalse(run.future.done())
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            self.assertTrue(app.running); self.assertEqual(app.pending_leave, 'quit')
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is run.future)); app.tick()
            self.assertFalse(app.running)
            from engine.learning.comparison import comparison_report
            self.assertEqual(comparison_report(plan)['baselines']['material']['status'], 'stopped')
            original = (plan / 'snapshot.json').read_bytes()
            app.close(); app = ChessApplication(app.screen, executor=executor); app.new_setup('learning')
            app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == plan)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.comparison.path, plan)
            click('learning_compare_start'); resumed = app.batch
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is resumed.future)); app.render()
            self.assertEqual(comparison_report(plan)['baselines']['material']['status'], 'completed')
            self.assertEqual((plan / 'snapshot.json').read_bytes(), original)
            app.close()
    def test_labeling_close_cancel_then_stop_saves_committed_records(self):
        dataset = self.labels.parents[1]
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            choose_labels(app, self.labels)
            click('learning_labels_recreate'); run = app.learning.labels.run
            before = {p.name: p.read_bytes() for p in (run.path / 'records').glob('*.json')}
            click('learning_nav_data')
            self.assertIs(app.learning.active_task()[2], run)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('cancel')
            self.assertIs(app.learning.labels.run, run); self.assertFalse(run.future.done())
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            self.assertTrue(app.running)
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is run.future)); app.tick()
            self.assertFalse(app.running)
            from engine.learning.labeling import load_labeling
            state = load_labeling(run.path)
            self.assertEqual(state['status'], 'stopped')
            for name, content in before.items(): self.assertEqual((run.path / 'records' / name).read_bytes(), content)
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.learning.root = dataset.parent; app.new_setup('learning')
            app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == run.path)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.path, dataset)
            self.assertEqual(app.learning.labels.path, run.path)
            click('learning_labels_resume'); executor.finish(); app.render(); executor.finish(); app.render()
            self.assertEqual(load_labeling(run.path)['status'], 'completed')
            for name, content in before.items(): self.assertEqual((run.path / 'records' / name).read_bytes(), content)
            app.close()
    def test_failed_labeling_can_be_manually_resumed_with_committed_records_intact(self):
        from engine.learning.labeling import create_labeling, load_labeling
        from engine.storage.batch_storage import write_json_atomic
        dataset = self.labels.parents[1]
        pilot = next((dataset / 'teacher-pilots').iterdir())
        failed = create_labeling(dataset, pilot)
        records = {p.name: p.read_bytes() for p in (failed / 'records').glob('*.json')}
        write_json_atomic(failed / 'status.json', dict(status='failed', path=str(failed), elapsed_seconds=1, error='測試失敗'))
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = dataset.parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning'); app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == failed)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.labels.state['status'], 'failed')
            click('learning_labels_resume'); executor.finish(); app.render(); executor.finish(); app.render()
            self.assertTrue(load_labeling(failed)['ready'])
            for name, content in records.items(): self.assertEqual((failed / 'records' / name).read_bytes(), content)
    def test_incomplete_combination_batch_opens_original_snapshot_for_resume(self):
        from engine.learning.group_training import create_group_training, run_group_training
        from engine.learning.combination_batch import create_combination_batch
        dataset = self.labels.parents[1]
        group = create_group_training(self.labels, ['mobility', 'king-safety']); run_group_training(group)
        batch = create_combination_batch(group, [['mobility', 'king-safety']])
        broken = self.labels / 'combinations' / 'broken'; broken.mkdir(parents=True)
        (broken / 'snapshot.json').write_text('{broken', encoding='utf-8')
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = dataset.parent
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('mode:learning'); app.learning.recovery_future.result(timeout=30); app.render()
            click('learning_recovery_list')
            index = next(i for i, item in enumerate(app.learning.recovery_entries) if item['path'] == batch)
            click(f'learning_recovery_open:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.combination.batch_path, batch)
            self.assertFalse(app.learning.active())
            click('learning_combination_batch_resume')
            self.assertEqual(app.learning.combination.run.path, batch)
    @unittest.skipUnless(psutil, '未安裝 psutil')
    def test_quit_interrupts_real_teacher_process_before_exit(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        dataset = self.labels.parents[1]
        command = make_engine(self.root); script = Path(command[1])
        script.write_text(script.read_text(encoding='utf-8').replace('  import chess', '  import time; time.sleep(60)\n  import chess'), encoding='utf-8')
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(max_workers=1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            app.learning.teacher.command = command
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_pilot_start')
            deadline = time.monotonic() + 15; matches = []
            while time.monotonic() < deadline:
                matches = []
                for process in psutil.Process().children(recursive=True):
                    try:
                        if str(script) in ' '.join(process.cmdline()): matches.append(process)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if matches: break
                time.sleep(.02)
            self.assertTrue(matches)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            deadline = time.monotonic() + 30
            while app.running and time.monotonic() < deadline:
                app.tick(); time.sleep(.02)
            self.assertFalse(app.running)
            self.assertFalse(any(p.is_running() for p in matches))
    def test_quit_confirmation_blocks_background_task_stop(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
            dataset = create_dataset(root / 'data/learning', source); executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                self.addCleanup(app.close); app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
                app.learning.teacher.command = make_engine(root)
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('learning_pilot_start'); run = app.learning.teacher.run
                app.render(); background = next(b.rect.center for b in app.buttons if b.action == 'learning_task_stop')
                app.handle_event(pygame.event.Event(pygame.QUIT))
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=background, button=1))
                click('cancel')
                executor.finish()
                self.assertEqual(run.snapshot()['status'], 'completed')
    def test_cancel_close_allows_learning_task_to_finish(self):
        dataset = self.labels.parents[1]
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            choose_labels(app, self.labels, training=True)
            for group in ('piece-square', 'pawn', 'king-safety', 'coordination'):
                click('learning_groups_toggle:' + group)
            click('learning_groups_new'); run = app.learning.group_training.run
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('cancel')
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is run.future)); app.render()
            self.assertEqual(app.learning.group_training.state['status'], 'completed')
    def test_cancel_close_allows_comparison_to_finish(self):
        from engine.learning.comparison import create_comparison, comparison_report
        from tests.test_learned_comparison import candidate
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
        plan = create_comparison(self.root, candidate(), roles=['learned'], opening_lines=lines, max_plies=1)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'
            app.learning.comparison.open_plan(plan); app.learning.page = 'comparison'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_compare_start'); run = app.batch
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('cancel')
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is run.future))
            self.assertEqual(comparison_report(plan)['baselines']['material']['status'], 'completed')
    @unittest.skipUnless(psutil, '未安裝 psutil')
    def test_quit_waits_for_real_solver_process_cleanup(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        dataset = self.labels.parents[1]
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(max_workers=1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            choose_labels(app, self.labels, training=True)
            for group in ('piece-square', 'pawn', 'king-safety', 'coordination'):
                click('learning_groups_toggle:' + group)
            click('learning_groups_new'); run = app.learning.group_training.run
            deadline = time.monotonic() + 30; pid = None
            while time.monotonic() < deadline and not run.future.done():
                pid = run.snapshot().get('worker_pid')
                if pid: break
                time.sleep(.005)
            self.assertIsNotNone(pid)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            deadline = time.monotonic() + 30
            while app.running and time.monotonic() < deadline:
                app.tick(); time.sleep(.01)
            self.assertFalse(app.running)
            self.assertTrue(run.future.done())
            self.assertFalse(psutil.pid_exists(pid))
    def test_quit_waits_for_real_comparison_workers_to_exit(self):
        import multiprocessing
        import time
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.comparison import create_comparison
        from tests.test_learned_comparison import candidate
        lines = [dict(initial_fen=fen, moves_uci=[], name=str(i), source={}) for i, fen in enumerate((
            '7k/8/8/8/8/8/P7/K7 w - - 0 1', '7k/8/8/8/8/8/1P6/K7 w - - 0 1'))]
        plan = create_comparison(self.root, candidate(), opening_lines=lines, max_plies=10)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(max_workers=1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.mode = 'learning'
            app.learning.comparison.open_plan(plan); app.learning.page = 'comparison'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            before = {p.pid for p in multiprocessing.active_children()}
            click('learning_compare_start'); run = app.batch
            deadline = time.monotonic() + 30; pids = set()
            while time.monotonic() < deadline and not run.future.done():
                pids = {p.pid for p in multiprocessing.active_children()} - before
                if pids: break
                time.sleep(.01)
            self.assertTrue(pids)
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            deadline = time.monotonic() + 30
            while app.running and time.monotonic() < deadline:
                app.tick(); time.sleep(.01)
            self.assertFalse(app.running); self.assertTrue(run.future.done())
            self.assertFalse(pids & {p.pid for p in multiprocessing.active_children()})
    def test_scan_failure_is_visible_and_can_be_retried(self):
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            with patch('ui.learning_view.unfinished', side_effect=OSError('清單讀取失敗')):
                click('mode:learning')
                try: app.learning.recovery_future.result(timeout=15)
                except OSError: pass
                app.render()
            click('learning_recovery_list')
            with patch.object(app, 'text', wraps=app.text) as draw: app.render()
            self.assertTrue(any('清單讀取失敗' in str(call.args[0]) for call in draw.call_args_list))
            click('learning_recovery_retry'); app.learning.recovery_future.result(timeout=15); app.render()
            self.assertFalse(app.learning.recovery_error)
    def test_unfinished_scan_verifies_records_instead_of_trusting_stale_status(self):
        from engine.learning.labeling import create_labeling
        from engine.storage.batch_storage import write_json_atomic
        dataset = self.labels.parents[1]; pilot = next((dataset / 'teacher-pilots').iterdir())
        path = create_labeling(dataset, pilot)
        write_json_atomic(path / 'status.json', dict(status='completed', path=str(path), elapsed_seconds=1, error=''))
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = dataset.parent
            app.new_setup('learning'); app.learning.recovery_future.result(timeout=30); app.render()
            item = next(item for item in app.learning.recovery_entries if item['path'] == path)
            self.assertEqual(item['status'], 'interrupted')
    def test_unfinished_scan_keeps_valid_work_when_other_records_are_damaged(self):
        import json
        from engine.learning.group_training import create_group_training
        dataset = self.labels.parents[1]
        valid = create_group_training(self.labels, ['mobility'])
        missing = create_group_training(self.labels, ['pawn']); (missing / 'status.json').unlink()
        broken = self.labels / 'group-training' / 'broken'; broken.mkdir()
        (broken / 'status.json').write_text(json.dumps({'status': 'stopped'}), encoding='utf-8')
        from engine.learning.teacher import digest
        snapshot = {'format_version': 1, 'kind': 'independent-groups'}
        snapshot['identity'] = digest(snapshot)
        (broken / 'snapshot.json').write_text(json.dumps(snapshot), encoding='utf-8')
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = dataset.parent
            app.new_setup('learning'); app.learning.recovery_future.result(timeout=30); app.render()
            found = {item['path']: item['status'] for item in app.learning.recovery_entries}
            self.assertEqual(found[valid], 'ready')
            self.assertEqual(found[missing], 'unavailable')
            self.assertEqual(found[broken], 'unavailable')
    def test_broken_comparison_does_not_hide_other_unfinished_comparisons(self):
        from engine.learning.comparison import create_comparison, comparison_options, comparison_report
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        from tests.test_learned_comparison import candidate
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
        valid = create_comparison(self.root, candidate(), roles=['learned'], opening_lines=lines, max_plies=1)
        broken = create_comparison(self.root, candidate(), roles=['learned'], opening_lines=lines, max_plies=1)
        run_evaluation_comparison(**comparison_options(valid, 'material'), control=lambda: False)
        pygame.init(); self.addCleanup(pygame.quit); executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close); app.learning.root = self.labels.parents[2]
            def read(path):
                if Path(path) == broken: raise IndexError('缺少資料')
                return comparison_report(path)
            with patch('engine.learning.unfinished.comparison_report', side_effect=read):
                app.new_setup('learning'); app.learning.recovery_future.result(timeout=30); app.render()
            found = {item['path']: item['status'] for item in app.learning.recovery_entries}
            self.assertEqual(found[broken], 'unavailable')
            self.assertEqual(found[valid], 'stopped')
