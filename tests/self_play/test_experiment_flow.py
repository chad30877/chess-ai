"""從比較介面預覽到保存的實驗流程。"""
import json
from pathlib import Path
import tempfile
import unittest

from ui.batch_setup import EvaluationFields
from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import run_evaluation_comparison


class ExperimentFlowTest(unittest.TestCase):
    def test_preview_executes_frozen_settings_and_saves_work_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / 'configs/evaluation'
            config_dir.mkdir(parents=True)
            source = config_dir / 'stable.json'
            source.write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.action('comparison_generated', None)
            fields.values.update(weight_values='1, 2, 2', max_plies='0', depth='1')
            fields.action('comparison_preview', None)
            definition = fields.preview.to_dict()
            self.assertEqual((definition['duplicate_count'], definition['baseline_count']), (1, 1))
            self.assertEqual(definition['planned_games'], 2)
            source.write_text(json.dumps(EvaluationConfig(pst_weight=9).to_dict()), encoding='utf-8')
            result = run_evaluation_comparison(**fields.options())
            manifest = json.loads((result.path / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['settings']['experiment'], definition)
            pairs = json.loads((result.path / 'comparison.json').read_text(encoding='utf-8'))['pairs']
            self.assertEqual(len({g['work_id'] for p in pairs for g in p['games']}), 2)
            self.assertEqual(fields.options()['baseline'].evaluation_config.pst_weight, 1)
            fields.values['depth'] = '2'
            with self.assertRaises(ValueError):
                fields.options()

    def test_invalid_values_and_disabled_weights_cannot_launch(self):
        from engine.sessions.experiment import build_experiment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'configs/evaluation'
            folder.mkdir(parents=True)
            (folder / 'stable.json').write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.action('comparison_generated', None)
            for values in ('nan', '-1', 'inf', ''):
                fields.values['weight_values'] = values
                fields.action('comparison_preview', None)
                with self.assertRaises(ValueError):
                    fields.options()
            options = fields.file_options()
            for field in ('material.weight', 'passed_pawns.weight', 'piece_square.endgame_weight'):
                with self.assertRaises(ValueError):
                    build_experiment(options, field, '2')
            fields.values['weight_values'] = '1, 1'
            fields.action('comparison_preview', None)
            with self.assertRaises(ValueError):
                fields.options()
