"""跨來源候選查找使用真實保存的學習結果。"""
import unittest
from tests import test_weight_training as fixtures
from engine.learning.training import create_training, run_training

class AllCandidatesTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_legacy_piece_square_candidate_is_read_only_and_keeps_identity(self):
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.training import load_training
        path = create_training(self.labels)
        run_training(path)
        before = {p.name: p.read_bytes() for p in path.glob('*.json')}
        original = load_training(path)
        incomplete = create_training(self.labels)
        inventory = load_all_candidate_inventory(self.root / 'data')
        self.assertTrue(any(row['path'] == str(incomplete) for row in inventory['errors']))
        self.assertFalse(any(row['path'] == str(incomplete) for row in inventory['candidates']))
        self.assertEqual(len(inventory['candidates']), 1)
        candidate = inventory['candidates'][0]['source']
        self.assertEqual(candidate['config'], original['frozen']['config'])
        self.assertEqual(candidate['report'], original['report'])
        self.assertEqual(candidate['snapshot_identity'], original['snapshot']['identity'])
        self.assertEqual(candidate['label_identity'], original['snapshot']['label_identity'])
        from engine.learning.comparison import create_comparison, load_comparison_plan
        plan = create_comparison(self.root, candidate, roles=('learned',))
        self.assertEqual(load_comparison_plan(plan)['source'], candidate)
        self.assertEqual({p.name: p.read_bytes() for p in path.glob('*.json')}, before)
        import pygame
        from unittest.mock import patch
        from apps.chess_application import ChessApplication, APP_SIZE
        from tests.helpers.executors import ManualExecutor
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_candidate:0')
            self.assertIsNone(app.batch)
            click('learning_inventory_screen'); executor.finish(); app.render()
            self.assertEqual(app.learning.screening.report['plan']['source'], candidate)
            self.assertIsNone(app.batch)
            self.assertEqual({p.name: p.read_bytes() for p in path.glob('*.json')}, before)

    def test_mixed_sources_keep_equal_configs_and_skip_damaged_experiment(self):
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.group_training import create_group_training, run_group_training
        from engine.learning.combination_training import create_combination, run_combination
        from engine.learning.dataset import create_dataset
        from engine.learning.teacher import run_pilot, choose_budget
        from engine.learning.labeling import create_labeling, run_labeling
        from tests.helpers.uci_teacher import make_engine
        from tests.test_learning_dataset import pgn_games
        group = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(group)
        combination = create_combination(group, ['mobility', 'king-safety'])
        run_combination(combination)
        first = create_training(self.labels); run_training(first)
        second = create_training(self.labels); run_training(second)
        source = self.root / 'other.pgn'; source.write_text(pgn_games(9), encoding='utf-8')
        dataset = create_dataset(self.root / 'data', source, seed=19)
        pilot = run_pilot(dataset, make_engine(self.root)); choose_budget(pilot, 50000)
        labels = create_labeling(dataset, pilot); run_labeling(labels)
        third = create_training(labels); run_training(third)
        import json
        from engine.storage.batch_storage import write_json_atomic
        for path, value in ((first, 1.0), (second, 3.0), (third, 2.0)):
            report_path = path / 'report.json'
            stored = json.loads(report_path.read_text(encoding='utf-8'))
            stored['validation']['learned']['mae'] = value
            write_json_atomic(report_path, stored)
        broken = labels / 'training' / 'broken'; broken.mkdir()
        (broken / 'snapshot.json').write_text('{broken', encoding='utf-8')
        report = load_all_candidate_inventory(self.root / 'data')
        self.assertEqual({r['origin'] for r in report['candidates']}, {'legacy', 'group', 'combination'})
        self.assertEqual({r['kind'] for r in report['candidates'] if r['origin'] == 'combination'}, {'direct', 'joint'})
        self.assertGreaterEqual(len({r['source']['dataset_identity'] for r in report['candidates']}), 2)
        legacy = [r for r in report['candidates'] if r['origin'] == 'legacy']
        self.assertEqual(len(legacy), 3)
        self.assertEqual(sorted(row['mae'] for row in legacy), [1.0, 2.0, 3.0])
        self.assertNotEqual([row['mae'] for row in legacy], [1.0, 2.0, 3.0])
        first_row = next(row for row in legacy if row['path'] == str(first))
        second_row = next(row for row in legacy if row['path'] == str(second))
        self.assertEqual(first_row['config_identity'], second_row['config_identity'])
        self.assertNotEqual(first_row['source']['snapshot_identity'], second_row['source']['snapshot_identity'])
        self.assertTrue(any(e['path'] == str(broken) for e in report['errors']))
        self.assertEqual([r['source']['dataset_identity'] for r in report['candidates']],
                         sorted(r['source']['dataset_identity'] for r in report['candidates']))
        import pygame
        from unittest.mock import patch
        from apps.chess_application import ChessApplication, APP_SIZE
        from tests.helpers.executors import ManualExecutor
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'; app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_origin'); click('learning_inventory_group')
            self.assertEqual(len(app.learning.inventory.filtered()), 3)
            click('learning_inventory_origin')
            self.assertFalse(app.learning.inventory.filtered())
            click('learning_inventory_group'); click('learning_inventory_group')
            self.assertTrue(app.learning.inventory.filtered())
            self.assertTrue(all(row['origin'] == 'group' and 'mobility' in row['groups'] for _, row in app.learning.inventory.filtered()))
            click('learning_inventory_origin')
            self.assertEqual({row['kind'] for _, row in app.learning.inventory.filtered()}, {'direct', 'joint'})
            self.assertIsNone(app.batch)
            self.assertFalse((self.root / 'data/learning-screening').exists())

    def test_over_ten_distinct_candidates_are_reachable_and_filterable_in_ui(self):
        import json
        from unittest.mock import patch
        import pygame
        from apps.chess_application import ChessApplication, APP_SIZE
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        from tests.helpers.executors import ManualExecutor
        for index in range(11):
            path = create_training(self.labels)
            snapshot_path = path / 'snapshot.json'
            snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
            weight = 0.5 + index * 0.1
            snapshot['original']['terms']['piece_square']['weight'] = weight
            snapshot['original_weights'][0] = weight
            snapshot['scales'][0] = weight
            snapshot.pop('identity'); snapshot['identity'] = digest(snapshot)
            write_json_atomic(snapshot_path, snapshot)
            run_training(path)
        report = load_all_candidate_inventory(self.root / 'data')
        self.assertEqual(len(report['candidates']), 11)
        self.assertEqual(len({row['config_identity'] for row in report['candidates']}), 11)
        pygame.init(); self.addCleanup(pygame.quit)
        executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            self.addCleanup(app.close)
            app.learning.root = self.root / 'data'
            app.new_setup('learning')
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            click('learning_goal_compare'); executor.finish(); app.render()
            click('learning_inventory_origin')
            click('learning_inventory_group')
            self.assertEqual(len(app.learning.inventory.filtered()), 11)
            click('learning_inventory_next'); click('learning_inventory_next')
            click('learning_inventory_candidate:10')
            self.assertIn(10, app.learning.inventory.selected_indices)
            self.assertEqual(app.learning.inventory.report['candidates'][10]['source']['snapshot_identity'], report['candidates'][10]['source']['snapshot_identity'])
            click('learning_inventory_prev'); click('learning_inventory_candidate:5')
            app.render()
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_inventory_screen').enabled)
            app.dispatch('learning_inventory_screen')
            self.assertEqual(app.learning.page, 'inventory')
            self.assertIsNone(app.batch)
            self.assertFalse((self.root / 'data/learning-screening').exists())

    def test_damaged_group_does_not_hide_other_group_in_same_training(self):
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        path = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(path)
        valid = load_group_candidate(path, 'mobility')
        (path / 'groups/king-safety/report.json').write_text('{broken', encoding='utf-8')
        report = load_all_candidate_inventory(self.root / 'data')
        self.assertEqual([row['source'] for row in report['candidates']], [valid])
        self.assertTrue(report['errors'])

    def test_damaged_joint_report_does_not_hide_valid_direct_combination(self):
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.group_training import create_group_training, run_group_training
        from engine.learning.combination_training import create_combination, run_combination, load_combination_candidate
        group = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(group)
        path = create_combination(group, ['mobility', 'king-safety'])
        run_combination(path)
        direct = load_combination_candidate(path, 'direct')
        (path / 'joint/report.json').write_text('{broken', encoding='utf-8')
        report = load_all_candidate_inventory(self.root / 'data')
        self.assertIn(direct, [row['source'] for row in report['candidates']])
        self.assertTrue(any('joint' in row['path'] for row in report['errors']))
        (group / 'groups/mobility/report.json').write_text('{broken', encoding='utf-8')
        invalid = load_all_candidate_inventory(self.root / 'data')
        self.assertFalse(any(row['origin'] == 'combination' for row in invalid['candidates']))
        self.assertTrue(any(row['groups'] == ('king-safety',) for row in invalid['candidates']))

    def test_resealed_group_with_wrong_dataset_is_not_selectable(self):
        import json
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        path = create_group_training(self.labels, ['mobility']); run_group_training(path)
        def read(file): return json.loads(file.read_text(encoding='utf-8'))
        def seal(value):
            value.pop('identity', None); value['identity'] = digest(value); return value
        snapshot_path = path / 'snapshot.json'
        snapshot = read(snapshot_path); snapshot['dataset_identity'] = '不相容資料'
        seal(snapshot); write_json_atomic(snapshot_path, snapshot)
        calibration_path = path / 'calibration.json'
        calibration = read(calibration_path); calibration['snapshot_identity'] = snapshot['identity']
        seal(calibration); write_json_atomic(calibration_path, calibration)
        candidate_ids = {}
        for file in (path / 'groups/mobility/candidates').glob('*.json'):
            item = read(file); item['snapshot_identity'] = snapshot['identity']; item['calibration_identity'] = calibration['identity']
            seal(item); write_json_atomic(file, item); candidate_ids[item['strength']] = item['identity']
        frozen_path = path / 'groups/mobility/frozen.json'
        frozen = read(frozen_path); frozen['snapshot_identity'] = snapshot['identity']
        frozen['candidate_identity'] = candidate_ids[frozen['strength']]
        seal(frozen); write_json_atomic(frozen_path, frozen)
        report_path = path / 'groups/mobility/report.json'
        report = read(report_path); report['frozen_identity'] = frozen['identity']; report['calibration_identity'] = calibration['identity']
        seal(report); write_json_atomic(report_path, report)
        self.assertEqual(load_group_candidate(path, 'mobility')['dataset_identity'], '不相容資料')
        inventory = load_all_candidate_inventory(self.root / 'data')
        self.assertFalse(inventory['candidates'])
        self.assertTrue(any(row['path'] == str(path) for row in inventory['errors']))

    def test_resealed_legacy_input_with_tampered_label_is_not_selectable(self):
        import json
        from engine.learning.candidate_inventory import load_all_candidate_inventory
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic
        path = create_training(self.labels); run_training(path)
        def read(file): return json.loads(file.read_text(encoding='utf-8'))
        def seal(value):
            value.pop('identity', None); value['identity'] = digest(value); return value
        inputs_path = path / 'inputs.json'
        inputs = read(inputs_path); inputs['label_snapshot']['dataset_sha256'] = '偽造來源'
        write_json_atomic(inputs_path, inputs)
        snapshot_path = path / 'snapshot.json'
        snapshot = read(snapshot_path); snapshot['inputs_sha256'] = digest(inputs)
        seal(snapshot); write_json_atomic(snapshot_path, snapshot)
        for file in (path / 'candidates').glob('*.json'):
            item = read(file); item['snapshot_identity'] = snapshot['identity']
            seal(item); write_json_atomic(file, item)
        calibration_path = path / 'calibration.json'
        calibration = read(calibration_path); calibration['snapshot_identity'] = snapshot['identity']
        write_json_atomic(calibration_path, calibration)
        frozen_path = path / 'frozen.json'
        frozen = read(frozen_path); frozen['snapshot_identity'] = snapshot['identity']
        write_json_atomic(frozen_path, frozen)
        report_path = path / 'report.json'
        report = read(report_path); report['frozen_identity'] = digest(frozen)
        write_json_atomic(report_path, report)
        from engine.learning.training import load_training
        self.assertTrue(load_training(path)['report'])
        inventory = load_all_candidate_inventory(self.root / 'data')
        self.assertFalse(inventory['candidates'])
        self.assertTrue(any(row['path'] == str(path) for row in inventory['errors']))
