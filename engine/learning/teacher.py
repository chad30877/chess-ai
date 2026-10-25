"""固定教師 UCI 邊界、訓練局面先導與不可變預算選擇。"""

from collections import Counter
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

import chess

from engine.learning.dataset import load_dataset
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic

BUDGETS = (50000, 200000)
MAX_SECONDS = 8 * 3600
TEACHER_VERSION = 1
OPTIONS = {'Threads': 1, 'Hash': 16, 'MultiPV': 1, 'Ponder': False,
           'Skill Level': 20, 'UCI_LimitStrength': False, 'SyzygyPath': '', 'SyzygyProbeLimit': 0}
RESET_POLICY = 'ucinewgame-clear-hash-isready-before-each-position-v1'
SCORE_POLICY = 'latest-exact-pv-matches-bestmove-else-final-score-v1'
SOURCE = {'url': 'https://github.com/official-stockfish/Stockfish/releases/tag/sf_19',
          'source_url': 'https://github.com/official-stockfish/Stockfish/archive/refs/tags/sf_19.zip',
          'license': 'GPL-3.0', 'tag': 'sf_19'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class TeacherStopped(Exception):
    pass


def default_teacher_workers():
    return max(1, min(4, getattr(os, 'process_cpu_count', os.cpu_count)() or 1))


def validate_workers(workers):
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError('同時分析局面數必須是正整數')
    return workers


class TeacherWorkFailed(Exception):
    def __init__(self, sample, error, raw_output):
        super().__init__(str(error))
        self.sample, self.raw_output = sample, list(raw_output)


class TeacherPool:
    """每個程序一次只收一個局面；主執行緒逐筆提交，退出時取消所有在途工作。"""
    def __init__(self, executable, workers, *, metadata=None, stop=None, deadline=None,
                 now=monotonic, timeout=30):
        self.executable, self.workers = executable, validate_workers(workers)
        self.expected, self.stop = metadata, stop
        self.options = dict(deadline=deadline, now=now, timeout=timeout)
        self.cancelled = Event()
        self.resources = ExitStack()
        self.teachers = []
        self.executor = None

    def is_set(self):
        return self.cancelled.is_set() or (self.stop is not None and self.stop.is_set())

    def __enter__(self):
        try:
            for _ in range(self.workers):
                teacher = self.resources.enter_context(UciTeacher(self.executable, stop=self, **self.options))
                if self.expected is not None and teacher.metadata != self.expected:
                    raise ValueError('教師執行檔或 UCI 條件與凍結快照不同；請建立新先導及標記實驗')
                self.expected = teacher.metadata
                self.teachers.append(teacher)
            self.executor = ThreadPoolExecutor(max_workers=self.workers)
            return self
        except BaseException:
            self.resources.close()
            raise

    @property
    def metadata(self):
        return self.expected

    def check(self):
        self.teachers[0].check()

    def analyse(self, samples, nodes):
        pending, remaining = {}, iter(samples)

        def submit(teacher):
            self.check()
            sample = next(remaining, None)
            if sample is not None:
                pending[self.executor.submit(teacher.analyse, sample, nodes)] = (teacher, sample)

        for teacher in self.teachers:
            submit(teacher)
        while pending:
            self.check()
            done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
            for future in done:
                teacher, sample = pending.pop(future)
                self.check()
                try:
                    record = future.result()
                except TeacherStopped:
                    raise
                except Exception as exc:
                    raise TeacherWorkFailed(sample, exc, teacher.last_output) from exc
                yield sample, record
                submit(teacher)

    def __exit__(self, *args):
        self.cancelled.set()
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
        self.resources.close()


class UciTeacher:
    """逐行保存教師輸出；讀取可取消，關閉有界且清理子程序。"""
    def __init__(self, executable, *, stop=None, deadline=None, now=monotonic, timeout=30):
        self.command = [str(p) for p in executable] if isinstance(executable, (list, tuple)) else [str(executable)]
        self.stop, self.deadline, self.now, self.timeout = stop, deadline, now, timeout
        self.process = None
        self.lines = Queue()
        self.metadata = None
        self.last_output = []

    def check(self):
        if self.stop is not None and self.stop.is_set():
            raise TeacherStopped('使用者停止')
        if self.deadline is not None and self.now() >= self.deadline:
            raise TeacherStopped('已達八小時上限')

    def send(self, command):
        self.check()
        try:
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            raise ValueError('教師引擎異常終止') from exc

    def receive(self, until):
        started, output = self.now(), []
        self.last_output = output
        while True:
            self.check()
            if self.now() - started >= self.timeout:
                raise ValueError('教師引擎逾時')
            try:
                line = self.lines.get(timeout=.05)
            except Empty:
                continue
            if line is None:
                raise ValueError('教師引擎異常終止')
            output.append(line)
            if 'CRITICAL ERROR' in line:
                raise ValueError('教師拒絕局面：' + line)
            if until(line):
                return output

    def __enter__(self):
        self.check()
        executable = Path(self.command[0])
        try:
            binary_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f'找不到或無法讀取教師執行檔：{executable}') from exc
        # 測試程序附帶腳本時，也固定腳本內容以避免身份混用。
        extra_hashes = {str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                        for p in self.command[1:] if Path(p).is_file()}
        try:
            self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            def read():
                try:
                    for line in self.process.stdout:
                        self.lines.put(line.rstrip('\r\n'))
                finally:
                    self.lines.put(None)
            self.reader = Thread(target=read, daemon=True)
            self.reader.start()
            self.send('uci')
            raw = self.receive(lambda line: line == 'uciok')
            ids = {line.split(' ', 2)[1]: line.split(' ', 2)[2] for line in raw if line.startswith('id ')}
            if ids.get('name') != 'Stockfish 19':
                raise ValueError('教師版本不合：需要 Stockfish 19，收到 ' + ids.get('name', '未知'))
            offered = [line for line in raw if line.startswith('option name ')]
            names = {line.split(' type ', 1)[0][12:] for line in offered}
            applied = {k: v for k, v in OPTIONS.items() if k in names}
            if not {'Threads', 'Hash', 'SyzygyPath', 'SyzygyProbeLimit'} <= names:
                raise ValueError('教師缺少必要 UCI 選項')
            for name, value in applied.items():
                self.send(f'setoption name {name} value {str(value).lower() if isinstance(value, bool) else value}')
            self.send('isready')
            self.receive(lambda line: line == 'readyok')
            self.metadata = dict(processing_version=TEACHER_VERSION, command=self.command, executable_sha256=binary_hash,
                extra_sha256=extra_hashes, identification=ids, options=applied, offered_options=offered,
                reset_policy=RESET_POLICY, score_policy=SCORE_POLICY, source=SOURCE, raw_identification=raw)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=.5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=2)
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()
            if hasattr(self, 'reader'):
                self.reader.join(timeout=.5)

    def __exit__(self, *args):
        self.close()

    def analyse(self, sample, nodes):
        board = chess.Board(sample['initial_fen'])
        if not board.is_valid():
            raise ValueError('教師起始局面無效')
        for move in sample['moves_uci']:
            board.push_uci(move)
        if board.fen() != sample['fen']:
            raise ValueError('教師局面與完整歷史不一致')
        self.send('ucinewgame')
        self.send('setoption name Clear Hash')
        self.send('isready')
        self.receive(lambda line: line == 'readyok')
        position = 'startpos' if sample['initial_fen'] == chess.STARTING_FEN else 'fen ' + sample['initial_fen']
        self.send('position ' + position + (' moves ' + ' '.join(sample['moves_uci']) if sample['moves_uci'] else ''))
        started = self.now()
        self.send(f'go nodes {nodes}')
        raw = self.receive(lambda line: line.startswith('bestmove '))
        elapsed = self.now() - started
        try:
            best = board.parse_uci(raw[-1].split()[1])
            if best not in board.legal_moves:
                raise ValueError('最佳手不是合法走法')
        except (ValueError, IndexError) as exc:
            raise ValueError('教師回傳非法最佳手：' + raw[-1]) from exc
        scores = [line for line in raw if line.startswith('info ') and ' score ' in line]
        if not scores:
            raise ValueError('教師沒有可解釋的分數')
        for line in scores:
            parts = line.split()
            index = parts.index('score')
            try:
                if parts[index + 1] not in ('cp', 'mate'): raise ValueError()
                int(parts[index + 2])
            except (ValueError, IndexError) as exc:
                raise ValueError('無法解釋教師分數：' + line) from exc
        # 節點到期可留下新深度的界限；只回退到同一最佳手最近的完整評分。
        exact = [line for line in scores if 'lowerbound' not in line.split() and 'upperbound' not in line.split()
                 and ' pv ' in line and line.split(' pv ', 1)[1].split()[0] == best.uci()]
        selected = exact[-1] if exact else scores[-1]
        fields = selected.split()
        index = fields.index('score')
        try:
            kind, score = fields[index + 1], int(fields[index + 2])
            if kind not in ('cp', 'mate'):
                raise ValueError()
        except (ValueError, IndexError) as exc:
            raise ValueError('無法解釋教師分數：' + selected) from exc
        actual_nodes = next((int(line.split(' nodes ')[1].split()[0]) for line in reversed(raw) if ' nodes ' in line), None)
        if actual_nodes is None:
            raise ValueError('教師未回報實際節點數')
        lower, upper = 'lowerbound' in fields, 'upperbound' in fields
        reasons = []
        if board.is_game_over(claim_draw=True): reasons.append('terminal')
        if board.is_check(): reasons.append('in_check')
        if kind == 'mate': reasons.append('mate')
        if board.is_capture(best): reasons.append('capture')
        if best.promotion: reasons.append('promotion')
        if lower or upper: reasons.append('bound_only')
        # Stockfish 保留的巨大 cp 為 TB/特殊分數，不轉為一般標記。
        if kind == 'cp' and abs(score) >= 20000: reasons.append('tablebase_score')
        if any(' tbhits ' in line and int(line.split(' tbhits ')[1].split()[0]) > 0 for line in raw):
            reasons.append('tablebase_hit')
        return dict(sample_id=sample.get('id', sample.get('position_id')), game_id=sample['game_id'], split=sample['split'],
            stage=sample['stage'], initial_fen=sample['initial_fen'], moves_uci=sample['moves_uci'], fen=sample['fen'],
            requested_nodes=nodes, actual_nodes=actual_nodes, elapsed_seconds=elapsed, raw_output=raw,
            selected_score_line=selected, final_score_line=scores[-1], score_policy=SCORE_POLICY,
            score_depth=int(fields[fields.index('depth') + 1]) if 'depth' in fields else None,
            score_nodes=int(fields[fields.index('nodes') + 1]) if 'nodes' in fields else None,
            raw_score=dict(kind=kind, value=score, pov='white' if board.turn else 'black', lowerbound=lower, upperbound=upper),
            white_cp=(score if board.turn else -score) if kind == 'cp' else None,
            bestmove=best.uci(), exclusion_reasons=reasons, valid=not reasons)


