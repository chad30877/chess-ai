import tempfile
import unittest
from engine.learning.rating import rating_from_counts, profile_rating
from tests.test_learned_comparison import candidate

class RatingReportTest(unittest.TestCase):
    def test_score_uses_real_results_and_finite_smoothing(self):
        self.assertAlmostEqual(rating_from_counts(1, 2, 1), 1500)
        self.assertAlmostEqual(rating_from_counts(4, 0, 0), 1881.6970038)
        self.assertAlmostEqual(rating_from_counts(0, 0, 4), 1118.3029962)

    def test_profile_without_comparisons_has_no_rating(self):
        with tempfile.TemporaryDirectory() as root:
            report = profile_rating(root, candidate()['config'])
            self.assertEqual(report['status'], 'unrated')
            self.assertIsNone(report['rating'])
            self.assertEqual(report['games'], 0)

    def test_comparison_report_shows_unrated_before_games(self):
        from engine.learning.comparison import create_comparison, comparison_report
        with tempfile.TemporaryDirectory() as root:
            path = create_comparison(root, candidate(), roles=('learned',), stable=True)
            row = comparison_report(path)['baselines']['stable']['candidates'][0]
            self.assertEqual(row['rating']['status'], 'unrated')
            self.assertEqual(row['rating']['games'], 0)

    def test_completed_small_batch_is_only_provisional_after_reopen(self):
        from engine.learning.comparison import create_comparison, comparison_report, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        lines = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in (1, 2)]
        with tempfile.TemporaryDirectory() as root:
            path = create_comparison(root, candidate(), roles=('learned',), stable=True, opening_lines=lines)
            run_evaluation_comparison(**comparison_options(path, 'material'))
            self.assertEqual(profile_rating(root, candidate()['config'])['status'], 'unrated')
            run_evaluation_comparison(**comparison_options(path, 'stable'))
            row = comparison_report(path)['baselines']['stable']['candidates'][0]
            self.assertEqual(row['rating']['status'], 'provisional')
            self.assertIsNone(row['rating']['rating'])
            self.assertEqual(row['rating']['provisional']['games'], 4)

    def test_stopped_half_pair_is_not_a_rating(self):
        from engine.learning.comparison import create_comparison, comparison_report, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        lines=[dict(initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1',moves_uci=[],name='',source={})]
        with tempfile.TemporaryDirectory() as root:
            path=create_comparison(root,candidate(),roles=('learned',),stable=True,opening_lines=lines)
            states=[]
            run_evaluation_comparison(**comparison_options(path,'stable'),progress=states.append,
                                      control=lambda: not states or states[-1]['saved_games'] < 1)
            report=comparison_report(path)['baselines']['stable']['candidates'][0]
            self.assertEqual(report['rating']['status'], 'unrated')
            self.assertIsNone(report['rating']['provisional'])
            run_evaluation_comparison(**comparison_options(path,'stable'))
            self.assertEqual(comparison_report(path)['baselines']['stable']['candidates'][0]['rating']['provisional']['games'],2)

    def test_full_batch_produces_formal_rating_and_identical_batch_is_deduplicated(self):
        from engine.learning.comparison import create_comparison, comparison_report, comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        lines = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in range(1, 33)]
        with tempfile.TemporaryDirectory() as root:
            path = create_comparison(root, candidate(), roles=('learned',), stable=True, opening_lines=lines)
            run_evaluation_comparison(**comparison_options(path, 'stable'))
            rating = comparison_report(path)['baselines']['stable']['candidates'][0]['rating']
            self.assertEqual(rating['status'], 'formal')
            self.assertEqual(rating['games'], 64)
            self.assertEqual(rating['wins'] + rating['draws'] + rating['losses'], 64)
            self.assertAlmostEqual(rating['rating'], rating_from_counts(rating['wins'], rating['draws'], rating['losses']))
            duplicate = create_comparison(root, candidate(), roles=('learned',), stable=True, opening_lines=lines)
            run_evaluation_comparison(**comparison_options(duplicate, 'stable'))
            again = comparison_report(duplicate)['baselines']['stable']['candidates'][0]['rating']
            self.assertEqual(again['games'], 64)
            extended_lines = lines[:-1] + [dict(lines[-1], initial_fen='7k/5Q2/6K1/8/8/8/8/8 w - - 0 33')]
            extended = create_comparison(root, candidate(), roles=('learned',), stable=True, opening_lines=extended_lines)
            states = []
            run_evaluation_comparison(**comparison_options(extended, 'stable'), progress=states.append,
                                      control=lambda: not states or states[-1]['saved_games'] < 2)
            stopped = comparison_report(extended)['baselines']['stable']['candidates'][0]['rating']
            self.assertEqual(stopped['rating'], rating['rating'])
            self.assertEqual(stopped['games'], 64)
            run_evaluation_comparison(**comparison_options(extended, 'stable'))
            accumulated = comparison_report(extended)['baselines']['stable']['candidates'][0]['rating']
            self.assertEqual(accumulated['games'], 66)
            truncated_lines=[dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1',moves_uci=[],name='',source={})]
            truncated = create_comparison(root, candidate(), roles=('learned',), stable=True,
                                          opening_lines=truncated_lines, max_plies=1)
            run_evaluation_comparison(**comparison_options(truncated, 'stable'))
            self.assertIsNone(profile_rating(root, candidate()['config'], max_plies=1)['rating'])
            self.assertIsNone(profile_rating(root, candidate()['config'], max_plies=1)['provisional'])
            self.assertEqual(profile_rating(root, candidate()['config'])['games'], 66)
            changed = candidate()['config']
            changed['terms']['isolated_pawns']['weight'] = 2
            self.assertEqual(profile_rating(root, changed)['status'], 'unrated')
            search = dict(rating['conditions']['search'], depth_plies=2)
            self.assertEqual(profile_rating(root, candidate()['config'], search=search)['status'], 'unrated')

