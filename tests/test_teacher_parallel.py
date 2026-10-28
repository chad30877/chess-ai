"""從公開教師入口觀察外部程序重疊、條件凍結與保存結果。"""
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from engine.learning.dataset import create_dataset
from engine.learning.teacher import run_pilot, load_pilot, choose_budget
from engine.storage.batch_storage import write_json_atomic
from engine.learning.labeling import create_labeling, run_labeling, load_labeling, load_labeled_dataset
from tests.helpers.uci_teacher import make_engine
from tests.test_learning_dataset import pgn_games


def observed_engine(root):
    command = make_engine(root)
    script = Path(command[1])
    code = script.read_text(encoding='utf-8')
    code = code.replace('import sys', '''import sys, os, json, time
from pathlib import Path
log = Path(__file__).with_name(str(os.getpid()) + '.trace')
def trace(event, **fields):
 with log.open('a', encoding='utf-8') as stream:
  stream.write(json.dumps(dict(event=event, pid=os.getpid(), time=time.perf_counter(), **fields)) + '\\n')
trace('process')''', 1)
    code = code.replace(" line=line.strip()", " line=line.strip()\n trace('command', command=line)")
    code = code.replace('  import chess', '''  nodes=int(line.split()[-1])
  trace('start', moves=moves, nodes=nodes)
  control=Path(__file__).with_name('control')
  mode=control.read_text() if control.exists() else ''
  if mode=='crash': raise RuntimeError('teacher crash')
  time.sleep(60 if mode=='hang' else .01 + .005*(len(moves)%4))
  import chess''')
    code = code.replace("print('info depth 2 score cp 25 nodes '+line.split()[-1]", "print('info depth 2 score cp '+str(len(moves))+' nodes '+line.split()[-1]")
    code = code.replace("  print('bestmove '+best, flush=True)", "  trace('end', moves=moves, nodes=nodes)\n  print('bestmove '+best, flush=True)")
    script.write_text(code, encoding='utf-8')
    return command


class ParallelTeacherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'source.pgn'
        source.write_text(pgn_games(8), encoding='utf-8')
        self.dataset = create_dataset(self.root / 'data', source)
        self.command = observed_engine(self.root)

    def events(self):
        return sorted((json.loads(line) for path in self.root.glob('*.trace')
                       for line in path.read_text(encoding='utf-8').splitlines()), key=lambda item: item['time'])

    def test_parallel_pilot_keeps_histories_and_separate_budget_measurements(self):
        pilot = load_pilot(run_pilot(self.dataset, self.command, workers=3))
        self.assertEqual(pilot['status'], 'completed', pilot.get('error'))
        self.assertEqual(pilot['snapshot']['workers'], 3)
        active, maximum = set(), 0
        starts, ends = [], []
        for event in self.events():
            if event['event'] == 'start':
                active.add(event['pid'])
                maximum = max(maximum, len(active))
                starts.append((event['nodes'], event['moves']))
            elif event['event'] == 'end':
                active.remove(event['pid'])
                ends.append((event['nodes'], event['moves']))
        self.assertEqual(maximum, 3)
        self.assertFalse(active)
        self.assertNotEqual(starts, ends)
        for record in pilot['records']:
            self.assertEqual(record['raw_score']['value'], len(record['moves_uci']))
        events = self.events()
        last_low = max(e['time'] for e in events if e['event'] == 'end' and e['nodes'] == 50000)
        first_high = min(e['time'] for e in events if e['event'] == 'start' and e['nodes'] == 200000)
        self.assertGreater(first_high, last_low)
        for nodes in ('50000', '200000'):
            measurement = pilot['budget_measurements'][nodes]
            self.assertEqual(measurement['completed'], pilot['snapshot']['sample_count'])
            self.assertGreater(measurement['elapsed_seconds'], 0)
        choice = choose_budget(pilot['path'], 50000)
        self.assertEqual(choice['workers'], 3)
        commands = [e['command'] for e in events if e['event'] == 'command']
        self.assertEqual(commands.count('setoption name Threads value 1'), 3)

    def test_parallel_labels_stop_retry_and_deadline_keep_commits_and_release_processes(self):
        import psutil
        pilot = run_pilot(self.dataset, self.command, workers=3)
        choose_budget(pilot, 50000)
        path = create_labeling(self.dataset, pilot)
        saved = load_labeling(path)
        self.assertEqual(saved['snapshot']['workers'], 3)
        initial = saved['completed']
        stop = Event()
        def cancel(state):
            if state['completed'] > initial: stop.set()
        run_labeling(path, stop=stop, progress=cancel)
        saved = load_labeling(path)
        self.assertEqual(saved['status'], 'stopped')
        self.assertGreater(saved['completed'], initial)
        self.assertGreater(saved['remaining'], 0)
        committed = {p.name: p.read_bytes() for p in (path / 'records').glob('*.json')}
        self.assertTrue(all(not psutil.pid_exists(e['pid']) for e in self.events()))
        (self.root / 'control').write_text('crash')
        run_labeling(path)
        failed = load_labeling(path)
        self.assertEqual(failed['status'], 'failed')
        self.assertGreater(failed['failed'], 0)
        with self.assertRaisesRegex(ValueError, '未完成'):
            load_labeled_dataset(path)
        (self.root / 'control').unlink()
        clock = [0.0]
        before = failed['completed']
        def expire(state):
            if state['completed'] > before: clock[0] = 28800
        run_labeling(path, now=lambda: clock[0], progress=expire)
        expired = load_labeling(path)
        self.assertEqual(expired['status'], 'stopped')
        self.assertIn('八小時', expired['error'])
        self.assertTrue(all(not psutil.pid_exists(e['pid']) for e in self.events()))
        run_labeling(path)
        saved = load_labeling(path)
        self.assertTrue(saved['ready'])
        self.assertEqual(saved['failed'], 0)
        for name, content in committed.items():
            self.assertEqual((path / 'records' / name).read_bytes(), content)

    def test_old_pilot_and_labels_keep_original_identity_and_single_process(self):
        pilot_path = run_pilot(self.dataset, self.command)
        snapshot_path = pilot_path / 'snapshot.json'
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
        snapshot.pop('workers')
        write_json_atomic(snapshot_path, snapshot)
        choose_budget(pilot_path, 50000)
        original = snapshot_path.read_bytes()
        choice = (pilot_path / 'choice.json').read_bytes()
        path = create_labeling(self.dataset, pilot_path)
        self.assertNotIn('workers', load_labeling(path)['snapshot'])
        label_snapshot = (path / 'snapshot.json').read_bytes()
        pids_before = {e['pid'] for e in self.events()}
        run_labeling(path)
        self.assertTrue(load_labeling(path)['ready'])
        self.assertEqual(len({e['pid'] for e in self.events()} - pids_before), 1)
        self.assertEqual(snapshot_path.read_bytes(), original)
        self.assertEqual((pilot_path / 'choice.json').read_bytes(), choice)
        self.assertEqual((path / 'snapshot.json').read_bytes(), label_snapshot)

    def test_budget_wall_time_uses_shared_clock_and_survives_reopen(self):
        clock = [100.0]
        seen = [0]
        def completed(state):
            if state['completed'] > seen[0]:
                clock[0] += 2
                seen[0] = state['completed']
        pilot = load_pilot(run_pilot(self.dataset, self.command, workers=2,
                                    now=lambda: clock[0], progress=completed))
        self.assertEqual(pilot['status'], 'completed')
        for nodes in ('50000', '200000'):
            measurement = pilot['budget_measurements'][nodes]
            self.assertEqual(measurement['elapsed_seconds'], measurement['completed'] * 2)
            self.assertEqual(measurement['workers'], 2)
        self.assertEqual(load_pilot(pilot['path'])['budget_measurements'], pilot['budget_measurements'])

    def test_one_sample_does_not_start_unused_workers(self):
        source = self.root / 'tiny.pgn'
        source.write_text('\n\n'.join('[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. ' + move + ' *'
                                     for move in ('O-O', 'd3')), encoding='utf-8')
        dataset = create_dataset(self.root / 'tiny', source)
        saved = load_pilot(run_pilot(dataset, self.command, workers=5))
        self.assertEqual(saved['status'], 'completed', saved.get('error'))
        self.assertEqual(saved['snapshot']['sample_count'], 1)
        self.assertEqual(saved['snapshot']['workers'], 5)
        self.assertEqual(len({event['pid'] for event in self.events()}), 1)
