"""以保存與重開入口核對並行吞吐、先導重用及後續標記工作量。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from engine.learning.dataset import create_dataset
from engine.learning.teacher import run_pilot, load_pilot, choose_budget
from engine.learning.labeling import create_labeling, load_labeling, run_labeling
from engine.storage.batch_storage import write_json_atomic
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games


class LabelingEstimatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'source.pgn'
        source.write_text(pgn_games(8), encoding='utf-8')
        self.dataset = create_dataset(self.root / 'data', source)
        self.command = make_engine(self.root)

    def measured_pilot(self):
        clock, seen = [0.0], [0]
        def progress(state):
            if state['completed'] > seen[0]:
                clock[0] += 1 if state['completed'] <= 60 else 3
                seen[0] = state['completed']
        return run_pilot(self.dataset, self.command, workers=2,
                         now=lambda: clock[0], progress=progress)

    def test_saved_parallel_wall_time_and_actual_sample_count_predict_remaining_labels(self):
        path = self.measured_pilot()
        pilot = load_pilot(path)
        self.assertEqual(pilot['snapshot']['sample_count'], 60)
        self.assertIsNone(pilot['choice'])
        estimates = pilot['labeling_estimates']
        self.assertEqual(estimates['50000']['measured_seconds'], 60)
        self.assertEqual(estimates['200000']['measured_seconds'], 180)
        self.assertEqual(estimates['50000']['remaining'], 36)
        self.assertEqual(estimates['50000']['seconds'], 36)
        self.assertEqual(estimates['200000']['seconds'], 108)
        self.assertEqual(load_pilot(path)['labeling_estimates'], estimates)
        choose_budget(path, 200000)
        labels = load_labeling(create_labeling(self.dataset, path))
        self.assertEqual(labels['remaining'], estimates['200000']['remaining'])
        self.assertEqual(labels['snapshot']['nodes'], 200000)
        self.assertEqual(labels['snapshot']['workers'], 2)
        Path(self.command[1]).unlink()
        self.assertEqual(load_pilot(path)['labeling_estimates'], estimates)

    def test_reuse_matches_labeling_and_does_not_discard_unanalysed_filtered_positions(self):
        script = Path(self.command[1])
        script.write_text(script.read_text(encoding='utf-8').replace('score cp 25', 'score mate 3'), encoding='utf-8')
        path = self.measured_pilot()
        record_paths = sorted((path / 'records').glob('*-50000.json'))
        wrong_history = json.loads(record_paths[0].read_text(encoding='utf-8'))
        wrong_history['moves_uci'] = []
        write_json_atomic(record_paths[0], wrong_history)
        wrong_policy = json.loads(record_paths[1].read_text(encoding='utf-8'))
        wrong_policy['score_policy'] = 'different-policy'
        write_json_atomic(record_paths[1], wrong_policy)
        estimates = load_pilot(path)['labeling_estimates']
        self.assertEqual(estimates['50000']['reused'], 58)
        self.assertEqual(estimates['50000']['remaining'], 38)
        self.assertEqual(estimates['50000']['seconds'], 38)
        choose_budget(path, 50000)
        labeling_path = create_labeling(self.dataset, path)
        before = load_labeling(labeling_path)
        self.assertEqual(before['summary']['excluded'], 58)
        self.assertEqual(before['remaining'], estimates['50000']['remaining'])
        run_labeling(labeling_path)
        after = load_labeling(labeling_path)
        self.assertTrue(after['ready'])
        self.assertEqual(after['summary']['excluded'], 96)
        self.assertEqual(after['summary']['valid'], 0)

    def test_missing_invalid_or_mismatched_measurements_never_create_estimates(self):
        path = self.measured_pilot()
        original = json.loads((path / 'status.json').read_text(encoding='utf-8'))
        variations = [{}, {'completed': 0}, {'elapsed_seconds': 0}, {'elapsed_seconds': None},
                      {'elapsed_seconds': float('nan')}, {'workers': 1}]
        for update in variations:
            with self.subTest(update=update):
                status = deepcopy(original)
                if update:
                    for measurement in status['budget_measurements'].values(): measurement.update(update)
                else:
                    status.pop('budget_measurements')
                write_json_atomic(path / 'status.json', status)
                for estimate in load_pilot(path)['labeling_estimates'].values():
                    self.assertIsNone(estimate['seconds'])
                    self.assertEqual(estimate['remaining'], 36)
        write_json_atomic(path / 'status.json', original)
        dataset_path = self.dataset / 'dataset.json'
        data = json.loads(dataset_path.read_text(encoding='utf-8'))
        data['seed'] += 1
        write_json_atomic(dataset_path, data)
        self.assertTrue(all(e['seconds'] is None for e in load_pilot(path)['labeling_estimates'].values()))