def _summary(snapshot, records):
    indexed = {(r['sample_id'], r['requested_nodes']): r for r in records}
    differences = []
    for sample in snapshot['samples']:
        pair = [indexed.get((sample['id'], n)) for n in BUDGETS]
        if all(r and r['valid'] for r in pair):
            differences.append(abs(pair[0]['white_cp'] - pair[1]['white_cp']))
    return dict(completed=len(records), total=2 * snapshot['sample_count'], compared=len(differences),
        not_comparable=snapshot['sample_count'] - len(differences),
        mean_absolute_difference_cp=sum(differences) / len(differences) if differences else None,
        max_absolute_difference_cp=max(differences) if differences else None,
        budgets={str(n): dict(completed=sum(r['requested_nodes'] == n for r in records),
            elapsed_seconds=sum(r['elapsed_seconds'] for r in records if r['requested_nodes'] == n),
            excluded=sum(not r['valid'] for r in records if r['requested_nodes'] == n),
            reasons=dict(Counter(reason for r in records if r['requested_nodes'] == n for reason in r['exclusion_reasons']))) for n in BUDGETS})


def run_pilot(dataset_path, executable, *, workers=1, stop=None, progress=lambda state: None, now=monotonic, timeout=30, run_path=None):
    """新建先導；只從訓練來源固定選最多100局面，成功紀錄逐筆提交。"""
    workers = validate_workers(workers)
    dataset_path = Path(dataset_path)
    data = load_dataset(dataset_path)
    path = Path(run_path) if run_path else dataset_path / 'teacher-pilots' / uuid4().hex
    if (path / 'snapshot.json').exists():
        raise ValueError('先導條件不可變；請建立新先導')
    path.mkdir(parents=True, exist_ok=run_path is not None)
    started = now()
    state = dict(status='running', path=str(path), completed=0, total=0, elapsed_seconds=0, error='', budget_measurements={})
    records = []
    def report(**update):
        state.update(update, elapsed_seconds=now() - started)
        progress(dict(state))
        write_json_atomic(path / 'status.json', state)
    try:
        with experiment_lock(path):
            report()
            samples = sorted((deepcopy(p) for p in data['positions'] if p['split'] == 'train'),
                             key=lambda p: digest([data['seed'], 'pilot-v1', p['position_id']]))[:100]
            if not samples:
                raise ValueError('訓練組沒有可用局面')
            for sample in samples: sample['id'] = sample['position_id']
            state['total'] = 2 * len(samples)
            with TeacherPool(executable, min(workers, len(samples)), stop=stop,
                             deadline=started + MAX_SECONDS, now=now, timeout=timeout) as teacher:
                snapshot = dict(format_version=1, processing_version=TEACHER_VERSION,
                    dataset_sha256=digest(data), dataset_path=str(dataset_path.resolve()), dataset_source=data['source'],
                    teacher=teacher.metadata, workers=workers, sample_count=len(samples), samples=samples, budgets=list(BUDGETS),
                    selection='train-only-sha256-seed-pilot-v1-lowest-100', max_seconds=MAX_SECONDS,
                    filter_version=1, cp_special_threshold=20000)
                write_json_atomic(path / 'snapshot.json', snapshot)
                (path / 'records').mkdir()
                for nodes in BUDGETS:
                    measured_start = now()
                    measurement = dict(completed=0, elapsed_seconds=0, workers=workers)
                    state['budget_measurements'][str(nodes)] = measurement
                    try:
                        for sample, record in teacher.analyse(samples, nodes):
                            teacher.check()
                            write_json_atomic(path / 'records' / f'{sample["id"]}-{nodes}.json', record)
                            records.append(record)
                            measurement.update(completed=measurement['completed'] + 1,
                                               elapsed_seconds=now() - measured_start)
                            report(completed=len(records), summary=_summary(snapshot, records),
                                   last_score=dict(white_cp=record['white_cp'], depth=record['score_depth'],
                                                   actual_nodes=record['actual_nodes'], kind=record['raw_score']['kind']))
                    finally:
                        measurement['elapsed_seconds'] = now() - measured_start
                report(status='completed')
    except TeacherStopped as exc:
        report(status='stopped', error=str(exc))
    except Exception as exc:
        report(status='failed', error=str(exc))
    return path


