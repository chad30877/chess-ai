import tempfile
import unittest
from tests.test_learned_comparison import candidate
from engine.opening_book import OpeningBook
from engine.opening_lines import common_opening_lines


class ScreeningTest(unittest.TestCase):
    def test_freeze_selected_candidate_with_separate_eight_legal_lines(self):
        from engine.learning.screening import create_screening, load_screening
        with tempfile.TemporaryDirectory() as root:
            source = candidate()
            path = create_screening(root, source)
            plan = load_screening(path)
            self.assertEqual(plan['source']['config'], source['config'])
            definition = plan['definitions']['stable']
            self.assertEqual(definition['planned_games'], 16)
            self.assertEqual(len(definition['opening_lines']), 8)
            full = common_opening_lines(OpeningBook(), count=32)
            keys = lambda lines: {(x['initial_fen'], tuple(x['moves_uci'])) for x in lines}
            self.assertFalse(keys(full) & keys(definition['opening_lines']))
            source['config']['terms']['material']['weight'] = 9
            self.assertNotEqual(load_screening(path)['source']['config'], source['config'])

    def test_only_complete_pairs_can_eliminate_at_two_points(self):
        from engine.learning.screening import screening_outcome
        def pair(*outcomes):
            return [dict(status='completed', candidate_outcome=value, termination='checkmate') for value in outcomes]
        pairs = [pair('win', 'win')] + [pair('loss', 'loss') for _ in range(7)]
        result = screening_outcome(pairs, 'completed')
        self.assertEqual((result['wins'], result['draws'], result['losses'], result['score']), (2, 0, 14, 2))
        self.assertTrue(result['eliminated'])
        self.assertAlmostEqual(result['rating'], 1500 + 400 * __import__('math').log10(2.5 / 14.5))
        self.assertIsNone(screening_outcome(pairs[:-1], 'stopped')['eliminated'])
        pairs[-1][0]['termination'] = 'max_plies'
        self.assertIsNone(screening_outcome(pairs, 'completed')['eliminated'])
        pairs[-1][0]['termination'] = 'checkmate'
        pairs[-1][0]['status'] = 'failed'
        self.assertIsNone(screening_outcome(pairs, 'completed')['eliminated'])
        pairs[-1][0]['status'] = 'completed'
        pairs[-1][0]['candidate_outcome'] = 'draw'
        self.assertFalse(screening_outcome(pairs, 'completed')['eliminated'])

