import unittest
from tests.test_learned_comparison import candidate
import tests.test_weight_training as fixtures


class HeldoutTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp
    def test_same_training_data_is_never_independent(self):
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout, load_heldout
        from engine.learning.labeling import load_labeled_dataset
        labeled = load_labeled_dataset(self.labels)
        source = candidate()
        source.update(dataset_identity=labeled['snapshot']['dataset_sha256'], label_identity=labeled['snapshot']['identity'],
                      label_path=str(self.labels), calibration={'scale': .01, 'healthy': True, 'identity':'scale-one'})
        final = freeze_final_comparison(self.root, [source])
        path = freeze_heldout(self.root, final)
        report = evaluate_heldout(path, self.labels)
        self.assertFalse(report['independent'])
        self.assertTrue(any('曝光' in x for x in report['limitations']))
        self.assertEqual(load_heldout(path)['report'], report)

    def test_frozen_report_cannot_be_replaced(self):
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout, load_heldout
        from engine.learning.labeling import load_labeled_dataset
        import json
        labeled = load_labeled_dataset(self.labels)
        source = candidate()
        source.update(dataset_identity=labeled['snapshot']['dataset_sha256'], label_identity=labeled['snapshot']['identity'],
                      label_path=str(self.labels), calibration={'scale': .01, 'healthy': True, 'identity':'scale-one'})
        final = freeze_final_comparison(self.root, [source])
        path = freeze_heldout(self.root, final)
        frozen_before = (path/'snapshot.json').read_bytes()
        report = evaluate_heldout(path, self.labels)
        self.assertEqual(report['results'][0]['metric']['games'], labeled['summary']['splits']['test']['games'])
        self.assertEqual(report['results'][0]['metric']['positions'], labeled['summary']['splits']['test']['positions'])
        with self.assertRaises(ValueError):
            evaluate_heldout(path, self.labels)
        self.assertEqual((path/'snapshot.json').read_bytes(), frozen_before)
        self.assertEqual(load_heldout(path)['report'], report)

    def test_new_source_teacher_compatibility_and_saved_result(self):
        import io
        import chess.pgn
        from engine.learning.dataset import create_dataset
        from engine.learning.teacher import run_pilot, choose_budget
        from engine.learning.labeling import create_labeling, run_labeling, load_labeled_dataset
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout, load_heldout
        from tests.test_learning_dataset import pgn_games
        old = load_labeled_dataset(self.labels)
        source = candidate()
        source.update(dataset_identity=old['snapshot']['dataset_sha256'], label_identity=old['snapshot']['identity'],
                      label_path=str(self.labels), calibration={'scale': .01, 'healthy': True, 'identity':'scale-one'})
        final = freeze_final_comparison(self.root, [source])
        path = freeze_heldout(self.root, final)
        stream=io.StringIO(pgn_games(16)); games=[]
        while (game := chess.pgn.read_game(stream)) is not None: games.append(str(game))
        fresh_file=self.root/'fresh.pgn'; fresh_file.write_text('\n\n'.join(games[8:]),encoding='utf-8')
        dataset=create_dataset(self.root/'new', fresh_file)
        pilot=run_pilot(dataset,old['snapshot']['teacher']['command']); choose_budget(pilot,50000)
        new_labels=create_labeling(dataset,pilot); run_labeling(new_labels)
        labeled=load_labeled_dataset(new_labels)
        report=evaluate_heldout(path,new_labels)
        self.assertNotEqual(report['dataset_identity'],old['snapshot']['dataset_sha256'])
        self.assertNotIn('教師條件與候選來源不相容',report['limitations'])
        self.assertEqual(report['results'][0]['metric']['games'],labeled['summary']['splits']['test']['games'])
        self.assertEqual(report['results'][0]['metric']['positions'],labeled['summary']['splits']['test']['positions'])
        self.assertIn('測試有效盤數不足 30，證據不足',report['limitations'])
        (new_labels/'dataset.json').write_text('{}',encoding='utf-8')
        self.assertEqual(load_heldout(path)['report'], report)
        with self.assertRaises(ValueError): evaluate_heldout(path,new_labels)

    def test_unavailable_source_and_unhealthy_calibration_are_limitations(self):
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout
        source = candidate()
        source.update(label_path=str(self.root/'missing'), calibration={'scale': .01,'healthy': False})
        path = freeze_heldout(self.root, freeze_final_comparison(self.root, [source]))
        report = evaluate_heldout(path, self.labels)
        self.assertFalse(report['independent'])
        self.assertIsNone(report['results'][0]['metric'])
        self.assertTrue(any('無法核對' in text for text in report['limitations']))
        self.assertTrue(any('校準' in text for text in report['limitations']))

    def test_different_teacher_budget_is_reported(self):
        from engine.learning.teacher import run_pilot, choose_budget
        from engine.learning.labeling import create_labeling, run_labeling, load_labeled_dataset
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout
        old=load_labeled_dataset(self.labels)
        source=candidate(); source.update(dataset_identity=old['snapshot']['dataset_sha256'],
            label_identity=old['snapshot']['identity'],label_path=str(self.labels),
            calibration={'scale':.01,'healthy':True,'identity':'scale-one'})
        path=freeze_heldout(self.root,freeze_final_comparison(self.root,[source]))
        dataset=self.labels.parent.parent
        pilot=run_pilot(dataset,old['snapshot']['teacher']['command']); choose_budget(pilot,200000)
        changed=create_labeling(dataset,pilot); run_labeling(changed)
        report=evaluate_heldout(path,changed)
        self.assertIn('教師條件與候選來源不相容',report['limitations'])
        self.assertFalse(report['independent'])

    def test_heldout_report_hand_worked_material_error(self):
        import chess
        from collections import defaultdict
        from engine.learning.final_comparison import freeze_final_comparison
        from engine.learning.heldout import freeze_heldout, evaluate_heldout
        from engine.learning.labeling import load_labeled_dataset
        labeled=load_labeled_dataset(self.labels)
        source=candidate(); source.update(dataset_identity=labeled['snapshot']['dataset_sha256'],
            label_identity=labeled['snapshot']['identity'], label_path=str(self.labels),
            calibration={'scale':.01,'healthy':True,'identity':'scale-one'})
        for name, term in source['config']['terms'].items(): term['enabled'] = name == 'material'
        rows=[r for r in labeled['positions'] if r['split']=='test']
        errors=defaultdict(list)
        # 與正式評分器分開，直接依棋子數與教師分數手算每盤誤差。
        for row in rows:
            board=chess.Board(row['fen'])
            balance=sum(value*(len(board.pieces(piece,chess.WHITE))-len(board.pieces(piece,chess.BLACK)))
                for piece,value in ((chess.PAWN,1),(chess.KNIGHT,3),(chess.BISHOP,3),(chess.ROOK,5),(chess.QUEEN,9)))
            errors[row['game_id']].append(abs(balance-row['label']['white_cp']/100))
        means=[sum(values)/len(values) for values in errors.values()]
        path=freeze_heldout(self.root,freeze_final_comparison(self.root,[source]))
        report=evaluate_heldout(path,self.labels)
        metric=report['results'][0]['metric']
        self.assertAlmostEqual(metric['mae'],sum(means)/len(means))
        self.assertEqual(metric['games'],len(means))
        self.assertEqual(metric['positions'],len(rows))
