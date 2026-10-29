import unittest
from tests import test_weight_training as fixtures
from engine.learning.group_training import create_group_training, run_group_training
from engine.learning.combination_training import create_combination, run_combination

class InventoryTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_inventory_reopens_saved_results_and_ranks_distinct_candidates(self):
        from engine.learning.candidate_inventory import load_candidate_inventory
        source = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(source)
        combination = create_combination(source, ['mobility', 'king-safety'])
        run_combination(combination)
        report = load_candidate_inventory(source)
        self.assertEqual(len(report['entries']), 31)
        self.assertFalse(report['complete'])
        self.assertEqual(report['entries'][('mobility',)]['single'], 'completed')
        self.assertEqual(report['entries'][('mobility', 'king-safety')]['direct'], 'completed')
        self.assertEqual(report['entries'][('mobility', 'king-safety')]['joint'], 'completed')
        self.assertEqual(report['entries'][('pawn',)]['single'], 'missing')
        self.assertEqual(report['candidates'], sorted(report['candidates'], key=lambda c: c['mae']))
        self.assertEqual(len({c['config_identity'] for c in report['candidates']}), len(report['candidates']))
        self.assertTrue(all(c['games'] > 0 and c['positions'] > 0 for c in report['candidates']))
        self.assertTrue(report['exposure'])
        self.assertEqual(report, load_candidate_inventory(source))

class InventoryUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_inventory_event_does_not_start_games_and_reopens(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import pygame
        from apps.chess_application import ChessApplication, APP_SIZE
        from engine.learning.candidate_inventory import load_candidate_inventory
        source = create_group_training(self.labels, ['mobility', 'king-safety'])
        run_group_training(source)
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                if action in ('learning_groups', 'learning_training', 'learning_combinations', 'learning_inventory') and app.learning.page_loading is not None:
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: app.learning.page_loading.result(timeout=30)
                    app.render()
                if action == 'learning_labels':
                    future = app.learning.labels.loading
                    if hasattr(app.executor, 'finish'): app.executor.finish()
                    else: future.result(timeout=15)
                    app.render()
            click('mode:learning')
            app.learning.root = self.root / 'data'
            click('learning_goal_results')
            app.learning.page_loading.result(timeout=30); app.render()
            click('learning_results_open:0')
            app.learning.page_loading.result(timeout=30); app.render()
            self.assertEqual(app.learning.group_training.path, source)
            self.assertGreater(app.learning.group_training.state['completed_groups'], 0)
            self.assertFalse(next(b for b in app.buttons if b.action == 'learning_groups_new').enabled)
            click('learning_nav_inventory')
            app.learning.page_loading.result(timeout=30); app.render()
            self.assertTrue(app.learning.inventory.report['candidates'])
            self.assertEqual(app.learning.inventory.report['candidates'][0]['source']['snapshot_identity'],
                             load_candidate_inventory(source)['source_identity'])
            self.assertIsNone(app.batch)
            click('learning_nav_data'); app.learning.open(self.labels.parents[1])
            click('learning_teacher'); click('learning_labels'); click('learning_groups'); click('learning_combinations')
            click('learning_inventory')
            self.assertEqual(app.learning.page, 'inventory')
            self.assertFalse(app.learning.inventory.report['complete'])
            self.assertEqual(app.learning.inventory.report['source_identity'], app.learning.combination.sources['mobility']['snapshot_identity'])
            self.assertFalse(app.learning.combination.active())
            click('learning_inventory_back')
            self.assertEqual(app.learning.page, 'combination')
            click('learning_inventory')
            self.assertTrue(app.learning.inventory.report['candidates'])
            app.close()

class FullInventoryTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp

    def test_full_coverage_ranking_incompatible_and_failed_saved_results(self):
        from copy import deepcopy
        from itertools import combinations
        import json
        from engine.learning.group_training import GROUPS, load_group_training
        from engine.learning.candidate_inventory import load_candidate_inventory
        from engine.learning.teacher import digest
        from engine.storage.batch_storage import write_json_atomic

        source = create_group_training(self.labels)
        run_group_training(source)
        self.assertEqual(load_group_training(source)['status'], 'completed')
        def save(path, value):
            value = deepcopy(value); value['identity'] = digest(value)
            write_json_atomic(path, value)
            return value
        paths = []
        for number, groups in enumerate(g for n in range(2, 6) for g in combinations(GROUPS, n)):
            path = create_combination(source, groups); paths.append(path)
            snapshot = json.loads((path/'snapshot.json').read_text(encoding='utf-8'))
            metric = dict(mae=(number+1)/1000000, games=3, positions=5,
                stages={s:dict(mae=None, games=0, positions=0) for s in ('opening','middlegame','endgame')})
            config = snapshot['direct']
            frozen = save(path/'direct/frozen.json', dict(kind='direct', groups=list(groups), config=config,
                snapshot_identity=snapshot['identity'], calibration_identity=snapshot['calibration_identity']))
            save(path/'direct/report.json', dict(frozen_identity=frozen['identity'], calibration_identity=snapshot['calibration_identity'],
                validation={'learned':metric}, data_use=snapshot['data_use']))
            joint = deepcopy(config)
            if number:
                joint['terms'][snapshot['terms'][0]]['weight'] += 0.012345 + number/10000
            candidate = save(path/'candidates/weak.json', dict(snapshot_identity=snapshot['identity'],
                calibration_identity=snapshot['calibration_identity'], strength='weak', config=joint, validation=metric))
            frozen = save(path/'joint/frozen.json', dict(kind='joint', groups=list(groups), config=joint, strength='weak',
                validation=metric, candidate_identity=candidate['identity'], snapshot_identity=snapshot['identity'],
                calibration_identity=snapshot['calibration_identity']))
            save(path/'joint/report.json', dict(frozen_identity=frozen['identity'], calibration_identity=snapshot['calibration_identity'],
                validation={'learned':metric}, data_use=snapshot['data_use']))
        report = load_candidate_inventory(source)
        self.assertTrue(report['complete'], report['errors'])
        self.assertEqual(len(report['entries']),31)
        self.assertEqual(sum(len(entry) for entry in report['entries'].values()),57)
        self.assertTrue(all(s == 'completed' for e in report['entries'].values() for s in e.values()))
        self.assertEqual(len(report['candidates']),10)
        self.assertEqual([c['mae'] for c in report['candidates']], [.000001,.000002,.000002,.000003,.000003,.000004,.000004,.000005,.000005,.000006])
        self.assertEqual(len({c['config_identity'] for c in report['candidates']}),10)
        self.assertEqual(report, load_candidate_inventory(source))
        # 經由實際應用程式事件呈現十個候選，不建立對局。
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import pygame
        from apps.chess_application import ChessApplication, APP_SIZE
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT', self.root), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'
            app.learning.combination.open(source)
            app.learning.combination.weights = True
            app.learning.page = 'combination'
            app.render()
            button = next(b for b in app.buttons if b.action == 'learning_inventory')
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            app.learning.page_loading.result(timeout=30)
            app.render()
            self.assertEqual(app.learning.page, 'inventory')
            self.assertEqual(len(app.learning.inventory.report['candidates']), 10)
            self.assertIsNone(app.learning.comparison.path)
            self.assertFalse((self.root/'data/learning-comparisons').exists())
            app.close()
        # 權威快照中的來源不相容時，不能納入完整排名。
        bad_snapshot = json.loads((paths[1]/'snapshot.json').read_text(encoding='utf-8'))
        bad_snapshot.pop('identity')
        bad_snapshot['sources'][0]['dataset_identity'] = 'different'
        save(paths[1]/'snapshot.json', bad_snapshot)
        incompatible = load_candidate_inventory(source)
        self.assertFalse(incompatible['complete'])
        self.assertTrue(any(e['path'] == str(paths[1]) for e in incompatible['errors']))
        # 損壞的結果不能讓排名偽裝成完整；其餘同源結果仍可查看。
        (paths[0]/'direct/report.json').write_text('{}', encoding='utf-8')
        broken = load_candidate_inventory(source)
        self.assertFalse(broken['complete'])
        self.assertTrue(any(e['path'] == str(paths[0]) for e in broken['errors']))
        self.assertTrue(broken['candidates'])
        # 沒有完成結果的失敗批次須在盤點顯示失敗。
        failed_path = paths[-1]
        (failed_path/'direct/report.json').unlink()
        (failed_path/'joint/report.json').unlink()
        write_json_atomic(failed_path/'status.json', dict(status='failed', elapsed_seconds=1, error='測試失敗'))
        failed = load_candidate_inventory(source)
        self.assertEqual(failed['entries'][tuple(GROUPS)], {'direct':'failed', 'joint':'failed'})
