"""自選群組組合、固定對照及聯合求解的公開流程。"""
import json
import unittest
from tests import test_weight_training as fixtures
from engine.evaluation.config import EvaluationConfig
from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
from engine.learning.combination_training import (create_combination, load_combination, run_combination,
    load_combination_candidate, save_combination_config, preview_combination)


class CombinationFlowTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def source(self):
        path = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(path)
        return path

    def test_direct_copies_single_weights_and_joint_exports_only_selected_groups(self):
        source = self.source()
        singles = [load_group_candidate(source, g) for g in ('mobility', 'king-safety')]
        preview = preview_combination(singles)
        path = create_combination(source, ['mobility', 'king-safety'])
        initial = load_combination(path)
        self.assertEqual(initial['snapshot']['direct'], preview['direct'])
        for single in singles:
            for name, term in single['config']['terms'].items():
                if name != 'material' and term['enabled']:
                    self.assertEqual(preview['direct']['terms'][name], term)
        self.assertIn(source.name, [p['experiment_id'] for p in initial['snapshot']['prior_test_experiments']])
        run_combination(path)
        saved = load_combination(path)
        self.assertEqual(saved['status'], 'completed', saved.get('error'))
        self.assertEqual(saved['completed'], 3)
        self.assertEqual(set(saved['controls']['validation']['metrics']), {'material','mobility','king-safety','both'})
        self.assertEqual(saved['calibration']['identity'], singles[0]['calibration_identity'])
        direct = load_combination_candidate(path, 'direct')
        joint = load_combination_candidate(path, 'joint')
        self.assertLessEqual(saved['results']['joint']['frozen']['validation']['mae'],
            min(c['validation']['mae'] for c in saved['candidates'].values()) + saved['snapshot']['rules']['tie_tolerance'])
        self.assertNotEqual(direct['candidate_identity'], joint['candidate_identity'])
        self.assertEqual(direct['config'], preview['direct'])
        for candidate in saved['candidates'].values():
            for name, term in preview['original']['terms'].items():
                if name not in preview['terms']:
                    self.assertEqual(candidate['config']['terms'][name], term)
            self.assertTrue(all(w >= 0 for w in candidate['solver']['weights']))
        for kind in ('direct', 'joint'):
            file = save_combination_config(path, kind, self.root / f'{kind}.json')
            self.assertEqual(EvaluationConfig.from_dict(json.loads(file.read_text(encoding='utf-8'))).to_dict(),
                load_combination_candidate(path, kind)['config'])
        files = {str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*.json')}
        run_combination(path)
        self.assertEqual({str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*.json')}, files)
        # 移動已保存來源後，新組合在目前位置保存並保留前次組合曝光，不回寫舊來源。
        import shutil
        moved = self.root/'relocated'
        shutil.copytree(self.labels,moved)
        relocated = create_combination(moved/'group-training'/source.name)
        relocated_state = load_combination(relocated)
        self.assertEqual(relocated.parent,moved/'combinations')
        self.assertIn(path.name,[p['experiment_id'] for p in relocated_state['snapshot']['prior_test_experiments']])

    def test_incompatible_sources_refuse_and_cancel_resume_keep_every_committed_unit(self):
        from copy import deepcopy
        from threading import Event
        import multiprocessing
        source = self.source()
        sources = [load_group_candidate(source,g) for g in ('mobility','king-safety')]
        for key in ('dataset_identity','calibration_identity','test_data_identity'):
            changed = deepcopy(sources); changed[1][key] = 'different'
            with self.assertRaisesRegex(ValueError,'不相容'): preview_combination(changed)
        path = create_combination(source)
        stop = Event(); workers = []
        def cancel(state):
            if state.get('worker_pid') and state['completed'] == 1:
                workers.append(state['worker_pid']); stop.set()
        run_combination(path,stop=stop,progress=cancel)
        saved = load_combination(path)
        self.assertEqual(saved['status'],'stopped')
        self.assertEqual(saved['completed'],1)
        self.assertTrue(workers)
        self.assertFalse(any(p.pid in workers for p in multiprocessing.active_children()))
        self.assertIsNone(saved['results']['joint']['frozen'])
        committed = {str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*.json') if p.name != 'status.json'}
        clock = [0]
        def expire(state):
            if state.get('worker_pid'): clock[0] = 28800
        run_combination(path,now=lambda:clock[0],progress=expire)
        self.assertIn('八小時',load_combination(path)['error'])
        self.assertEqual(load_combination(path)['completed'],1)
        run_combination(path)
        self.assertEqual(load_combination(path)['status'],'completed')
        for name,data in committed.items(): self.assertEqual((path/name).read_bytes(),data)
        next_path = create_combination(source)
        self.assertIn(path.name,[p['experiment_id'] for p in load_combination(next_path)['snapshot']['prior_test_experiments']])


class FixedWeightContractTest(unittest.TestCase):
    def test_same_weights_give_different_king_error_increments_in_two_backgrounds(self):
        from engine.learning.combination_training import fixed_weight_metrics
        from pathlib import Path
        payload = json.loads((Path(__file__).resolve().parents[1]/'configs/evaluation/learning-mobility.json').read_text())
        for name, term in payload['terms'].items():
            if name != 'material':
                term['enabled'] = name in ('pawn_mobility','king_mobility','king_pawn_shield','king_file_exposure')
        payload['terms']['pawn_mobility']['endgame_weight'] = .1
        payload['terms']['king_mobility']['endgame_weight'] = .1
        payload['terms']['king_pawn_shield']['endgame_weight'] = .4
        payload['terms']['king_file_exposure']['endgame_weight'] = .1
        rows = [dict(game_id='a', fen='6k1/8/8/8/8/8/5PPP/6K1 w - - 0 1', stage='endgame', label=dict(white_cp=400))]
        result = fixed_weight_metrics(rows, EvaluationConfig.from_dict(payload), .01)
        # 子力 3；活動力 5*.1-3*.1=.2（h 兵只有一斜格）；王安全 3*.4+3*.1=1.5；目標 4。
        for name, expected in [('material',1),('mobility',.8),('king-safety',.5),('both',.7)]:
            self.assertAlmostEqual(result['metrics'][name]['mae'], expected)
            self.assertEqual(result['configs'][name]['phase'], payload['phase'])
        self.assertAlmostEqual(result['king_increments']['without_mobility']['mae'], -.5)
        self.assertAlmostEqual(result['king_increments']['with_mobility']['mae'], -.1)
        self.assertIsNone(result['king_increments']['with_mobility']['stages']['opening'])
