"""串流棋譜抽樣、整盤分組及不可變局面快照。"""

import bz2
import gzip
import hashlib
import heapq
import io
import json
import sqlite3
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from urllib.request import urlopen
from uuid import uuid4

import chess
import chess.pgn

from engine.evaluation.pst import middlegame_phase
from engine.storage.batch_storage import write_json_atomic as _write

SOURCE_URL = 'https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst'
SOURCE_PAGE = 'https://database.lichess.org/'
SOURCE_SHA256 = 'aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635'
PROCESSING_VERSION = 1
SPLITS = ('train', 'validation', 'test')


class DatasetStopped(Exception):
    pass


def _check(stop):
    if stop is not None and stop.is_set():
        raise DatasetStopped('使用者停止；資料未完成，請建立新實驗重試')


def position_identity(board):
    """資料去重不使用回合數；僅保留確實合法的吃過路兵權。"""
    return ' '.join(board.fen(en_passant='legal').split()[:4])


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _stage(board):
    phase = middlegame_phase(board)
    return 'opening' if phase >= .8 else 'middlegame' if phase > .25 else 'endgame'


def _validate_zstd(path, stop):
    # stream_reader 允許截短串流；另查每個 frame 的 eof，避免部分棋譜冒充完整來源。
    try:
        import zstandard
    except ImportError as exc:
        raise ValueError('讀取 .zst 需要安裝 zstandard；請依 README 安裝') from exc
    decoder = zstandard.ZstdDecompressor().decompressobj()
    with path.open('rb') as stream:
        while chunk := stream.read(64 * 1024):
            _check(stop)
            if decoder.eof:
                decoder = zstandard.ZstdDecompressor().decompressobj()
            decoder.decompress(chunk)
            while decoder.unused_data:
                rest = decoder.unused_data
                decoder = zstandard.ZstdDecompressor().decompressobj()
                decoder.decompress(rest)
    if not decoder.eof:
        raise ValueError('Zstandard 來源截短或不完整')


def _acquire(source, path, stop, progress):
    remote = str(source) == SOURCE_URL
    suffix = '.pgn.zst' if remote else ''.join(Path(source).suffixes)
    destination = path / ('source' + suffix)
    sha = hashlib.sha256()
    size = 0
    with (urlopen(SOURCE_URL, timeout=15) if remote else Path(source).open('rb')) as stream:
        headers = dict(stream.headers.items()) if remote else {}
        expected = int(headers.get('Content-Length', 0)) if remote else 0
        with destination.open('wb') as out:
            while True:
                _check(stop)
                chunk = stream.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                sha.update(chunk)
                out.write(chunk)
                progress(dict(stage='acquiring', bytes=size))
        if expected and size != expected:
            raise ValueError('來源下載不完整')
    if destination.name.endswith('.zst'):
        _validate_zstd(destination, stop)
    verified = sha.hexdigest() == SOURCE_SHA256
    return destination, dict(
        name='Lichess 2013-01 標準棋' if remote or verified else Path(source).name,
        acquisition='https' if remote else 'local-copy',
        location=str(source), sha256=sha.hexdigest(), bytes=size,
        source_page=SOURCE_PAGE if remote or verified else None,
        source_url=SOURCE_URL if remote or verified else None,
        license='CC0-1.0' if remote or verified else '未確認（使用者提供）',
        version='2013-01' if remote or verified else 'local',
        official_sha256_verified=verified,
        http_last_modified=headers.get('Last-Modified'), etag=headers.get('ETag'))


