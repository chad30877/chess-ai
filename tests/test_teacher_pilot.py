"""教師公開執行、保存及選擇流程；唯一替身為外部 UCI 程序。"""
import tempfile
import time
from threading import Event
from unittest.mock import patch
import unittest
from pathlib import Path

from engine.learning.dataset import create_dataset
from tests.test_learning_dataset import pgn_games
from engine.learning.teacher import run_pilot, load_pilot, choose_budget


class TeacherPilotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'games.pgn'
        source.write_text(pgn_games(16), encoding='utf-8')
        self.dataset = create_dataset(self.root / 'data', source)
        self.engine = self.root / 'uci.py'
        from tests.helpers.uci_teacher import make_engine
        self.command = make_engine(self.root)

    def test_train_only_history_scores_saved_and_budget_choice_is_immutable(self):
        path = run_pilot(self.dataset, self.command)
        pilot = load_pilot(path)
        self.assertEqual(pilot['status'], 'completed')
        self.assertGreater(pilot['summary']['compared'], 0)
        self.assertGreater(pilot['summary']['budgets']['50000']['excluded'], 0)
        self.assertTrue(all(p['split'] == 'train' for p in pilot['snapshot']['samples']))
        self.assertEqual(len(pilot['records']), 2 * pilot['snapshot']['sample_count'])
        black = next(r for r in pilot['records'] if r['raw_score']['pov'] == 'black')
        self.assertEqual(black['white_cp'], -25)
        self.assertFalse(black['raw_score']['lowerbound'])
        self.assertEqual(black['moves_uci'], next(s['moves_uci'] for s in pilot['snapshot']['samples'] if s['id'] == black['sample_id']))
        chosen = choose_budget(path, 50000)
        self.assertEqual(load_pilot(path)['choice'], chosen)
        with self.assertRaisesRegex(ValueError, '不可變'):
            choose_budget(path, 200000)

    def test_missing_wrong_version_crash_timeout_and_illegal_move_preserve_failure(self):
        original = self.engine.read_text(encoding='utf-8')
        scenarios = [
            ('wrong', original.replace('Stockfish 19', 'Stockfish 18'), '版本不合'),
            ('crash', original.replace("import chess", "raise SystemExit(5)\n  import chess"), '異常終止'),
            ('timeout', original.replace("import chess", "import time; time.sleep(60)\n  import chess"), '逾時'),
        ]
        scenarios.append(('illegal', original.replace("print('bestmove '+best", "print('bestmove a1a1'"), '非法最佳手'))
        scenarios.append(('null', original.replace("print('bestmove '+best", "print('bestmove 0000'"), '非法最佳手'))
        for name, content, expected in scenarios:
            with self.subTest(name=name):
                self.engine.write_text(content, encoding='utf-8')
                started = time.monotonic()
                saved = load_pilot(run_pilot(self.dataset, self.command, timeout=.6))
                self.assertEqual(saved['status'], 'failed')
                self.assertIn(expected, saved['error'])
                self.assertFalse(saved['records'])
                self.assertLess(time.monotonic() - started, 5)
        saved = load_pilot(run_pilot(self.dataset, self.root/'missing.exe'))
        self.assertIn('執行檔', saved['error'])

    def test_cancel_and_eight_hour_limit_commit_only_completed_positions(self):
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                stop, clock = Event(), [100.0]
                def progress(state):
                    if state['completed'] == 1:
                        if cancel: stop.set()
                        else: clock[0] += 8 * 3600
                saved = load_pilot(run_pilot(self.dataset, self.command, stop=stop,
                    now=lambda: clock[0], progress=progress))
                self.assertEqual(saved['status'], 'stopped')
                self.assertEqual(len(saved['records']), 1)
                with self.assertRaisesRegex(ValueError, '未完成'):
                    choose_budget(saved['path'], 50000)

    def test_bound_mate_and_special_score_are_preserved_with_exclusion_reasons(self):
        original = self.engine.read_text(encoding='utf-8')
        for score, reason in [('cp 7 upperbound', 'bound_only'), ('mate 3', 'mate'), ('cp 20001', 'tablebase_score')]:
            with self.subTest(score=score):
                self.engine.write_text(original.replace('score cp 25', 'score '+score), encoding='utf-8')
                stop = Event()
                def progress(state):
                    if state['completed'] == 1: stop.set()
                record = load_pilot(run_pilot(self.dataset, self.command, stop=stop, progress=progress))['records'][0]
                self.assertIn(reason, record['exclusion_reasons'])
                self.assertFalse(record['valid'])
                if reason == 'mate': self.assertIsNone(record['white_cp'])

    def test_save_failure_does_not_publish_incomplete_position(self):
        import os
        original = os.replace
        def replace(source, target):
            if Path(target).parent.name == 'records': raise OSError('磁碟無法寫入')
            return original(source, target)
        with patch('os.replace', side_effect=replace):
            saved = load_pilot(run_pilot(self.dataset, self.command))
        self.assertEqual(saved['status'], 'failed')
        self.assertIn('磁碟', saved['error'])
        self.assertFalse(saved['records'])

    def test_stop_interrupts_waiting_teacher_and_releases_process(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Timer
        original = self.engine.read_text(encoding='utf-8')
        self.engine.write_text(original.replace('import chess', 'import time; time.sleep(60)\n  import chess'), encoding='utf-8')
        stop = Event()
        timer = Timer(.4, stop.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_pilot, self.dataset, self.command, stop=stop)
            saved = load_pilot(future.result(timeout=4))
        self.assertEqual(saved['status'], 'stopped')
        self.assertFalse(saved['records'])
        self.assertLess(time.monotonic() - started, 4)

    def test_last_completed_exact_score_for_same_bestmove_survives_budget_bound(self):
        original = self.engine.read_text(encoding='utf-8')
        self.engine.write_text(original.replace("print('bestmove '+best", "print('info depth 3 score cp 30 lowerbound nodes 50001 pv '+best, flush=True)\n  print('bestmove '+best"), encoding='utf-8')
        stop = Event()
        def progress(state):
            if state['completed'] == 1: stop.set()
        record = load_pilot(run_pilot(self.dataset, self.command, stop=stop, progress=progress))['records'][0]
        self.assertEqual(record['raw_score']['value'], 25)
        self.assertNotIn('bound_only', record['exclusion_reasons'])

    def test_previous_exact_for_different_move_does_not_hide_final_bound(self):
        original = self.engine.read_text(encoding='utf-8')
        replacement = "best=list(board.legal_moves)[1].uci()\n  print('info depth 3 score cp 30 lowerbound nodes 50001 pv '+best, flush=True)\n  print('bestmove '+best"
        self.engine.write_text(original.replace("print('bestmove '+best", replacement), encoding='utf-8')
        stop = Event()
        def progress(state):
            if state['completed'] == 1: stop.set()
        record = load_pilot(run_pilot(self.dataset, self.command, stop=stop, progress=progress))['records'][0]
        self.assertEqual(record['raw_score']['value'], 30)
        self.assertIn('bound_only', record['exclusion_reasons'])

if __name__ == '__main__': unittest.main()
