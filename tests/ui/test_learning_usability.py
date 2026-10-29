"""資料選擇、跨教師成果與工作獨立性的回歸檢查。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import Future
from types import SimpleNamespace
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor
from tests.test_learning_dataset import pgn_games
from engine.learning.dataset import create_dataset


class UsabilityTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch('apps.chess_application.PROJECT_ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=ManualExecutor())
        self.addCleanup(pygame.quit)
        self.addCleanup(self.app.close)
        self.app.new_setup('learning')

    def test_error_and_dataset_summary_have_distinct_lines(self):
        source = self.root / 'games.pgn'
        source.write_text(pgn_games(8), encoding='utf-8')
        path = create_dataset(self.root / 'data/learning', source)
        view = self.app.learning
        view.open(path)
        view.page = 'data'
        view.message = '測試讀取失敗'
        with patch.object(self.app, 'text', wraps=self.app.text) as draw:
            self.app.render()
        error = next(c for c in draw.call_args_list if c.args[0] == view.message)
        summary = next(c for c in draw.call_args_list if '/500 盤' in c.args[0])
        self.assertNotEqual(error.args[2], summary.args[2])

    def test_random_seed_and_source_survive_reopening(self):
        view = self.app.learning
        view.page = 'data'
        self.app.dispatch('learning_source')
        before = view.seed
        self.app.dispatch('learning_seed_random')
        self.assertNotEqual(before, view.seed)
        from ui.learning_view import LearningView
        reopened = LearningView(self.root)
        self.assertEqual(reopened.source, 'local')
        self.assertEqual(reopened.seed, view.seed)

    def test_other_work_does_not_disable_training_button(self):
        view = self.app.learning
        future = Future()
        run = SimpleNamespace(future=future, stop=lambda: future.set_result(None), snapshot=lambda: {})
        view.teacher.run = run
        view.page = 'groups'
        self.app.buttons = []
        self.app.button('learning_groups_new', '開始', (0, 0, 100, 30))
        self.assertTrue(self.app.buttons[-1].enabled)

    def test_picker_cancel_preserves_path_and_rename_preserves_config(self):
        view = self.app.learning
        view.page, view.source, view.local_path = 'data', 'local', 'before.pgn'
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askopenfilename', return_value=''):
            self.app.dispatch('learning_source_pick')
        self.assertEqual(view.local_path, 'before.pgn')
        from engine.storage.batch_storage import write_json_atomic
        import json
        config = self.root / 'configs/evaluation/user.json'
        config.parent.mkdir(parents=True)
        original = Path(__file__).resolve().parents[2] / 'configs/evaluation/stable.json'
        write_json_atomic(config, json.loads(original.read_text(encoding='utf-8')))
        before = config.read_bytes()
        view.inventory.open_first(view.root); view.page = 'inventory'
        self.app.dispatch('learning_inventory_candidate:0')
        self.app.dispatch('learning_inventory_rename')
        view.inventory.draft = '我的穩健設定'
        view.input(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
        view.inventory.open_first(view.root)
        self.assertEqual(view.inventory.report['candidates'][0]['name'], '我的穩健設定')
        self.assertEqual(config.read_bytes(), before)


class TeacherSelectionTest(unittest.TestCase):
    from tests.test_weight_training import TrainingFlowTest
    setUp = TrainingFlowTest.setUp

    def test_reuse_and_cross_teacher_training_while_another_label_runs(self):
        from engine.learning.labeling import create_labeling, load_labeling, LabelRun
        from engine.learning.group_training import load_group_training
        saved = load_labeling(self.labels)
        dataset = Path(saved['snapshot']['dataset_path'])
        pilot = Path(saved['snapshot']['pilot_path'])
        self.assertEqual(create_labeling(dataset, pilot, reuse=True), self.labels)
        other = create_labeling(dataset, pilot)
        self.assertNotEqual(other, self.labels)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
        self.addCleanup(app.close)
        app.mode = 'learning'; view = app.learning; view.root = self.root / 'data'
        view.open(dataset)
        view.labels.dataset, view.labels.pilot = dataset, pilot
        view.labels.load(other)
        view.labels.run = LabelRun(other, executor)
        running = view.labels.run
        app.dispatch('learning_choose_training_labels'); executor.finish(); app.render()
        index = next(i for i, row in enumerate(view.label_choices.entries) if row['path'] == self.labels)
        app.dispatch(f'learning_label_choice:{index}'); executor.finish(); app.render()
        self.assertEqual(view.group_training.labels, self.labels)
        app.dispatch('learning_groups_new')
        training = view.group_training.run
        self.assertIsNotNone(training)
        self.assertFalse(running.future.done())
        # 真正執行學習工作，確認來源選擇沒有借用執行中的標記。
        executor.finish()
        self.assertEqual(load_group_training(training.path)['snapshot']['label_path'], str(self.labels.resolve()))
        view.close()
        self.assertTrue(running._stop.is_set())
