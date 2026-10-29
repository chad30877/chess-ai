"""保存成果清單、名稱及身分選擇的應用程式事件。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.dataset import create_dataset, load_dataset
from tests.helpers.executors import ManualExecutor
from tests.test_learning_dataset import pgn_games


class SavedSelectionTest(unittest.TestCase):
    def test_rename_and_reopen_older_dataset_preserves_identity(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'
            source.write_text(pgn_games(8), encoding='utf-8')
            older = create_dataset(root / 'data/learning', source)
            create_dataset(root / 'data/learning', source)
            before = (older / 'dataset.json').read_bytes()
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning'); click('learning_nav_data'); click('learning_saved_list')
                index = next(i for i, entry in enumerate(app.learning.saved_entries) if entry == older)
                click(f'learning_saved_select:{index}'); executor.finish(); app.render()
                self.assertEqual(app.learning.path, older)
                click('learning_saved_rename')
                app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
                app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='我的成果'))
                app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
                app.close(); app = ChessApplication(app.screen, executor=executor)
                click('mode:learning'); click('learning_nav_data'); executor.finish(); app.render()
                self.assertEqual(app.learning.path, older)
                self.assertEqual(app.learning.saved_name(older, '資料'), '我的成果')
                self.assertEqual((older / 'dataset.json').read_bytes(), before)
                self.assertEqual(app.learning.data, load_dataset(older))
                app.close()

class SavedTeacherSelectionTest(unittest.TestCase):
    from tests import test_weight_training as fixtures
    setUp = fixtures.TrainingFlowTest.setUp

    def test_selected_pilot_is_restored_after_newer_one_appears(self):
        import shutil
        dataset = self.labels.parents[1]
        older = next((dataset / 'teacher-pilots').iterdir())
        newer = older.parent / 'newer'; shutil.copytree(older, newer)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_saved_list')
            index = app.learning.saved_entries.index(older)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.teacher.path, older)
            later = older.parent / 'later'; shutil.copytree(older, later)
            status = later / 'status.json'; os.utime(status, (status.stat().st_mtime + 60, status.stat().st_mtime + 60))
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'data'
            self.assertEqual(app.learning.teacher.path, older)
            app.close(); shutil.rmtree(older)
            app = ChessApplication(app.screen, executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            self.assertEqual(app.learning.teacher.path, older)
            self.assertIn(str(older), app.learning.teacher.message)
            click('learning_saved_list'); index = app.learning.saved_entries.index(newer)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.teacher.path, newer)
            app.close()
    def test_older_label_selection_survives_newer_unfinished_work(self):
        from engine.learning.labeling import create_labeling
        dataset = self.labels.parents[1]
        pilot = next((dataset / 'teacher-pilots').iterdir())
        create_labeling(dataset, pilot)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_saved_list')
            index = app.learning.saved_entries.index(self.labels)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            create_labeling(dataset, pilot)
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            click('learning_labels'); executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, self.labels)
            self.assertTrue(app.learning.labels.state['ready'])
            app.close()
    def test_label_from_another_pilot_is_not_used_as_current_source(self):
        import shutil
        dataset = self.labels.parents[1]
        pilot = next((dataset / 'teacher-pilots').iterdir())
        other = pilot.parent / 'other'; shutil.copytree(pilot, other)
        os.utime(other / 'status.json', (pilot.stat().st_mtime + 60, pilot.stat().st_mtime + 60))
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            app.learning.teacher.load(other)
            app.render(); button = next(b for b in app.buttons if b.action == 'learning_labels')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            executor.finish(); app.render()
            self.assertFalse(app.learning.labels.state.get('ready'))
            self.assertIsNone(app.learning.labels.path)
            self.assertTrue(next(b for b in app.buttons if b.action == 'learning_labels_new').enabled)
            app.close()
    def test_older_training_selection_survives_newer_unfinished_work(self):
        from engine.learning.training import create_training
        dataset = self.labels.parents[1]
        older = create_training(self.labels)
        create_training(self.labels)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_training'); executor.finish(); app.render()
            click('learning_saved_list'); index = app.learning.saved_entries.index(older)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            create_training(self.labels)
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            click('learning_labels'); executor.finish(); app.render()
            click('learning_training'); executor.finish(); app.render()
            self.assertEqual(app.learning.training.path, older)
            app.close()
    def test_group_and_combination_lists_restore_selected_results(self):
        from engine.learning.group_training import create_group_training, run_group_training
        from engine.learning.combination_training import create_combination
        dataset = self.labels.parents[1]
        group = create_group_training(self.labels, ['mobility', 'king-safety']); run_group_training(group)
        create_group_training(self.labels, ['mobility'])
        first = create_combination(group, ['mobility', 'king-safety'])
        create_combination(group, ['mobility', 'king-safety'])
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_groups'); executor.finish(); app.render()
            click('learning_saved_list'); index = app.learning.saved_entries.index(group)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.group_training.path, group)
            frozen = group / 'groups' / 'mobility' / 'frozen.json'
            before_snapshot = (group / 'snapshot.json').read_bytes(); before_frozen = frozen.read_bytes()
            click('learning_saved_rename')
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
            app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='已完成群組'))
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
            self.assertEqual((group / 'snapshot.json').read_bytes(), before_snapshot)
            self.assertEqual(frozen.read_bytes(), before_frozen)
            from engine.learning.group_training import load_group_training
            self.assertEqual(load_group_training(group)['status'], 'completed')
            click('learning_combinations'); executor.finish(); app.render()
            click('learning_saved_list'); index = app.learning.saved_entries.index(first)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.combination.path, first)
            app.close(); app = ChessApplication(app.screen, executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            click('learning_labels'); executor.finish(); app.render()
            click('learning_groups'); executor.finish(); app.render()
            self.assertEqual(app.learning.group_training.path, group)
            self.assertEqual(app.learning.saved_name(group, '單群組學習'), '已完成群組')
            click('learning_combinations'); executor.finish(); app.render()
            self.assertEqual(app.learning.combination.path, first)
            app.close()
    def test_same_display_name_and_missing_remembered_dataset_can_be_reselected(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            import shutil
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
            first = create_dataset(root / 'data/learning', source)
            second = create_dataset(root / 'data/learning', source)
            originals = {p: (p / 'dataset.json').read_bytes() for p in (first, second)}
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning'); click('learning_nav_data')
                for path in (first, second):
                    click('learning_saved_list'); index = app.learning.saved_entries.index(path)
                    click(f'learning_saved_select:{index}'); executor.finish(); app.render()
                    self.assertEqual(app.learning.path, path)
                    click('learning_saved_rename')
                    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
                    app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='同名'))
                    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
                    self.assertEqual((path / 'dataset.json').read_bytes(), originals[path])
                app.close(); shutil.rmtree(second)
                app = ChessApplication(app.screen, executor=executor)
                click('mode:learning'); click('learning_nav_data'); executor.finish(); app.render()
                self.assertEqual(app.learning.path, second)
                self.assertIsNone(app.learning.data)
                self.assertIn(str(second), app.learning.message)
                click('learning_saved_list'); index = app.learning.saved_entries.index(first)
                click(f'learning_saved_select:{index}'); executor.finish(); app.render()
                self.assertEqual(app.learning.path, first)
                self.assertEqual(app.learning.saved_name(first, '資料'), '同名')
                app.close()
    def test_long_named_dataset_list_can_reach_last_page(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(3), encoding='utf-8')
            datasets = [create_dataset(root / 'data/learning', source) for _ in range(10)]
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode((900, 768)), executor=executor)
                app.learning.saved_state['names'] = {str(p): '長中文名稱' * 12 for p in datasets}
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('mode:learning'); click('learning_nav_data'); click('learning_saved_list'); click('learning_saved_next')
                target = app.learning.saved_entries[-1]
                click('learning_saved_select:9'); executor.finish(); app.render()
                self.assertEqual(app.learning.path, target)
                self.assertIsNotNone(app.learning.data)
                app.close()
    def test_active_dataset_run_cannot_switch_saved_dataset(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
            saved = create_dataset(root / 'data/learning', source)
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                app.mode = 'learning'; app.learning.page = 'data'; app.learning.source = 'local'; app.learning.local_path = str(source)
                def click(action):
                    app.render(); button = next(b for b in app.buttons if b.action == action)
                    self.assertTrue(button.enabled, action)
                    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                click('learning_create'); run = app.learning.run
                app.render(); button = next(b for b in app.buttons if b.action == 'learning_saved_list')
                self.assertFalse(button.enabled)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                self.assertFalse(app.learning.saved_list)
                self.assertIs(app.learning.run, run)
                app.close()
    def test_changing_pilot_while_labeling_preserves_running_task_context(self):
        import shutil
        dataset = self.labels.parents[1]
        original = next((dataset / 'teacher-pilots').iterdir())
        other = original.parent / 'other'; shutil.copytree(original, other)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.teacher.load(original); app.learning.page = 'data'
            app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_labels_new'); run = app.learning.labels.run
            click('learning_teacher'); click('learning_saved_list')
            index = app.learning.saved_entries.index(other)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.teacher.path, other)
            click('learning_task_return')
            self.assertEqual(app.learning.teacher.path, original)
            self.assertIs(app.learning.labels.run, run)
            self.assertFalse(run.future.done())
            app.close()
    def test_changing_label_while_training_preserves_running_task_context(self):
        from engine.learning.labeling import create_labeling
        dataset = self.labels.parents[1]
        pilot = next((dataset / 'teacher-pilots').iterdir())
        other = create_labeling(dataset, pilot)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_saved_list'); index = app.learning.saved_entries.index(self.labels)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            click('learning_groups'); executor.finish(); app.render()
            click('learning_groups_new'); run = app.learning.group_training.run
            self.assertFalse(run.future.done())
            click('learning_labels')
            if app.learning.labels.loading is not None: executor.finish()
            app.render()
            self.assertFalse(run.future.done())
            click('learning_saved_list'); index = app.learning.saved_entries.index(other)
            click(f'learning_saved_select:{index}'); executor.finish(); app.render()
            self.assertEqual(app.learning.labels.path, other)
            click('learning_task_return')
            self.assertEqual(app.learning.labels.path, self.labels)
            self.assertIs(app.learning.group_training.run, run)
            self.assertFalse(run.future.done())
            app.close()
    def test_new_dataset_receives_date_and_purpose_without_changing_snapshot(self):
        from datetime import datetime
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'games.pgn'; source.write_text(pgn_games(8), encoding='utf-8')
            executor = ManualExecutor()
            with patch('apps.chess_application.PROJECT_ROOT', root):
                app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
                app.mode = 'learning'; app.learning.page = 'data'; app.learning.source = 'local'; app.learning.local_path = str(source)
                app.render(); button = next(b for b in app.buttons if b.action == 'learning_create')
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                path = app.learning.run.path
                self.assertEqual(app.learning.saved_name(path, '資料'), datetime.now().strftime('%Y/%m/%d') + ' 資料')
                executor.finish(); app.render()
                self.assertEqual(app.learning.data, load_dataset(path))
                app.close()
    def test_finished_detached_task_does_not_replace_next_task_context(self):
        import shutil
        dataset = self.labels.parents[1]
        original = next((dataset / 'teacher-pilots').iterdir())
        other = original.parent / 'other'; shutil.copytree(original, other)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.open(dataset); app.learning.teacher.load(original); app.learning.page = 'teacher'
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_labels_new'); first = app.learning.labels.run
            click('learning_teacher'); click('learning_saved_list')
            click(f'learning_saved_select:{app.learning.saved_entries.index(other)}'); executor.finish(); app.render()
            executor.finish(next(i for i, job in enumerate(executor.jobs) if job[0] is first.future))
            click('learning_labels'); executor.finish(); app.render()
            click('learning_labels_new'); second = app.learning.labels.run
            click('learning_teacher'); click('learning_saved_list')
            click(f'learning_saved_select:{app.learning.saved_entries.index(original)}'); executor.finish(); app.render()
            click('learning_task_return')
            self.assertIs(app.learning.labels.run, second)
            self.assertEqual(app.learning.teacher.path, other)
            self.assertFalse(second.future.done())
            app.close()