def _select_games(source, path, seed, stop, progress):
    selected = []
    stats = Counter()
    with ExitStack() as stack:
        db = stack.enter_context(closing(sqlite3.connect(path / 'seen.sqlite3')))
        db.execute('CREATE TABLE seen (id TEXT PRIMARY KEY)')
        raw = stack.enter_context(source.open('rb'))
        if source.name.endswith('.zst'):
            try:
                import zstandard
            except ImportError as exc:
                raise ValueError('讀取 .zst 需要安裝 zstandard；請依 README 安裝') from exc
            raw = stack.enter_context(zstandard.ZstdDecompressor().stream_reader(raw))
        elif source.name.endswith('.gz'):
            raw = stack.enter_context(gzip.GzipFile(fileobj=raw))
        elif source.name.endswith('.bz2'):
            raw = stack.enter_context(bz2.BZ2File(raw))
        stream = stack.enter_context(io.TextIOWrapper(raw, encoding='utf-8-sig', errors='strict'))
        while True:
            _check(stop)
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            stats['source_games'] += 1
            if stats['source_games'] % 100 == 0:
                db.commit()
                progress(dict(stage='reading', **stats))
            if game.errors:
                raise ValueError(f'第 {stats["source_games"]} 盤棋譜損壞：{game.errors[0]}')
            if game.headers.get('Variant', 'Standard') not in ('Standard', 'Chess'):
                stats['nonstandard_games'] += 1
                continue
            board = game.board()
            if not board.is_valid() or board.chess960:
                raise ValueError('起始局面不是合法標準棋')
            initial = board.fen()
            moves = []
            for move in game.mainline_moves():
                _check(stop)
                if move not in board.legal_moves:
                    raise ValueError('棋譜含非法走法')
                moves.append(move.uci())
                board.push(move)
            if not moves:
                raise ValueError('棋譜沒有可讀取的合法走法')
            identity = _digest(position_identity(chess.Board(initial)) + ' ' + ' '.join(moves))
            inserted = db.execute('INSERT OR IGNORE INTO seen VALUES (?)', (identity,)).rowcount
            if not inserted:
                stats['duplicate_games'] += 1
                continue
            stats['unique_games'] += 1
            rank = int(_digest(f'{seed}:select:{identity}'), 16)
            record = dict(game_id=identity, initial_fen=initial, moves_uci=moves,
                          source_game=stats['source_games'], headers=dict(game.headers))
            item = (-rank, identity, record)
            if len(selected) < 500:
                heapq.heappush(selected, item)
            elif rank < -selected[0][0]:
                heapq.heapreplace(selected, item)
        db.commit()
    if not stats['source_games']:
        raise ValueError('來源不含 PGN 棋譜')
    (path / 'seen.sqlite3').unlink()
    records = [item[2] for item in selected]
    records.sort(key=lambda game: _digest(f'{seed}:split:{game["game_id"]}'))
    return records, stats


