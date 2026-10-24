"""學習公開數值契約：逐盤等權與正式分階段評分一致。"""
import unittest
from pathlib import Path
import json
import chess
from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.learning.training import calibrate, extract_features, evaluate_errors, training_rules
ROOT = Path(__file__).resolve().parents[1]

class TrainingNumericTest(unittest.TestCase):
    def test_hand_worked_game_equal_calibration_and_empty_stages(self):
        stable=EvaluationConfig.from_dict(json.loads((ROOT/'configs/evaluation/stable.json').read_text()))
        rows=[dict(game_id=g,fen='7k/8/8/8/8/8/'+p+'/K7 w - - 0 1',stage='endgame',label={'white_cp':t})
              for g,p,t in [('a','P7',100),('b','PP6',200),('b','PP6',200)]]
        result=calibrate(rows,stable,training_rules())
        # stable 為 .99／2.02；兩盤各半權，倍率 251.5/25000，MAE=(.016+.008)/2。
        self.assertAlmostEqual(result['scale'],.01006)
        self.assertEqual(result['games'],2)
        report=evaluate_errors(rows,stable,result['scale'])
        self.assertIsNone(report['stages']['opening']['mae'])
        self.assertEqual(report['games'],2)
        self.assertAlmostEqual(report['mae'],.012)

    def test_features_match_formal_evaluation_with_zero_endgame_weights(self):
        config=EvaluationConfig.from_dict(json.loads((ROOT/'configs/evaluation/learning-piece-square.json').read_text()))
        for fen in ('7k/8/8/8/3N4/8/P7/K7 w - - 0 1',chess.STARTING_FEN):
            board=chess.Board(fen)
            bias,features,weights=extract_features(board,config,['piece_square'])
            self.assertAlmostEqual(bias+sum(a*b for a,b in zip(features,weights)),HandcraftedEvaluator(config=config).evaluate(board),places=12)


class TrainingFlowTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from engine.learning.dataset import create_dataset
        from engine.learning.teacher import run_pilot, choose_budget
        from engine.learning.labeling import create_labeling, run_labeling
        from tests.test_learning_dataset import pgn_games
        from tests.helpers.uci_teacher import make_engine
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        source=self.root/'games.pgn'; source.write_text(pgn_games(8),encoding='utf-8')
        dataset=create_dataset(self.root/'data',source)
        command=make_engine(self.root); script=Path(command[1])
        code=script.read_text(encoding='utf-8')
        code=code.replace('import sys',f'import sys\nsys.path.insert(0,{str(ROOT)!r})')
        code=code.replace('  best=next(iter(board.legal_moves)).uci()',"  best=next((m for m in board.legal_moves if not board.is_capture(m) and not m.promotion),next(iter(board.legal_moves))).uci()\n  from engine.evaluation.evaluator import HandcraftedEvaluator\n  score=round(HandcraftedEvaluator().evaluate(board)*100)*(1 if board.turn else -1)")
        code=code.replace("score cp 25 nodes '+line", "score cp '+str(score)+' nodes '+line")
        script.write_text(code,encoding='utf-8')
        pilot=run_pilot(dataset,command); choose_budget(pilot,50000)
        self.labels=create_labeling(dataset,pilot); run_labeling(self.labels)

    def test_real_solver_validation_freeze_reopen_and_legal_config_export(self):
        from engine.learning.training import create_training, run_training, load_training, save_training_config
        path=create_training(self.labels)
        run_training(path)
        result=load_training(path)
        self.assertEqual(result['status'],'completed',result.get('error'))
        self.assertEqual(result['completed'],3)
        self.assertAlmostEqual(result['calibration']['scale'],.01)
        self.assertTrue(result['calibration']['healthy'])
        self.assertEqual(result['frozen']['strength'],'strong')
        self.assertEqual(set(result['report']['test']),{'material','original','learned','stable'})
        self.assertGreater(result['report']['test']['learned']['games'],0)
        saved=save_training_config(path,self.root/'learned.json')
        config=EvaluationConfig.from_dict(json.loads(saved.read_text(encoding='utf-8')))
        self.assertTrue(config.phase_enabled)
        self.assertEqual(dict(config.piece_values),{'P':1,'N':3,'B':3,'R':5,'Q':9})
        self.assertFalse(any(t.enabled for t in config.mobility_terms.values()))
        # 摘要寫入落後不能推翻正式提交的測試報告，也不能引起重新選擇。
        (path/'status.json').write_text(json.dumps(dict(status='failed',elapsed_seconds=0,error='摘要落後')),encoding='utf-8')
        self.assertEqual(load_training(path)['status'],'completed')
        before={p.name:p.read_bytes() for p in path.glob('*.json')}
        run_training(path)
        self.assertEqual({p.name:p.read_bytes() for p in path.glob('*.json')},before)

    def test_stop_real_worker_deadline_and_resume_preserve_completed_candidates(self):
        import multiprocessing
        from threading import Event
        from engine.learning.training import create_training,run_training,load_training
        path=create_training(self.labels)
        stop=Event(); seen=[]
        def cancel(state):
            if state.get('worker_pid') and state['completed']==1:
                seen.append(state['worker_pid']); stop.set()
        run_training(path,stop=stop,progress=cancel)
        saved=load_training(path)
        self.assertEqual(saved['status'],'stopped')
        self.assertEqual(saved['completed'],1)
        self.assertTrue(seen)
        self.assertFalse(any(p.pid in seen for p in multiprocessing.active_children()))
        first=(path/'candidates/weak.json').read_bytes()
        clock=[0]
        def expire(state):
            if state.get('worker_pid'): clock[0]=28800
        run_training(path,now=lambda:clock[0],progress=expire)
        self.assertEqual(load_training(path)['completed'],1)
        self.assertIn('八小時',load_training(path)['error'])
        run_training(path)
        self.assertEqual(load_training(path)['status'],'completed')
        self.assertEqual((path/'candidates/weak.json').read_bytes(),first)
        self.assertTrue(all(v>=0 for c in load_training(path)['candidates'].values() for v in c['solver']['weights']))

