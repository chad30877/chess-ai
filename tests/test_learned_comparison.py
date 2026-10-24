"""學習候選到共同開局比較的來源、分母與續跑契約。"""
import json
from pathlib import Path
import tempfile
import unittest

from engine.evaluation.config import EvaluationConfig

ROOT = Path(__file__).resolve().parents[1]


def candidate():
    original = json.loads((ROOT/'configs/evaluation/learning-pawn.json').read_text(encoding='utf-8'))
    return dict(kind='single', groups=['pawn'], experiment_id='training-one', snapshot_identity='snapshot-one',
                candidate_identity='candidate-one', frozen_identity='frozen-one', config=original,
                original=original, stable=json.loads((ROOT/'configs/evaluation/stable.json').read_text(encoding='utf-8')),
                dataset_identity='data-one', label_identity='labels-one', calibration_identity='scale-one',
                report={split:{role:dict(mae=value, games=2, positions=3) for role,value in
                    [('original',1.5),('learned',1.0),('material',2.0),('stable',1.2)]} for split in ('validation','test')})


class LearnedComparisonTest(unittest.TestCase):
    def test_preview_freezes_role_source_full_configs_and_separate_reference_work(self):
        from engine.learning.comparison import create_comparison, load_comparison_plan, comparison_options
        with tempfile.TemporaryDirectory() as directory:
            source = candidate()
            path = create_comparison(directory, source, stable=True)
            plan = load_comparison_plan(path)
            self.assertEqual(plan['planned_games'],256)
            self.assertEqual(list(plan['definitions']),['material','stable'])
            self.assertEqual(plan['source']['candidate_identity'],'candidate-one')
            for baseline in ('material','stable'):
                options = comparison_options(path,baseline)
                definition = options['experiment_definition']
                self.assertEqual(definition['planned_games'],128)
                self.assertEqual(len(options['opening_lines']),32)
                self.assertEqual(options['workers'],4)
                self.assertEqual(options['baseline'].search_config.depth_plies,3)
                self.assertEqual(options['baseline'].search_config.quiescence_depth,4)
                self.assertEqual(options['baseline'].search_config.search_workers,1)
                self.assertEqual(options['baseline'].search_config.transposition_capacity,4096)
                self.assertEqual([c.evaluation_config.to_dict() for c in options['candidates']],[source['original'],source['config']])
                self.assertNotEqual(definition['candidates'][0]['id'],definition['candidates'][1]['id'])
            source['config']['terms']['material']['weight']=9
            self.assertEqual(load_comparison_plan(path)['source']['config']['terms']['material']['weight'],1)
            self.assertFalse(comparison_options(path,'stable')['baseline'].evaluation_config.phase_enabled)

    def test_real_depth_three_stop_reopen_report_and_replay_keep_conditions(self):
        from engine.learning.comparison import create_comparison, comparison_options, comparison_report
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        from engine.replay.replay_loader import load_replay_json
        lines=[dict(initial_fen=fen,moves_uci=[],name=str(i),source={'fixture':'合法短局'}) for i,fen in enumerate([
            '7k/8/8/8/8/8/P7/K7 w - - 0 1','7k/8/8/8/8/8/1P6/K7 w - - 0 1'])]
        with tempfile.TemporaryDirectory() as directory:
            path=create_comparison(directory,candidate(),stable=True,opening_lines=lines,max_plies=1)
            options=comparison_options(path,'material')
            with self.assertRaisesRegex(ValueError,'預覽不一致'):
                run_evaluation_comparison(**dict(options,workers=1))
            states=[]
            result=run_evaluation_comparison(**options,progress=states.append,
                control=lambda:not states or states[-1]['saved_games']<1)
            saved={p:p.read_bytes() for p in (result.path/'replays').glob('*.json')}
            stopped=comparison_report(path)['baselines']['material']
            self.assertEqual(sum(r['draws'] for r in stopped['candidates']),0)
            self.assertGreater(sum(r['pending_games']+r['unfinished'] for r in stopped['candidates']),0)
            resumed=comparison_options(path,'material')
            self.assertEqual(resumed['workers'],4)
            self.assertEqual(resumed['resume_path'],result.path)
            run_evaluation_comparison(**resumed)
            self.assertTrue(all(p.read_bytes()==content for p,content in saved.items()))
            report=comparison_report(path)
            self.assertEqual(report['baselines']['stable']['status'],'not-started')
            material=report['baselines']['material']
            self.assertEqual(material['requested_workers'],4)
            self.assertEqual(material['actual_workers'],4)
            self.assertEqual(len(material['candidates']),2)
            for row in material['candidates']:
                self.assertEqual(row['planned_games'],4)
                self.assertEqual(row['pending_games'],0)
                self.assertEqual(len(row['openings']),2)
                self.assertEqual(row['teacher']['validation']['mae'],1.5 if row['role']=='original' else 1.0)
                self.assertEqual(sum(o['wins']+o['draws']+o['losses']+o['unfinished'] for o in row['openings']),4)
            self.assertGreater(len(report['baselines']['material']['replays']),0)
            replay=next(r for p in report['baselines']['material']['replays'] if (r:=load_replay_json(str(p)))['moves_uci'])
            self.assertEqual(len(replay['moves_uci']),1)
            manifest=json.loads((result.path/'manifest.json').read_text(encoding='utf-8'))
            for side in [manifest['settings']['comparison']['participants']['baseline'],*manifest['settings']['comparison']['participants']['candidates']]:
                self.assertEqual(side['search']['max_depth'],3)
