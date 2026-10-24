"""透過資料建立、保存與重開入口驗證分組及局面契約。"""

import io
import json
import gzip
from threading import Event
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

import chess
import chess.pgn

from engine.learning.dataset import SOURCE_URL, create_dataset, load_dataset


def pgn_games(count=12):
    games = []
    for index in range(count):
        board = chess.Board()
        game = chess.pgn.Game()
        game.headers['Site'] = f'fixture:{index}'
        node = game
        import random
        rng = random.Random(index)
        for _ in range(30):
            if board.is_game_over():
                break
            move = rng.choice(list(board.legal_moves))
            node = node.add_variation(move)
            board.push(move)
        games.append(str(game))
    return '\n\n'.join(games) + '\n\n'


class DatasetTest(unittest.TestCase):
    def test_repeated_positions_within_one_group_do_not_multiply_samples(self):
        moves = '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Kh1 Ng8 7. Kg1 Nf6 8. Kh1 Ng8 *'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'repeat.pgn'
            source.write_text('[Event "repeat"]\n\n' + moves, encoding='utf-8')
            data = load_dataset(create_dataset(root / 'runs', source))
            self.assertEqual(len({p['identity'] for p in data['positions']}), len(data['positions']))
            self.assertGreater(data['summary']['excluded']['within_split_duplicate'], 0)

    def test_full_limit_has_exact_whole_game_split_and_disjoint_positions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'enough.pgn'
            source.write_text(pgn_games(501), encoding='utf-8')
            data = load_dataset(create_dataset(root / 'runs', source, seed=77))
            self.assertEqual(data['summary']['selected_games'], 500)
            self.assertEqual(data['summary']['shortfall_games'], 0)
            self.assertEqual([data['summary']['splits'][s]['games'] for s in ('train', 'validation', 'test')], [350, 75, 75])
            identities = [{p['identity'] for p in data['positions'] if p['split'] == split} for split in ('train', 'validation', 'test')]
            self.assertFalse(identities[0] & identities[1] or identities[0] & identities[2] or identities[1] & identities[2])

    def test_shared_positions_are_removed_from_every_split(self):
        prefix = '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O '
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'shared.pgn'
            source.write_text('\n\n'.join(f'[Event "{i}"]\n\n{prefix}{move} *' for i, move in enumerate(('Be7', 'b5', 'd6'))), encoding='utf-8')
            saved = load_dataset(create_dataset(root / 'runs', source, seed=5))
            self.assertEqual(saved['summary']['splits']['train']['games'], 2)
            self.assertEqual(saved['summary']['splits']['test']['games'], 1)
            self.assertEqual(saved['summary']['excluded']['cross_split_duplicate'], 3)
            self.assertEqual(len(saved['positions']), 3)
            self.assertTrue(all(p['ply'] == 10 for p in saved['positions']))

    def test_effective_en_passant_is_kept_and_counters_do_not_create_positions(self):
        from engine.learning.dataset import position_identity
        ineffective = chess.Board('4k3/8/8/3p4/8/8/8/4K3 w - d6 0 8')
        same = chess.Board('4k3/8/8/3p4/8/8/8/4K3 w - - 15 40')
        self.assertEqual(position_identity(ineffective), position_identity(same))
        effective = chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 8')
        no_right = chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - - 0 8')
        self.assertNotEqual(position_identity(effective), position_identity(no_right))
        pinned = chess.Board('k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 8')
        self.assertTrue(position_identity(pinned).endswith(' -'))

    def test_saved_samples_distinguish_only_effective_en_passant_across_splits(self):
        first = 'h8h7 a1a2 h7g6 a2a3 g6f5 a3b3 f5g5 b3b4 d7d5'.split()
        second = 'h8h7 a1a2 h7g6 a2a3 d7d5 a3b3 g6f5 b3b4 f5g5'.split()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pawn, expected in (('4P3', 2), ('P7', 0)):
                fen = f'7k/3p4/8/{pawn}/8/8/8/K7 b - - 0 1'
                games = []
                for moves in (first, second):
                    game = chess.pgn.Game()
                    board = chess.Board(fen)
                    game.setup(board)
                    node = game
                    for uci in moves:
                        move = board.parse_uci(uci)
                        node = node.add_variation(move)
                        board.push(move)
                    games.append(str(game))
                source = root / f'{pawn}.pgn'
                source.write_text('\n\n'.join(games), encoding='utf-8')
                data = load_dataset(create_dataset(root / 'runs', source))
                self.assertEqual(len(data['positions']), expected)
                if expected:
                    self.assertEqual({p['identity'].split()[-1] for p in data['positions']}, {'d6', '-'})
                else:
                    self.assertEqual(data['summary']['excluded']['cross_split_duplicate'], 2)

    def test_local_compressed_and_downloaded_sources_record_actual_hash_and_origin(self):
        import hashlib
        content = gzip.compress(pgn_games(3).encode('utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / 'source.pgn.gz'
            local.write_bytes(content)
            saved = load_dataset(create_dataset(root / 'runs', local))
            self.assertEqual(saved['source']['sha256'], hashlib.sha256(content).hexdigest())
            self.assertEqual(saved['source']['acquisition'], 'local-copy')
            # 真正的 HTTP 邊界替身；內容為小型 zstd 串流，不下載整份公開資料。
            import zstandard
            compressed = zstandard.ZstdCompressor().compress(pgn_games(3).encode('utf-8'))
            response = io.BytesIO(compressed)
            response.headers = {'Content-Length': str(len(compressed)), 'ETag': 'fixture-version'}
            with patch('engine.learning.dataset.urlopen', return_value=response):
                downloaded = load_dataset(create_dataset(root / 'runs', SOURCE_URL))
            self.assertEqual(downloaded['source']['sha256'], hashlib.sha256(compressed).hexdigest())
            self.assertEqual(downloaded['source']['license'], 'CC0-1.0')
            self.assertEqual(downloaded['source']['etag'], 'fixture-version')
            self.assertEqual(downloaded['positions'], saved['positions'])

    def test_stop_damage_and_save_failure_never_publish_partial_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.pgn'
            source.write_text(pgn_games(), encoding='utf-8')
            completed = create_dataset(root / 'runs', source)
            original = (completed / 'dataset.json').read_bytes()
            with self.assertRaisesRegex(ValueError, '不可覆寫'):
                create_dataset(root / 'runs', source, seed=123, run_path=completed)
            self.assertEqual((completed / 'dataset.json').read_bytes(), original)
            stop = Event()
            def progress(state):
                if state['stage'] == 'reading':
                    stop.set()
            stopped = create_dataset(root / 'runs', source, stop=stop, progress=progress)
            self.assertEqual(json.loads((stopped / 'status.json').read_text(encoding='utf-8'))['status'], 'stopped')
            self.assertFalse((stopped / 'dataset.json').exists())
            source.write_text('[Event "broken"]\n\n1. e4 e5 2. Bh6 *', encoding='utf-8')
            damaged = create_dataset(root / 'runs', source)
            status = json.loads((damaged / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['status'], 'failed')
            self.assertIn('損壞', status['error'])
            self.assertFalse((damaged / 'dataset.json').exists())
            source.write_text(pgn_games(3), encoding='utf-8')
            replace = Path.replace
            def fail_dataset(path, target):
                if Path(target).name == 'dataset.json':
                    raise OSError('磁碟已滿')
                return replace(path, target)
            with patch.object(Path, 'replace', fail_dataset):
                failed = create_dataset(root / 'runs', source)
            self.assertFalse((failed / 'dataset.json').exists())
            self.assertIn('磁碟已滿', json.loads((failed / 'status.json').read_text(encoding='utf-8'))['error'])
            self.assertEqual((completed / 'dataset.json').read_bytes(), original)

    def test_truncated_zstd_is_a_visible_failure_even_with_parseable_games(self):
        import zstandard
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'broken.pgn.zst'
            content = zstandard.ZstdCompressor(write_checksum=True).compress(pgn_games(3).encode('utf-8'))
            source.write_bytes(content[:-4])
            result = create_dataset(root / 'runs', source)
            state = json.loads((result / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'failed')
            self.assertFalse((result / 'dataset.json').exists())

    def test_create_reopen_is_deterministic_and_keeps_game_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'games.pgn'
            source.write_text(pgn_games() + pgn_games(1), encoding='utf-8')
            first = create_dataset(root / 'runs', source, seed=42)
            second = create_dataset(root / 'runs', source, seed=42)
            saved = load_dataset(first)
            again = load_dataset(second)
            self.assertEqual(saved['games'], again['games'])
            self.assertEqual(saved['positions'], again['positions'])
            self.assertEqual(saved['summary']['duplicate_games'], 1)
            self.assertEqual(saved['summary']['selected_games'], 12)
            self.assertEqual(saved['summary']['shortfall_games'], 488)
            self.assertEqual([saved['summary']['splits'][s]['games'] for s in ('train', 'validation', 'test')], [8, 1, 3])
            self.assertEqual(len({g['game_id'] for g in saved['games']}), 12)
            for sample in saved['positions']:
                board = chess.Board(sample['initial_fen'])
                for move in sample['moves_uci']:
                    board.push_uci(move)
                self.assertEqual(board.fen(), sample['fen'])
                self.assertGreater(len(sample['moves_uci']), 8)
                self.assertFalse(board.is_check() or board.is_game_over(claim_draw=True))
                self.assertLessEqual(sum(p['game_id'] == sample['game_id'] for p in saved['positions']), 12)


if __name__ == '__main__':
    unittest.main()
