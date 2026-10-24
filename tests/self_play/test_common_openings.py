"""共同開局經比較、保存及回放保留完整歷史。"""
import json
from pathlib import Path
import tempfile
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.replay.replay_loader import load_replay_json
from engine.replay.replay_session import ReplaySession
from engine.sessions.evaluation_comparison import ComparisonParticipant, run_evaluation_comparison


class CommonOpeningTest(unittest.TestCase):
    def test_comparison_replays_prefix_and_preserves_repetition_history(self):
        prefix = ['g1f3', 'g8f6', 'f3g1', 'f6g8'] * 2
        line = dict(initial_fen=chess.STARTING_FEN, moves_uci=prefix, name='重複歷史', source={})
        with tempfile.TemporaryDirectory() as directory:
            states = []
            result = run_evaluation_comparison(
                baseline=ComparisonParticipant.greedy('基準', EvaluationConfig()),
                candidate=ComparisonParticipant.greedy('候選', EvaluationConfig()),
                opening_lines=[line], max_plies=8, batch_root=Path(directory)/'batches', progress=states.append)
            for path in (result.path/'replays').glob('*.json'):
                data = load_replay_json(str(path))
                self.assertEqual(data['moves_uci'], prefix)
                session = ReplaySession(data['initial_fen'], data['moves_uci'], claim_draw=True)
                session.last()
                self.assertTrue(session.current_board().is_repetition(3))
                self.assertEqual(session.total_ply(), 8)
                self.assertEqual(data['metadata']['opening_line']['moves_uci'], prefix)
            self.assertEqual(result.candidate_stats.unfinished, 2)
            self.assertTrue(any(s.get('active_games') and next(iter(s['active_games'].values()))['plies'] == 8 for s in states))

    def test_ui_freezes_diverse_lines_for_existing_profiles_and_resume(self):
        from ui.batch_setup import EvaluationFields
        from engine.sessions.experiment_resume import resume_experiment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'configs/evaluation'
            folder.mkdir(parents=True)
            for name, weight in [('stable', 1), ('other', 2)]:
                (folder/f'{name}.json').write_text(json.dumps(EvaluationConfig(pst_weight=weight).to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.candidates = [folder/'other.json']
            fields.values.update(depth='1', max_plies='12')
            fields.action('comparison_openings_generate', None)
            frozen = fields.options()
            lines = frozen['opening_lines']
            self.assertEqual(len(lines), 32)
            self.assertEqual(len({tuple(line['moves_uci']) for line in lines}), 32)
            self.assertTrue(all(0 < len(line['moves_uci']) <= 12 for line in lines))
            self.assertEqual({line['eco'][0] for line in lines}, set('ABCDE'))
            self.assertEqual(frozen['experiment_definition']['planned_games'], 64)
            states = []
            result = run_evaluation_comparison(**frozen, progress=states.append,
                control=lambda: not states or states[-1]['saved_games'] < 1)
            before = {p: p.read_bytes() for p in (result.path/'replays').glob('*.json')}
            self.assertEqual(len(before), 1)
            (folder/'other.json').write_text(json.dumps(EvaluationConfig(pst_weight=99).to_dict()), encoding='utf-8')
            resume_experiment(result.path)
            self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))
            data = json.loads((result.path/'comparison.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['pairs']), 32)
            self.assertEqual(data['progress']['saved_games'], 64)
            for pair, line in zip(data['pairs'], lines):
                self.assertEqual(pair['opening_line'], line)
            resume_experiment(result.path)
            self.assertEqual(len(list((result.path/'replays').glob('*.json'))), 64)

    def test_spawn_search_uses_repetition_history_and_color_pairs(self):
        import multiprocessing
        from engine.sessions.evaluation_comparison import ComparisonSearchConfig
        prefix = ['b1c3', 'g8f6', 'c3b1', 'f6g8', 'b1c3', 'g8f6']
        line = dict(initial_fen='6nk/7q/8/8/8/8/8/KN6 w - - 0 1',
                    moves_uci=prefix, name='可申請三次重複', source={})
        before = {p.pid for p in multiprocessing.active_children()}
        with tempfile.TemporaryDirectory() as directory:
            search = ComparisonSearchConfig(depth_plies=1, search_workers=2, quiescence_depth=0)
            result = run_evaluation_comparison(
                baseline=ComparisonParticipant.alphabeta('基準', EvaluationConfig(pst_enabled=False), search=search),
                candidates=[ComparisonParticipant.alphabeta(label, EvaluationConfig(pst_enabled=False), search=search)
                            for label in ['候選一', '候選二']],
                opening_lines=[line], initial_fens=[line['initial_fen']], claim_draw=True,
                max_plies=8, workers=2, batch_root=Path(directory)/'batches')
            self.assertEqual([stats.draws for stats in result.candidate_results], [2, 2])
            data = json.loads((result.path/'comparison.json').read_text(encoding='utf-8'))
            self.assertEqual([p['opening_line'] for p in data['pairs']], [line, line])
            self.assertTrue(all({g['candidate_color'] for g in p['games']} == {'white', 'black'} for p in data['pairs']))
            for path in (result.path/'replays').glob('*.json'):
                replay = load_replay_json(str(path))
                self.assertEqual(replay['moves_uci'], prefix + ['c3b1'])
                self.assertEqual(replay['metadata']['termination'], 'threefold_repetition')
        self.assertTrue({p.pid for p in multiprocessing.active_children()} <= before)

    def test_special_moves_survive_saved_comparison_and_replay(self):
        prefixes = [
            ['e2e4', 'a7a6', 'e4e5', 'd7d5', 'e5d6'],
            ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1c4', 'g8f6', 'e1g1'],
        ]
        with tempfile.TemporaryDirectory() as directory:
            lines = [dict(initial_fen=chess.STARTING_FEN, moves_uci=moves, source={}, name=str(i))
                     for i, moves in enumerate(prefixes)]
            result = run_evaluation_comparison(
                baseline=ComparisonParticipant.greedy('基準', EvaluationConfig()),
                candidate=ComparisonParticipant.greedy('候選', EvaluationConfig()),
                opening_lines=lines, max_plies=8, batch_root=Path(directory)/'batches')
            for path in (result.path/'replays').glob('*.json'):
                replay = load_replay_json(str(path))
                prefix = replay['metadata']['opening_line']['moves_uci']
                self.assertEqual(replay['moves_uci'][:len(prefix)], prefix)
                session = ReplaySession(replay['initial_fen'], replay['moves_uci'])
                session.goto_ply(len(prefix))
                board = session.current_board()
                if len(prefix) == 5:
                    self.assertIsNone(board.piece_at(chess.D5))
                    self.assertEqual(board.piece_at(chess.D6), chess.Piece(chess.PAWN, chess.WHITE))
                else:
                    self.assertEqual(board.king(chess.WHITE), chess.G1)
                    self.assertEqual(board.piece_at(chess.F1), chess.Piece(chess.ROOK, chess.WHITE))
                    self.assertFalse(board.has_kingside_castling_rights(chess.WHITE))

    def test_invalid_and_terminal_lines_fail_before_creating_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'batches'
            for prefix, claim in [(['e2e5'], False),
                                  (['f2f3', 'e7e5', 'g2g4', 'd8h4'], False),
                                  (['g1f3', 'g8f6', 'f3g1', 'f6g8']*2, True)]:
                with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                    run_evaluation_comparison(
                        baseline=ComparisonParticipant.greedy('基準', EvaluationConfig()),
                        candidate=ComparisonParticipant.greedy('候選', EvaluationConfig()),
                        opening_lines=[dict(initial_fen=chess.STARTING_FEN, moves_uci=prefix)],
                        claim_draw=claim, batch_root=root)
                self.assertFalse(root.exists())

    def test_spawn_stop_cleans_up_games_with_opening_history(self):
        import multiprocessing
        from engine.sessions.evaluation_comparison import ComparisonSearchConfig
        before = {p.pid for p in multiprocessing.active_children()}
        prefix = ['e2e4', 'e7e5']
        states = []
        with tempfile.TemporaryDirectory() as directory:
            search = ComparisonSearchConfig(depth_plies=8)
            result = run_evaluation_comparison(
                baseline=ComparisonParticipant.alphabeta('基準', EvaluationConfig(), search=search),
                candidate=ComparisonParticipant.alphabeta('候選', EvaluationConfig(), search=search),
                opening_lines=[dict(initial_fen=chess.STARTING_FEN, moves_uci=prefix)],
                repetitions=2, workers=2, batch_root=Path(directory)/'batches', progress=states.append,
                control=lambda: not any(s.get('active_games') for s in states))
            self.assertEqual(json.loads((result.path/'manifest.json').read_text(encoding='utf-8'))['status'], 'stopped')
            self.assertEqual(states[-1]['active_games'], {})
            for path in (result.path/'replays').glob('*.json'):
                self.assertEqual(load_replay_json(str(path))['moves_uci'][:2], prefix)
        self.assertTrue({p.pid for p in multiprocessing.active_children()} <= before)

    def test_prefix_deduplication_short_lines_and_insufficient_source(self):
        from types import SimpleNamespace
        from engine.opening_lines import common_opening_lines
        book = SimpleNamespace(source={'fixture': '合法短線'}, lines=[
            dict(eco='A00', name='相同前綴一', moves_uci=['e2e4', 'e7e5', 'g1f3']),
            dict(eco='A01', name='相同前綴二', moves_uci=['e2e4', 'e7e5', 'f1c4']),
            dict(eco='B00', name='短線', moves_uci=['d2d4']),
        ])
        lines = common_opening_lines(book, count=2, max_plies=2)
        self.assertEqual([line['moves_uci'] for line in lines], [['e2e4', 'e7e5'], ['d2d4']])
        with self.assertRaisesRegex(ValueError, '需要 3 條，僅有 2 條'):
            common_opening_lines(book, count=3, max_plies=2)

    def test_work_identity_distinguishes_same_fen_with_different_history(self):
        from engine.sessions.experiment import freeze_comparison, work_id
        from engine.sessions.evaluation_comparison import ComparisonSearchConfig
        prefix = ['g1f3', 'g8f6', 'f3g1', 'f6g8']
        options = dict(baseline=ComparisonParticipant.alphabeta('基準', EvaluationConfig(), search=ComparisonSearchConfig(depth_plies=1)),
                       candidates=[ComparisonParticipant.alphabeta('候選', EvaluationConfig(pst_weight=2), search=ComparisonSearchConfig(depth_plies=1))],
                       initial_fens=[chess.STARTING_FEN], repetitions=1, base_seed=0, max_plies=4,
                       claim_draw=False, name=None, tags=[])
        a = freeze_comparison(dict(options, opening_lines=[dict(initial_fen=chess.STARTING_FEN, moves_uci=prefix)])).to_dict()
        b = freeze_comparison(dict(options, opening_lines=[dict(initial_fen=chess.STARTING_FEN, moves_uci=[])])).to_dict()
        self.assertNotEqual(work_id(a, 0, 1, True), work_id(b, 0, 1, True))

    def test_equal_configs_in_different_files_keep_distinct_resume_work(self):
        from engine.sessions.experiment_resume import resume_experiment
        from engine.replay.comparison_catalog import load_comparison
        from ui.batch_setup import EvaluationFields
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'configs/evaluation'
            folder.mkdir(parents=True)
            for name in ['stable', 'candidate-a', 'candidate-b']:
                (folder/f'{name}.json').write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
            fields = EvaluationFields(root)
            fields.candidates = [folder/'candidate-a.json', folder/'candidate-b.json']
            fields.opening_lines = [dict(initial_fen=chess.STARTING_FEN, moves_uci=['e2e4'], source={}, name='短線')]
            fields.values.update(depth='1', max_plies='1')
            result = run_evaluation_comparison(**fields.options())
            resume_experiment(result.path)
            summary = load_comparison(result.path/'manifest.json')
            self.assertEqual(len(summary.games), 4)
            self.assertEqual(len({json.loads(path.read_text(encoding='utf-8'))['metadata']['execution']['work_id']
                                  for path in (result.path/'replays').glob('*.json')}), 4)
