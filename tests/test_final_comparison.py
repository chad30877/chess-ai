import tempfile
import unittest
from copy import deepcopy
from tests.test_learned_comparison import candidate

class FinalComparisonTest(unittest.TestCase):
    def test_freeze_reopen_and_reuse_matching_plans(self):
        from engine.learning.comparison import create_comparison, load_comparison_plan
        from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
        with tempfile.TemporaryDirectory() as root:
            source = candidate()
            previous = create_comparison(root, source, roles=('learned',), stable=True)
            changed = deepcopy(source); changed['config']['terms']['isolated_pawns']['weight'] = 2
            path = freeze_final_comparison(root, [source, changed])
            final = load_final_comparison(path)
            self.assertEqual(len(final['candidates']), 2)
            self.assertEqual(final['candidates'][0]['path'], str(previous))
            for entry in final['candidates']:
                plan = load_comparison_plan(entry['path'])
                for baseline in ('material', 'stable'):
                    definition = plan['definitions'][baseline]
                    self.assertEqual(definition['planned_games'], 64)
                    self.assertEqual(len(definition['opening_lines']), 32)
            source['config']['terms']['isolated_pawns']['weight'] = 9
            self.assertNotEqual(load_final_comparison(path)['candidates'][0]['source']['config'], source['config'])
            with self.assertRaises(ValueError): freeze_final_comparison(root, [])
            with self.assertRaises(ValueError): freeze_final_comparison(root, [changed]*6)


    def test_reuses_existing_per_baseline_with_original_and_learned_roles(self):
        from engine.learning.comparison import create_comparison, load_comparison_plan
        from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
        with tempfile.TemporaryDirectory() as root:
            source = candidate()
            previous = create_comparison(root, source, stable=True)
            old = load_comparison_plan(previous)
            path = freeze_final_comparison(root, [source])
            final = load_final_comparison(path)
            plan = load_comparison_plan(final['candidates'][0]['path'])
            self.assertEqual(plan['definitions']['material']['id'], old['definitions']['material']['id'])
            self.assertEqual(plan['definitions']['stable']['id'], old['definitions']['stable']['id'])

    def test_different_conditions_are_not_reused(self):
        from engine.learning.comparison import create_comparison, load_comparison_plan
        from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
        with tempfile.TemporaryDirectory() as root:
            source = candidate()
            short = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='short', source={})]
            old = create_comparison(root, source, roles=('learned',), stable=True, opening_lines=short, max_plies=1)
            final = load_final_comparison(freeze_final_comparison(root, [source]))
            self.assertNotEqual(final['candidates'][0]['path'], str(old))
            plan = load_comparison_plan(final['candidates'][0]['path'])
            self.assertEqual(plan['definitions']['stable']['planned_games'], 64)

    def test_reuses_matching_existing_single_baseline(self):
        from engine.learning.comparison import create_comparison, load_comparison_plan
        from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
        with tempfile.TemporaryDirectory() as root:
            source = candidate()
            old = load_comparison_plan(create_comparison(root, source, roles=('learned',)))
            final = load_final_comparison(freeze_final_comparison(root, [source]))
            plan = load_comparison_plan(final['candidates'][0]['path'])
            self.assertEqual(plan['definitions']['material']['id'], old['definitions']['material']['id'])
            self.assertEqual(plan['definitions']['stable']['planned_games'], 64)
