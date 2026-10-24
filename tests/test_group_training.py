"""五個單群組公開執行、共用校準與保存結果。"""
import json
from pathlib import Path
import unittest
from tests import test_weight_training as fixtures
from engine.evaluation.config import EvaluationConfig
from engine.learning.group_training import create_group_training, run_group_training, load_group_training, save_group_config, load_group_candidate


class GroupTrainingFlowTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_five_independent_groups_share_calibration_and_export_full_candidates(self):
        path = create_group_training(self.labels)
        run_group_training(path)
        result = load_group_training(path)
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(result['completed'], 15)
        self.assertEqual(result['completed_groups'], 5)
        self.assertAlmostEqual(result['calibration']['scale'], .01)
        columns = []
        for group, state in result['groups'].items():
            definition = result['snapshot']['definitions'][group]
            columns.extend(definition['column_order'])
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['report']['calibration_identity'], result['calibration']['identity'])
            self.assertEqual(set(state['report']['test']), {'material', 'original', 'learned', 'stable'})
            report = state['report']
            improves = all(report[s]['learned']['mae'] < report[s]['original']['mae'] for s in ('validation', 'test'))
            self.assertEqual(report['priority_battle_observation'], result['calibration']['healthy'] and improves)
            for split in ('validation', 'test'):
                self.assertGreater(report[split]['learned']['positions'], 0)
                for baseline in ('material', 'stable'):
                    self.assertAlmostEqual(report['deltas'][split]['learned'][baseline]['mae'],
                        report[split]['learned']['mae'] - report[split][baseline]['mae'])
            for candidate in state['candidates'].values():
                learned = candidate['config']
                original = definition['original']
                self.assertEqual(learned['phase'], original['phase'])
                for name, term in original['terms'].items():
                    if name not in definition['terms']: self.assertEqual(learned['terms'][name], term)
                self.assertTrue(all(w >= 0 for w in candidate['solver']['weights']))
            target = save_group_config(path, group, self.root / f'{group}.json')
            loaded = EvaluationConfig.from_dict(json.loads(target.read_text(encoding='utf-8')))
            self.assertEqual(loaded.to_dict(), state['frozen']['config'])
            source = load_group_candidate(path, group)
            self.assertEqual(source['groups'], [group])
            self.assertEqual(source['calibration_identity'], result['calibration']['identity'])
        from engine.learning.training import create_training, load_training
        prior = load_training(create_training(self.labels))['snapshot']['prior_test_experiments']
        self.assertIn(result['snapshot']['id'], [p['experiment_id'] for p in prior])
        self.assertEqual(len(columns), 32)
        self.assertEqual(len(set(columns)), 32)
        files = {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*.json')}
        run_group_training(path)
        self.assertEqual({str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*.json')}, files)

    def test_one_deadline_across_groups_and_resume_preserve_completed_results_and_calibration(self):
        clock = [0]
        path = create_group_training(self.labels)
        def expire(state):
            if state['completed_groups'] == 2: clock[0] = 28800
        run_group_training(path, now=lambda: clock[0], progress=expire)
        saved = load_group_training(path)
        self.assertEqual(saved['status'], 'stopped')
        self.assertEqual(saved['completed_groups'], 2)
        self.assertEqual(saved['completed'], 6)
        self.assertIn('八小時', saved['error'])
        self.assertFalse(saved['groups']['mobility']['report'])
        with self.assertRaisesRegex(ValueError, '未完成'): load_group_candidate(path, 'mobility')
        committed = {str(p.relative_to(path)): p.read_bytes() for p in path.glob('groups/*/*.json')}
        committed.update({str(p.relative_to(path)): p.read_bytes() for p in path.glob('groups/*/candidates/*.json')})
        calibration = (path / 'calibration.json').read_bytes()
        run_group_training(path)
        self.assertEqual(load_group_training(path)['completed_groups'], 5)
        self.assertEqual((path / 'calibration.json').read_bytes(), calibration)
        for file, data in committed.items(): self.assertEqual((path / file).read_bytes(), data)
        next_path = create_group_training(self.labels, ['mobility', 'king-safety'])
        next_state = load_group_training(next_path)
        self.assertNotEqual(next_state['snapshot']['identity'], saved['snapshot']['identity'])
        self.assertEqual(next_state['snapshot']['prior_test_experiments'][0]['experiment_id'], saved['snapshot']['id'])

    def test_one_candidate_save_failure_preserves_other_groups_and_retries_only_missing(self):
        import os
        from unittest.mock import patch
        path = create_group_training(self.labels)
        original = os.replace
        def fail(src, target):
            if Path(target) == path / 'groups/pawn/candidates/weak.json': raise OSError('此候選儲存失敗')
            return original(src, target)
        with patch('os.replace', fail): run_group_training(path)
        saved = load_group_training(path)
        self.assertEqual(saved['status'], 'partial')
        self.assertEqual(saved['completed'], 14)
        self.assertEqual(saved['completed_groups'], 4)
        self.assertEqual(saved['failed_groups'], 1)
        self.assertEqual(saved['groups']['pawn']['status'], 'failed')
        self.assertIsNone(saved['groups']['pawn']['report'])
        kept = {str(p.relative_to(path)): p.read_bytes() for p in path.glob('groups/*/report.json')}
        kept.update({str(p.relative_to(path)): p.read_bytes() for p in path.glob('groups/*/candidates/*.json')})
        run_group_training(path)
        self.assertEqual(load_group_training(path)['status'], 'completed')
        for file, data in kept.items(): self.assertEqual((path / file).read_bytes(), data)


class GroupNumericContractTest(unittest.TestCase):
    def test_all_32_endpoint_features_match_formal_scores_and_zero_king_weight_can_increase(self):
        import chess
        from engine.evaluation.evaluator import HandcraftedEvaluator
        from engine.learning.training import extract_features, fit_position_weights, training_rules
        root = Path(__file__).resolve().parents[1]
        groups = ('piece-square', 'pawn', 'mobility', 'king-safety', 'coordination')
        boards = [chess.Board('r3k2r/pp1n1ppp/2p1bn2/3p4/3P4/2N1BN2/PP3PPP/R3K2R w KQkq - 0 10'),
                  chess.Board('6k1/8/8/8/8/8/5PPP/6K1 w - - 0 1')]
        columns = 0
        for group in groups:
            config = EvaluationConfig.from_dict(json.loads((root / f'configs/evaluation/learning-{group}.json').read_text(encoding='utf-8')))
            terms = [n for n, v in config.to_dict()['terms'].items() if n != 'material' and v['enabled']]
            for board in boards:
                bias, features, weights = extract_features(board, config, terms)
                self.assertAlmostEqual(bias + sum(x*w for x,w in zip(features,weights)), HandcraftedEvaluator(config=config).evaluate(board), places=11)
            columns += len(weights)
            if group == 'king-safety':
                row = dict(game_id='king', fen=boards[1].fen(), stage='endgame', label=dict(white_cp=1000))
                fitted, _ = fit_position_weights([row], config, terms, .01, .001, training_rules())
                original, learned = config.to_dict(), fitted.to_dict()
                self.assertTrue(any(original['terms'][n]['endgame_weight'] == 0 and learned['terms'][n]['endgame_weight'] > 0 for n in terms))
                for name, term in original['terms'].items():
                    if name not in terms: self.assertEqual(learned['terms'][name], term)
        self.assertEqual(columns, 32)