def load_pilot(path):
    path = Path(path)
    state = json.loads((path / 'status.json').read_text(encoding='utf-8'))
    state['snapshot'] = json.loads((path / 'snapshot.json').read_text(encoding='utf-8')) if (path / 'snapshot.json').exists() else None
    if state['snapshot'] and (state['snapshot'].get('format_version') != 1 or
                              state['snapshot'].get('processing_version') != TEACHER_VERSION):
        raise ValueError('不支援的教師處理版本')
    state['records'] = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((path / 'records').glob('*.json'))]
    if state['snapshot']:
        state['summary'] = _summary(state['snapshot'], state['records'])
        state['completed'] = len(state['records'])
    state['choice'] = json.loads((path / 'choice.json').read_text(encoding='utf-8')) if (path / 'choice.json').exists() else None
    return state


def choose_budget(path, nodes):
    """量測完成後凍結選擇；重開不重跑先導或偷偷替換預算。"""
    path = Path(path)
    with experiment_lock(path):
        pilot = load_pilot(path)
        if pilot['status'] != 'completed' or pilot['completed'] != pilot['total']:
            raise ValueError('先導未完成，無法選定預算')
        if nodes not in BUDGETS:
            raise ValueError('請選擇已量測的節點預算')
        if pilot['choice']:
            if pilot['choice']['nodes'] != nodes:
                raise ValueError('教師條件不可變；請建立新先導')
            return pilot['choice']
        snapshot = pilot['snapshot']
        choice = dict(format_version=1, nodes=nodes, dataset_sha256=snapshot['dataset_sha256'],
            teacher=deepcopy(snapshot['teacher']), filter_version=snapshot['filter_version'],
            cp_special_threshold=snapshot['cp_special_threshold'], pilot_snapshot_sha256=digest(snapshot))
        if 'workers' in snapshot:
            choice['workers'] = snapshot['workers']
        choice['identity'] = digest(choice)
        write_json_atomic(path / 'choice.json', choice)
        return choice


class PilotRun:
    """可停止的 UI 背景先導；狀態與成功標記分開保存。"""
    def __init__(self, dataset_path, executable, executor, **options):
        self.path = Path(dataset_path) / 'teacher-pilots' / uuid4().hex
        self.path.mkdir(parents=True)
        self._stop, self._lock = Event(), Lock()
        self._state = dict(status='queued', path=str(self.path), completed=0, total=0, elapsed_seconds=0)
        write_json_atomic(self.path / 'status.json', self._state)
        self.future = executor.submit(self._work, dataset_path, executable, options)

    def _work(self, dataset_path, executable, options):
        try:
            return run_pilot(dataset_path, executable, stop=self._stop,
                             progress=self._progress, run_path=self.path, **options)
        except Exception as exc:
            self._progress(dict(status='failed', error=f'先導保存失敗：{exc}'))
            return self.path

    def _progress(self, state):
        with self._lock: self._state.update(state)

    def snapshot(self):
        with self._lock: return dict(self._state)

    def stop(self):
        self._stop.set()
