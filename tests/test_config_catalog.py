"""設定目錄的快速載入、來源檢查與可比排序。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine.learning.config_catalog import load_catalog, validate_catalog_row, composition
from engine.learning.teacher import digest
from engine.storage.batch_storage import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((ROOT / 'configs/evaluation/learning-king-safety.json').read_text(encoding='utf-8'))
        self.path = self.root / 'configs/evaluation/user.json'
        self.path.parent.mkdir(parents=True)
        write_json_atomic(self.path, self.config)
        write_json_atomic(self.root / 'configs/evaluation/stable.json', json.loads((ROOT / 'configs/evaluation/stable.json').read_text(encoding='utf-8')))

    def test_list_does_not_read_inputs_or_comparison_reports(self):
        original = Path.read_text
        reads = []
        def tracked(path, *args, **kwargs):
            reads.append(str(path))
            self.assertNotEqual(path.name, 'inputs.json')
            self.assertNotEqual(path.name, 'comparison.json')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', tracked): result = load_catalog(self.root / 'data/learning')
        row = next(r for r in result['candidates'] if r['path'] == str(self.path))
        self.assertIsNone(row['mae'])
        self.assertEqual(row['code'], '---K-')
        self.assertEqual(validate_catalog_row(row)['config'], row['source']['config'])
        write_json_atomic(self.path, {})
        with self.assertRaisesRegex(ValueError, '設定已變更'): validate_catalog_row(row)

    def test_user_config_can_prepare_comparison_without_training(self):
        from engine.learning.comparison_setup import preview_setup
        row = load_catalog(self.root / 'data/learning')['candidates'][0]
        result = preview_setup(self.root, self.root / 'data/learning', [row], 'screening')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['planned_games'], 16)

    def test_sort_uses_latest_compatible_metric_and_missing_last(self):
        from ui.candidate_inventory_view import InventoryView
        view = InventoryView(); view.open_first(self.root / 'data/learning')
        row = view.report['candidates'][0]
        old = dict(row, name='舊', mae=.1, metric_date=1, metric_context='same')
        new = dict(row, name='新', mae=.5, metric_date=2, metric_context='same')
        other = dict(row, name='其他教師', mae=.01, metric_date=3, metric_context='different', config_identity='other')
        missing = dict(row, name='未評估', config_identity='missing')
        view.report['candidates'] = [missing, old, new, other]
        view.sort, view.context = 'mae', 'same'
        self.assertEqual(view.value(old), .5)
        self.assertIsNone(view.value(other))
        self.assertEqual([i for i, _ in view.filtered()][:2], [2, 1])

    def test_rating_reads_real_pairs_and_keeps_opening_conditions_separate(self):
        from engine.learning.config_catalog import load_ratings
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        from tests.test_learned_comparison import candidate
        source = candidate()
        for move_number in (1, 2):
            lines = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {move_number}', moves_uci=[], name='', source={})]
            plan = create_comparison(self.root, source, roles=('learned',), stable=True, opening_lines=lines)
            run_evaluation_comparison(**comparison_options(plan, 'stable'))
        ratings, contexts = load_ratings(self.root)
        from engine.evaluation.config import EvaluationConfig
        values = ratings[digest(EvaluationConfig.from_dict(source['config']).to_dict())]
        self.assertEqual(len(values), 2)
        self.assertEqual(len(contexts), 2)
        self.assertTrue(all(value['status'] == '暫估' for value in values.values()))
