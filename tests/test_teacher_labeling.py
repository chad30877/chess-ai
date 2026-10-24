"""逐局面標記公開執行、恢復與正式學習資料閘門。"""
import tempfile
import unittest
import json
import os
from threading import Event
from unittest.mock import patch
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic
from pathlib import Path

from engine.learning.dataset import create_dataset, load_dataset
from engine.learning.teacher import run_pilot, choose_budget
from engine.learning.labeling import create_labeling, run_labeling, load_labeling, load_labeled_dataset
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games


class LabelingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'games.pgn'
        source.write_text(pgn_games(8), encoding='utf-8')
        self.dataset = create_dataset(self.root / 'data', source)
        self.data = load_dataset(self.dataset)
        self.command = make_engine(self.root)
        self.control = self.root / 'control'
        script = Path(self.command[1])
        code = script.read_text(encoding='utf-8')
        code = code.replace("  import chess", "  from pathlib import Path\n  import time\n  control=Path(__file__).with_name('control')\n  mode=control.read_text() if control.exists() else ''\n  if mode=='crash': raise RuntimeError('teacher crash')\n  if mode=='delay': time.sleep(.1)\n  if mode=='hang': time.sleep(60)\n  import chess")
        code = code.replace("  print('info depth 2 score cp 25 nodes '+line.split()[-1]+' pv '+best, flush=True)", "  score={'mate':'mate 3','bound':'cp 25 lowerbound','tb':'cp 21000','unknown':'wut 1'}.get(mode,'cp 25')\n  print('info depth 2 score '+score+' nodes '+line.split()[-1]+' pv '+best, flush=True)")
        code = code.replace("  print('info depth 1", "  if mode=='tbhit': print('info depth 1 tbhits 1', flush=True)\n  if mode=='tactics': best=next((m.uci() for m in board.legal_moves if m.promotion), next((m.uci() for m in board.legal_moves if board.is_capture(m)), best))\n  print('info depth 1")
        script.write_text(code, encoding='utf-8')
        self.pilot = run_pilot(self.dataset, self.command)
        self.choice = choose_budget(self.pilot, 50000)

    def test_all_splits_use_frozen_budget_reuse_and_only_complete_data_can_train(self):
        path = create_labeling(self.dataset, self.pilot)
        before = load_labeling(path)
        training_count = sum(p['split'] == 'train' for p in self.data['positions'])
        self.assertEqual(before['completed'], training_count)
        self.assertEqual(before['summary']['reused_pilot'], training_count)
        with self.assertRaisesRegex(ValueError, '未完成'):
            load_labeled_dataset(path)
        run_labeling(path)
        saved = load_labeling(path)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['completed'], len(self.data['positions']))
        self.assertEqual(saved['remaining'], 0)
        self.assertEqual({r['label']['requested_nodes'] for r in saved['records']}, {50000})
        self.assertEqual({r['label']['split'] for r in saved['records']}, {'train', 'validation', 'test'})
        usable = load_labeled_dataset(path)
        self.assertTrue(all(p['label']['valid'] and p['label']['white_cp'] is not None for p in usable['positions']))
        self.assertEqual(usable['snapshot']['choice'], self.choice)
        self.assertEqual(saved['summary']['data_exclusions'], self.data['summary']['excluded'])

    def test_stop_deadline_reopen_and_stale_summary_skip_every_committed_record(self):
        path = create_labeling(self.dataset, self.pilot)
        initial = load_labeling(path)['completed']
        stop = Event()
        def after_one(state):
            if state['completed'] > initial: stop.set()
        run_labeling(path, stop=stop, progress=after_one)
        saved = load_labeling(path)
        self.assertEqual(saved['status'], 'stopped')
        self.assertEqual(saved['completed'], initial + 1)
        committed = {p.name: p.read_bytes() for p in (path / 'records').glob('*.json')}
        write_json_atomic(path / 'status.json', dict(status='running', completed=0, elapsed_seconds=0))
        self.assertEqual(load_labeling(path)['completed'], initial + 1)
        clock = [0]
        def expire(state):
            if state['completed'] > initial + 1: clock[0] = 28800
        run_labeling(path, now=lambda: clock[0], progress=expire)
        limited = load_labeling(path)
        self.assertEqual(limited['status'], 'stopped')
        self.assertIn('八小時', limited['error'])
        self.assertEqual(limited['completed'], initial + 2)
        with self.assertRaisesRegex(ValueError, '未完成'): load_labeled_dataset(path)
        run_labeling(path)
        self.assertTrue(load_labeling(path)['ready'])
        for name, data in committed.items(): self.assertEqual((path / 'records' / name).read_bytes(), data)
        write_json_atomic(path / 'status.json', dict(status='failed', error='摘要落後'))
        self.assertEqual(load_labeling(path)['status'], 'completed')

    def test_crash_unknown_score_and_save_failure_are_retriable_without_duplicate_commits(self):
        for mode in ('crash', 'unknown', 'save'):
            with self.subTest(mode=mode):
                path = create_labeling(self.dataset, self.pilot)
                initial = load_labeling(path)['completed']
                self.control.write_text(mode)
                original = os.replace
                def fail_record(src, target):
                    if Path(target).parent == path / 'records': raise OSError('儲存失敗')
                    return original(src, target)
                with patch('os.replace', fail_record if mode == 'save' else original):
                    run_labeling(path)
                failed = load_labeling(path)
                self.assertEqual(failed['status'], 'failed')
                self.assertEqual(failed['completed'], initial)
                self.assertEqual(failed['failed'], 1)
                self.assertEqual(failed['retry'], 1)
                self.assertTrue(failed['failures'][0]['error'])
                if mode == 'unknown': self.assertTrue(failed['failures'][0]['raw_output'])
                self.control.unlink()
                run_labeling(path)
                done = load_labeling(path)
                self.assertTrue(done['ready'])
                self.assertEqual(done['failed'], 0)
                self.assertEqual(len({r['work_id'] for r in done['records']}), done['total'])

    def test_filters_counts_and_frozen_engine_identity(self):
        for mode, reason in (('mate', 'mate'), ('bound', 'bound_only'), ('tb', 'tablebase_score'), ('tbhit', 'tablebase_hit')):
            with self.subTest(mode=mode):
                path = create_labeling(self.dataset, self.pilot)
                initial = load_labeling(path)['completed']
                self.control.write_text(mode)
                run_labeling(path)
                done = load_labeling(path)
                self.assertTrue(done['ready'])
                self.assertEqual(done['summary']['reasons'][reason], done['total'] - initial)
                usable = load_labeled_dataset(path)
                self.assertTrue(all(p['split'] == 'train' for p in usable['positions']))
        self.control.unlink()
        path = create_labeling(self.dataset, self.pilot)
        script = Path(self.command[1])
        script.write_text(script.read_text(encoding='utf-8') + '\n# 改動執行檔\n', encoding='utf-8')
        run_labeling(path)
        self.assertIn('凍結', load_labeling(path)['error'])
        with self.assertRaisesRegex(ValueError, '不可變'): create_labeling(self.dataset, self.pilot, run_path=path)

    def test_capture_promotion_and_only_identical_selected_pilot_records_are_reused(self):
        source = self.root / 'promotions.pgn'
        source.write_text(pgn_games(8) + '\n[Event "升變"]\n[Result "*"]\n\n1. a4 h5 2. a5 h4 3. a6 h3 4. axb7 hxg2 5. bxa8=Q gxh1=Q *', encoding='utf-8')
        dataset = create_dataset(self.root / 'special', source)
        self.control.write_text('tactics')
        pilot = run_pilot(dataset, self.command)
        choose_budget(pilot, 50000)
        path = create_labeling(dataset, pilot)
        run_labeling(path)
        saved = load_labeling(path)
        self.assertGreater(saved['summary']['reasons']['promotion'], 0)
        self.assertGreater(saved['summary']['reasons']['capture'], 0)
        self.assertTrue(all(not p['label']['exclusion_reasons'] for p in load_labeled_dataset(path)['positions']))
        self.control.unlink()
        record_file = next(p for p in (self.pilot / 'records').glob('*.json')
                           if json.loads(p.read_text(encoding='utf-8'))['requested_nodes'] == 50000)
        record = json.loads(record_file.read_text(encoding='utf-8'))
        record['fen'] = '身份不符'
        write_json_atomic(record_file, record)
        path = create_labeling(self.dataset, self.pilot)
        expected = sum(p['split'] == 'train' for p in self.data['positions']) - 1
        self.assertEqual(load_labeling(path)['completed'], expected)
        run_labeling(path)
        self.assertTrue(load_labeling(path)['ready'])
        self.assertEqual(load_labeling(path)['summary']['reused_pilot'], expected)

    def test_exclusive_execution_and_summary_write_interruption_recover_from_records(self):
        path = create_labeling(self.dataset, self.pilot)
        status = (path / 'status.json').read_bytes()
        with experiment_lock(path):
            with self.assertRaisesRegex(ValueError, '執行者'): run_labeling(path)
        self.assertEqual((path / 'status.json').read_bytes(), status)
        initial = load_labeling(path)['completed']
        original = os.replace
        calls = [0]
        def fail_summary(src, target):
            if Path(target) == path / 'status.json':
                calls[0] += 1
                if calls[0] >= 2: raise OSError('摘要儲存失敗')
            return original(src, target)
        with patch('os.replace', fail_summary):
            with self.assertRaisesRegex(OSError, '摘要'): run_labeling(path)
        self.assertEqual(load_labeling(path)['completed'], initial + 1)
        run_labeling(path)
        self.assertTrue(load_labeling(path)['ready'])


if __name__ == '__main__': unittest.main()