class ConstraintContractTest(unittest.TestCase):
    def test_hand_worked_nonnegative_zero_start_and_no_percentage_cap(self):
        from engine.learning.training import fit_position_weights
        from copy import deepcopy
        base=json.loads((ROOT/'configs/evaluation/learning-piece-square.json').read_text())
        row=dict(game_id='a',fen='7k/8/8/8/8/8/P7/K7 w - - 0 1',stage='endgame',label={'white_cp':0})
        config=EvaluationConfig.from_dict(base)
        # 殘局固定子力 1、PST 原始值 .02，λ=.001：下界 0／最適 15；零初始尺度 .1。
        fitted,_=fit_position_weights([row],config,['piece_square'],.01,.001,training_rules())
        self.assertAlmostEqual(fitted.endgame_pst_weight,0,places=10)
        self.assertAlmostEqual(fitted.pst_weight,1,places=12)
        row['label']['white_cp']=200
        fitted,_=fit_position_weights([row],config,['piece_square'],.01,.001,training_rules())
        self.assertAlmostEqual(fitted.endgame_pst_weight,15,places=8)
        zero=deepcopy(base); zero['terms']['piece_square']['endgame_weight']=0
        fitted,_=fit_position_weights([row],EvaluationConfig.from_dict(zero),['piece_square'],.01,.001,training_rules())
        self.assertAlmostEqual(fitted.endgame_pst_weight, .199203187250996,places=8)
        self.assertEqual(dict(fitted.piece_values),{'P':1,'N':3,'B':3,'R':5,'Q':9})



    def test_degenerate_or_unstable_calibration_never_claims_reliable_ranking(self):
        stable=EvaluationConfig.from_dict(json.loads((ROOT/'configs/evaluation/stable.json').read_text()))
        def sample(game,cp): return dict(game_id=game,fen='7k/8/8/8/8/8/P7/K7 w - - 0 1',stage='endgame',label={'white_cp':cp})
        for cp in (0,-100,float('nan')):
            with self.assertRaisesRegex(ValueError,'校準'):
                calibrate([sample('a',cp)],stable,training_rules())
        result=calibrate([sample('a',1),sample('b',100)],stable,training_rules())
        self.assertFalse(result['healthy'])
        self.assertTrue(result['warning'])

class ValidationSelectionTest(unittest.TestCase):
    setUp=TrainingFlowTest.setUp
    def test_test_results_cannot_replace_validation_choice_and_changed_data_is_new_experiment(self):
        from engine.learning.training import create_training,run_training,load_training
        path=create_training(self.labels)
        run_training(path)
        first=load_training(path)
        second_path=create_training(self.labels)
        second=load_training(second_path)
        self.assertNotEqual(first['snapshot']['id'],second['snapshot']['id'])
        self.assertEqual(second['snapshot']['test_data_identity'],first['snapshot']['test_data_identity'])
        self.assertEqual(second['snapshot']['prior_test_experiments'][0]['experiment_id'],first['snapshot']['id'])
        self.assertEqual(first['frozen']['validation'],first['candidates'][first['frozen']['strength']]['validation'])
        # 重開及再次執行只展示正式保存報告，不能重新以測試挑候選。
        report=(path/'report.json').read_bytes(); frozen=(path/'frozen.json').read_bytes()
        run_training(path)
        self.assertEqual((path/'report.json').read_bytes(),report)
        self.assertEqual((path/'frozen.json').read_bytes(),frozen)
