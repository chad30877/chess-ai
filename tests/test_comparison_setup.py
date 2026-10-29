"""比較用途以真實凍結候選及既有對戰規則驗證。"""
import json
from pathlib import Path
import unittest
from tests import test_weight_training as fixtures
from engine.learning.training import create_training, run_training
from engine.learning.teacher import digest
from engine.storage.batch_storage import write_json_atomic

class SetupPlanTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_three_selected_candidates_create_48_game_screening_plan(self):
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.comparison_setup import freeze_setup, preview_setup
        from unittest.mock import patch
        from engine.learning.comparison import load_comparison_plan
        for index in range(2):
            path = create_training(self.labels)
            file = path / 'snapshot.json'
            snapshot = json.loads(file.read_text(encoding='utf-8'))
            weight = .5 + index * .2
            snapshot['original']['terms']['piece_square']['weight'] = weight
            snapshot['original_weights'][0] = snapshot['scales'][0] = weight
            snapshot.pop('identity'); snapshot['identity'] = digest(snapshot)
            write_json_atomic(file, snapshot); run_training(path)
        from engine.learning.dataset import create_dataset
        from engine.learning.teacher import run_pilot, choose_budget
        from engine.learning.labeling import create_labeling, run_labeling
        from tests.helpers.uci_teacher import make_engine
        from tests.test_learning_dataset import pgn_games
        source = self.root / 'other.pgn'; source.write_text(pgn_games(9), encoding='utf-8')
        dataset = create_dataset(self.root / 'data', source, seed=19)
        pilot = run_pilot(dataset, make_engine(self.root)); choose_budget(pilot, 50000)
        labels = create_labeling(dataset, pilot); run_labeling(labels)
        path = create_training(labels); run_training(path)
        rows = load_all_candidate_inventory(self.root / 'data')['candidates']
        self.assertEqual(len({row['source']['dataset_identity'] for row in rows}), 2)
        setup = freeze_setup(self.root, self.root / 'data', rows, 'screening')
        self.assertEqual(setup['planned_games'], 48)
        self.assertEqual(len(setup['work']), 3)
        plans = [load_comparison_plan(item['path']) for item in setup['work']]
        self.assertEqual([p['source'] for p in plans], [row['source'] for row in rows])
        self.assertTrue(all(p['planned_games'] == 16 and list(p['definitions']) == ['stable'] for p in plans))
        definitions = [p['definitions']['stable'] for p in plans]
        for field in ('search', 'opening_lines', 'baseline', 'workers', 'claim_draw'):
            self.assertTrue(all(d[field] == definitions[0][field] for d in definitions))
        from engine.learning.comparison import create_comparison
        old = create_comparison(self.root, rows[0]['source'], roles=('original', 'learned'), stable=True)
        self.assertEqual(load_comparison_plan(old)['planned_games'], 256)
        with patch('engine.learning.comparison_setup.screening_report') as report:
            report.side_effect = lambda path: {'complete': True, 'eliminated': str(path) == setup['work'][1]['path']}
            preview = preview_setup(self.root, self.root / 'data', rows, 'final')
            self.assertEqual(preview['passed'], [True, False, True])
            with self.assertRaisesRegex(ValueError, '快速篩選'):
                freeze_setup(self.root, self.root / 'data', rows, 'final')
            report.return_value = {'complete': True, 'eliminated': False}; report.side_effect = None
            final = freeze_setup(self.root, self.root / 'data', rows, 'final')
        self.assertEqual(final['planned_games'], 384)
        self.assertEqual(len(final['work']), 6)
        for item in final['work']:
            plan = load_comparison_plan(item['path'])
            self.assertEqual(plan['definitions'][item['baseline']]['planned_games'], 64)

    def test_bundle_runs_short_comparisons_and_stops_with_saved_games(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from engine.learning.comparison import create_comparison
        from engine.learning.comparison_setup import ComparisonBundleRun
        from tests.test_learned_comparison import candidate
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name=str(i), source={}) for i in range(8)]
        paths = [create_comparison(self.root, candidate(), roles=('learned',), opening_lines=lines, max_plies=1) for _ in range(2)]
        with ThreadPoolExecutor(1) as executor:
            run = ComparisonBundleRun([dict(path=str(path), baseline='material') for path in paths], 32, executor)
            deadline = time.monotonic() + 30
            while run.snapshot()['saved_games'] < 1:
                self.assertFalse(run.future.done())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.02)
            run.stop(); run.future.result(timeout=20)
            state = run.snapshot()
            self.assertEqual(state['status'], 'stopped')
            self.assertGreaterEqual(state['saved_games'], 1)
            self.assertEqual(state['requested_games'], 32)
            self.assertTrue(Path(state['last_replay']).exists())
            saved_dir = Path(state['path']) / 'replays'
            committed = {file: file.read_bytes() for file in saved_dir.glob('*.json')
                         if json.loads(file.read_text(encoding='utf-8'))['metadata']['termination'] != 'user_stop'}
            resumed = ComparisonBundleRun([dict(path=str(path), baseline='material') for path in paths], 32, executor)
            resumed.future.result(timeout=30)
            self.assertEqual(resumed.snapshot()['status'], 'completed')
            self.assertEqual(resumed.snapshot()['saved_games'], 32)
            self.assertTrue(all(file.read_bytes() == content for file, content in committed.items()))