class ScreeningUiTest(unittest.TestCase):
    def test_select_candidate_freeze_and_reopen_without_starting_games(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from apps.chess_application import ChessApplication, APP_SIZE
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as root, patch('apps.chess_application.PROJECT_ROOT', __import__('pathlib').Path(root)), ThreadPoolExecutor(1) as executor:
            app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=executor)
            app.mode = 'learning'; app.learning.page = 'inventory'
            source = candidate()
            app.learning.inventory.report = dict(candidates=[dict(source=source, groups=['pawn'], kind='single', mae=1., games=2, positions=3, stages={x:dict(games=0,positions=0) for x in ('opening','middlegame','endgame')})], complete=False, dataset_identity='d', label_identity='l', calibration=None, test_data_identity='t', exposure='', source_identity='fixture')
            app.learning.inventory.report['candidates'][0]['source'].update(test_data_identity='t',prior_test_experiments=[])
            def click(action):
                app.render(); button = next(b for b in app.buttons if b.action == action)
                self.assertTrue(button.enabled, action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
            self.assertIsNone(app.batch)
            click('learning_inventory_screen')
            self.assertEqual(app.learning.page, 'screening')
            self.assertIsNone(app.batch)
            path = app.learning.screening.path
            self.assertEqual(app.learning.screening.report['status'], 'not-started')
            click('learning_screening_back')
            click('learning_inventory_screen')
            self.assertEqual(app.learning.screening.path, path)
            self.assertIsNone(app.batch)
            from engine.learning.screening import screening_report
            report = screening_report(path)
            report.update(complete=True, eliminated=False, games=16, wins=3, draws=0, losses=13, score=3)
            eliminated = dict(report, eliminated=True, wins=2, losses=14, score=2)
            with patch('ui.screening_view.screening_report', return_value=eliminated):
                app.render()
                button = next(b for b in app.buttons if b.action == 'learning_screening_select')
                self.assertFalse(button.enabled)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
                self.assertEqual(app.learning.screening.selected, [])
                self.assertFalse(next(b for b in app.buttons if b.action == 'learning_screening_final_freeze').enabled)
            with patch('ui.screening_view.screening_report', return_value=report):
                click('learning_screening_select')
                self.assertEqual(len(app.learning.screening.selected), 1)
                click('learning_screening_final_freeze')
                self.assertIsNone(app.batch)
                click('learning_screening_final_open')
                self.assertEqual(app.learning.page, 'comparison')
                self.assertEqual(set(app.learning.comparison.report['baselines']), {'material', 'stable'})
                self.assertEqual(app.learning.comparison.report['plan']['planned_games'], 128)
                click('learning_compare_back')
                self.assertEqual(app.learning.page, 'screening')
                self.assertIsNone(app.batch)
                click('learning_screening_back')
                click('learning_inventory_screen')
                self.assertEqual(len(app.learning.screening.selected), 1)
                click('learning_screening_select')
                self.assertEqual(len(app.learning.screening.selected), 0)
                from copy import deepcopy
                sources = []
                for value in range(5):
                    entry = deepcopy(source)
                    entry['config']['terms']['material']['weight'] = 10 + value
                    sources.append(entry)
                app.learning.screening.selected = sources
                click('learning_screening_select')
                self.assertEqual(len(app.learning.screening.selected), 5)
                self.assertIn('最多選擇五個', app.learning.screening.message)
                self.assertIsNone(app.batch)
            app.close()


class ScreeningSavedFlowTest(unittest.TestCase):
    def test_stop_reopen_and_complete_pairs_do_not_create_formal_rating(self):
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.learning.screening import screening_report
        from engine.learning.rating import profile_rating
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        lines = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in range(1, 9)]
        with tempfile.TemporaryDirectory() as root:
            path = create_comparison(root, candidate(), roles=('learned',), screening=True, opening_lines=lines)
            states = []
            run_evaluation_comparison(**comparison_options(path, 'stable'), progress=states.append,
                control=lambda: not states or states[-1]['saved_games'] < 1)
            stopped = screening_report(path)
            self.assertIsNone(stopped['eliminated'])
            self.assertLess(stopped['games'], 16)
            self.assertEqual(profile_rating(root, candidate()['config'])['status'], 'unrated')
            run_evaluation_comparison(**comparison_options(path, 'stable'))
            result = screening_report(path)
            self.assertEqual(result['games'], 16)
            self.assertTrue(result['complete'])
            self.assertIsNotNone(result['eliminated'])
            self.assertEqual(profile_rating(root, candidate()['config'])['status'], 'unrated')

    def test_failure_and_truncated_games_do_not_trigger_elimination(self):
        from unittest.mock import patch
        from engine.learning.comparison import create_comparison, comparison_options
        from engine.learning.screening import screening_report
        from engine.learning.rating import profile_rating
        from engine.sessions.evaluation_comparison import run_evaluation_comparison, play_game
        mate = [dict(initial_fen=f'7k/5Q2/6K1/8/8/8/8/8 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in range(1, 9)]
        with tempfile.TemporaryDirectory() as root:
            path = create_comparison(root, candidate(), roles=('learned',), screening=True, opening_lines=mate[:1])
            calls = []
            def fail_second(*args, **kwargs):
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError('受控失敗')
                return play_game(*args, **kwargs)
            with patch('engine.sessions.evaluation_comparison.play_game', side_effect=fail_second):
                with self.assertRaisesRegex(RuntimeError, '受控失敗'):
                    run_evaluation_comparison(**comparison_options(path, 'stable'))
            self.assertIsNone(screening_report(path)['eliminated'])
            self.assertEqual(screening_report(path)['games'], 0)
            self.assertEqual(profile_rating(root, candidate()['config'])['status'], 'unrated')
            run_evaluation_comparison(**comparison_options(path, 'stable'))
            self.assertEqual(screening_report(path)['games'], 2)
            self.assertIsNone(screening_report(path)['eliminated'])
            lines = [dict(initial_fen=f'7k/8/8/8/8/8/P7/K7 w - - 0 {i}', moves_uci=[], name=str(i), source={}) for i in range(1, 9)]
            truncated = create_comparison(root, candidate(), roles=('learned',), screening=True, opening_lines=lines, max_plies=1)
            run_evaluation_comparison(**comparison_options(truncated, 'stable'))
            self.assertIsNone(screening_report(truncated)['eliminated'])
            self.assertEqual(screening_report(truncated)['games'], 0)
