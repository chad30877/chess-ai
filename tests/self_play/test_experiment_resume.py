"""保存後重建實驗工作，保留半組配對與既有棋譜。"""
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from ui.batch_setup import EvaluationFields
from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import run_evaluation_comparison

class ExperimentResumeTest(unittest.TestCase):
    def test_resume_half_pair_and_stale_progress_without_replaying_saved_game(self):
        from engine.sessions.experiment_resume import resume_experiment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'configs/evaluation'
            folder.mkdir(parents=True)
            (folder/'stable.json').write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.action('comparison_generated', None)
            fields.values.update(weight_values='2', max_plies='0', depth='1')
            fields.action('comparison_preview', None)
            states = []
            result = run_evaluation_comparison(**fields.options(), progress=lambda state: states.append(state),
                control=lambda: not states or states[-1]['saved_games'] < 1)
            before = list((result.path/'replays').glob('*.json'))
            self.assertEqual(len(before), 1)
            original = before[0].read_bytes()
            (result.path/'comparison.json').write_text('{}', encoding='utf-8')
            manifest = json.loads((result.path/'manifest.json').read_text(encoding='utf-8'))
            manifest['counts']['saved_games'] = 0
            (result.path/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (folder/'stable.json').write_text(json.dumps(EvaluationConfig(pst_weight=99).to_dict()), encoding='utf-8')
            subprocess.run([sys.executable, '-c',
                'from engine.sessions.experiment_resume import resume_experiment; import sys; resume_experiment(sys.argv[1], workers=2)',
                str(result.path)], check=True, timeout=30)
            self.assertEqual(before[0].read_bytes(), original)
            data = json.loads((result.path/'comparison.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['pairs'][0]['games']), 2)
            self.assertIsNone(data['progress']['paired_score_rate'])
            resume_experiment(result.path)
            self.assertEqual(len(list((result.path/'replays').glob('*.json'))), 2)

    def test_resume_rejects_active_executor_and_old_or_incompatible_snapshots(self):
        from engine.sessions.experiment_resume import resume_experiment, experiment_lock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'manifest.json').write_text(json.dumps({'schema_version':2,'settings':{}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '缺少'):
                resume_experiment(path)
            (path/'manifest.json').write_text(json.dumps({'schema_version':2,'settings':{'experiment':{'schema_version':99}}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '版本不相容'):
                resume_experiment(path)
            with experiment_lock(path):
                with self.assertRaisesRegex(ValueError, '已有執行者'):
                    with experiment_lock(path):
                        pass

    def test_interrupted_attempt_is_preserved_and_replaced_only_in_effective_results(self):
        from engine.sessions.experiment_resume import resume_experiment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'configs/evaluation'
            folder.mkdir(parents=True)
            (folder/'stable.json').write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.action('comparison_generated', None)
            fields.values.update(weight_values='2', max_plies='1', depth='1')
            fields.action('comparison_preview', None)
            calls = []
            def control():
                calls.append(None)
                return len(calls) < 4
            result = run_evaluation_comparison(**fields.options(), control=control)
            before = list((result.path/'replays').glob('*.json'))
            self.assertEqual(len(before), 1)
            self.assertEqual(json.loads(before[0].read_text(encoding='utf-8'))['metadata']['termination'], 'user_stop')
            original = before[0].read_bytes()
            resume_experiment(result.path)
            self.assertEqual(before[0].read_bytes(), original)
            self.assertEqual(len(list((result.path/'replays').glob('*.json'))), 3)
            self.assertEqual(json.loads((result.path/'manifest.json').read_text(encoding='utf-8'))['status'], 'completed')
            data = json.loads((result.path/'comparison.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['pairs'][0]['games']), 2)
            self.assertTrue(all(game['termination']=='max_plies' for game in data['pairs'][0]['games']))

            from engine.replay.comparison_catalog import load_comparison
            from engine.replay.replay_loader import load_replay_json
            summary = load_comparison(result.path / 'manifest.json')
            self.assertEqual(len(summary.games), 3)
            self.assertEqual(sum(game.historical for game in summary.games), 1)
            self.assertEqual(summary.candidate_summaries[0]['unfinished'], 2)
            for game in summary.games:
                self.assertIsNotNone(load_replay_json(str(game.path)))