def _sample(games, seed, stop):
    counts = Counter()
    samples = []
    n = len(games)
    boundaries = (n * 70 // 100, n * 70 // 100 + n * 15 // 100)
    for index, game in enumerate(games):
        _check(stop)
        split = 'train' if index < boundaries[0] else 'validation' if index < boundaries[1] else 'test'
        game['split'] = split
        board = chess.Board(game['initial_fen'])
        buckets = {stage: [] for stage in ('opening', 'middlegame', 'endgame')}
        for ply, uci in enumerate(game['moves_uci'], 1):
            _check(stop)
            board.push_uci(uci)
            if ply <= 8:
                counts['first_8_plies'] += 1
                continue
            if board.is_game_over(claim_draw=True):
                counts['terminal'] += 1
                continue
            if board.is_check():
                counts['in_check'] += 1
                continue
            stage = _stage(board)
            buckets[stage].append(dict(
                position_id=_digest(position_identity(board)), identity=position_identity(board),
                game_id=game['game_id'], split=split, stage=stage, ply=ply,
                initial_fen=game['initial_fen'], moves_uci=game['moves_uci'][:ply], fen=board.fen()))
        for bucket in buckets.values():
            bucket.sort(key=lambda p: _digest(f'{seed}:sample:{game["game_id"]}:{p["ply"]}'))
        chosen = []
        while len(chosen) < 12 and any(buckets.values()):
            for bucket in buckets.values():
                if bucket and len(chosen) < 12:
                    chosen.append(bucket.pop())
        counts['not_sampled'] += sum(map(len, buckets.values()))
        samples.extend(chosen)
    owners = {}
    for sample in samples:
        owners.setdefault(sample['identity'], set()).add(sample['split'])
    kept = []
    seen = set()
    for sample in samples:
        key = sample['identity']
        if len(owners[key]) > 1:
            counts['cross_split_duplicate'] += 1
        elif key in seen:
            counts['within_split_duplicate'] += 1
        else:
            seen.add(key)
            kept.append(sample)
    return kept, counts


def create_dataset(root, source, *, seed=2026, stop=None, progress=lambda state: None, run_path=None):
    """建立新實驗；失敗或停止不發布 dataset.json，完成後只讀。"""
    path = Path(run_path) if run_path else Path(root) / uuid4().hex
    if (path / 'dataset.json').exists():
        raise ValueError('已完成的資料快照不可覆寫；請建立新實驗')
    path.mkdir(parents=True, exist_ok=run_path is not None)
    started = monotonic()
    status = dict(status='running', stage='acquiring', path=str(path), seed=int(seed))
    def report(update):
        status.update(update, elapsed_seconds=monotonic() - started)
        progress(dict(status))
    try:
        _write(path / 'status.json', status)
        _check(stop)
        report({})
        local, source_info = _acquire(source, path, stop, report)
        report(dict(stage='reading'))
        games, stats = _select_games(local, path, int(seed), stop, report)
        report(dict(stage='sampling', **stats))
        positions, excluded = _sample(games, int(seed), stop)
        summary = dict(stats, duplicate_games=stats['duplicate_games'], selected_games=len(games),
                       shortfall_games=500 - len(games), positions=len(positions),
                       position_limit=6000, excluded=dict(excluded), splits={})
        for split in SPLITS:
            group = [p for p in positions if p['split'] == split]
            summary['splits'][split] = dict(games=sum(g['split'] == split for g in games),
                positions=len(group), stages=dict(Counter(p['stage'] for p in group)))
        payload = dict(format_version=1, processing_version=PROCESSING_VERSION, seed=int(seed),
            rules=dict(game_limit=500, positions_per_game=12, skip_plies=8,
                       split='train=floor(.7*n), validation=floor(.15*n), test=remainder', selection='sha256-lowest',
                       sampling='phase-round-robin-sha256', phase='material-v1 thresholds .8/.25',
                       dedup='legal-ep-fen-first-four', terminal='claim_draw=True'),
            source=source_info, games=games, positions=positions, summary=summary)
        _check(stop)
        _write(path / 'dataset.json', payload)
        report(dict(status='completed', stage='completed', summary=summary))
    except DatasetStopped as exc:
        report(dict(status='stopped', error=str(exc)))
    except Exception as exc:
        report(dict(status='failed', error=str(exc)))
    finally:
        _write(path / 'status.json', status)
    return path


def load_dataset(path):
    path = Path(path)
    payload = json.loads((path / 'dataset.json').read_text(encoding='utf-8'))
    if payload.get('format_version') != 1 or payload.get('processing_version') != PROCESSING_VERSION:
        raise ValueError('不支援的資料處理版本')
    return payload


class DatasetRun:
    """UI 背景工作；每次新建目錄，成功快照與執行狀態分開保存。"""
    def __init__(self, root, source, seed, executor):
        self.path = Path(root) / uuid4().hex
        self.path.mkdir(parents=True)
        self._lock = Lock()
        self._stop = Event()
        self._state = dict(status='queued', stage='acquiring', path=str(self.path), seed=seed)
        _write(self.path / 'status.json', self._state)
        self.future = executor.submit(self._work, root, source, seed)

    def _work(self, root, source, seed):
        try:
            return create_dataset(root, source, seed=seed, stop=self._stop,
                                  progress=self._progress, run_path=self.path)
        except Exception as exc:
            self._progress(dict(status='failed', error=str(exc)))
            return self.path

    def _progress(self, state):
        with self._lock:
            self._state.update(state)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def stop(self):
        self._stop.set()
