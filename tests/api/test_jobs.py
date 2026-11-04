"""伺服器工作服務、全機重度工作鎖、SSE 快照與首頁掃描。"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from api.app import create_app, job_events
from engine.sessions.heavy_job import HeavyJobBusy, HeavyJobExecutor, acquire

LOCAL = ('127.0.0.1', 50000)
ROOT = Path(__file__).resolve().parents[2]

HOLDER = """
import sys
from engine.sessions.heavy_job import acquire
hold = acquire(program='pygame 介面', label='教師標記', lock_path=sys.argv[1])
print('held', flush=True)
sys.stdin.read()
hold.release()
"""


def cleanup(temp):
    """Windows 上剛寫入的檔案可能被短暫占用（例如防毒掃描），重試數次再刪除。"""
    for _ in range(20):
        try:
            temp.cleanup()
            return
        except PermissionError:
            time.sleep(0.25)
    temp.cleanup()


def wait_for(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError('等待逾時')


class HeavyJobLockTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lock = Path(self.temp.name) / '.heavy-job.lock'

    def tearDown(self):
        self.temp.cleanup()

    def test_two_processes_only_one_holds_the_lock(self):
        child = subprocess.Popen([sys.executable, '-c', HOLDER, str(self.lock)], cwd=ROOT,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            self.assertEqual(child.stdout.readline().strip(), 'held')
            with self.assertRaises(HeavyJobBusy) as caught:
                acquire(program='網頁介面', label='一般批次', lock_path=self.lock)
            self.assertEqual(caught.exception.owner['program'], 'pygame 介面')
            self.assertIn('教師標記', str(caught.exception))
        finally:
            child.communicate('', timeout=30)
        acquire(program='網頁介面', label='一般批次', lock_path=self.lock).release()

    def test_executor_releases_the_lock_when_work_finishes(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            heavy = HeavyJobExecutor(pool, program='網頁介面', lock_path=self.lock)
            future = heavy.submit(time.sleep, 0.2)
            with self.assertRaises(HeavyJobBusy):
                heavy.submit(time.sleep, 0)
            future.result()
            wait_for(lambda: self._free())

    def _free(self):
        try:
            acquire(program='測試', label='檢查', lock_path=self.lock).release()
            return True
        except HeavyJobBusy:
            return False


class JobServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.app = create_app(self.root / 'static', project_root=self.root,
                              lock_path=self.root / 'data/.heavy-job.lock', scan_on_start=False)
        self.client = TestClient(self.app, client=LOCAL)

    def tearDown(self):
        self.app.state.jobs.shutdown(timeout=60)
        cleanup(self.temp)

    def start_slow_batch(self):
        response = self.client.post('/api/batches/general', json=dict(
            white='Random', black='Random', games=3, max_plies=4, interval=1.0, base_seed=1))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def job(self, job_id):
        return next(item for item in self.client.get('/api/jobs').json() if item['id'] == job_id)

    def test_second_heavy_job_is_rejected_with_owner(self):
        first = self.start_slow_batch()
        response = self.client.post('/api/batches/general', json=dict(white='Random', black='Random', games=1))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['owner']['program'], '網頁介面')
        self.assertIn('一般批次', response.json()['detail'])
        self.assertEqual([job['id'] for job in self.client.get('/api/jobs').json()], [first['id']])

    def test_stop_keeps_saved_games_and_frees_the_lock(self):
        job = self.start_slow_batch()
        wait_for(lambda: self.job(job['id'])['progress'].get('saved_games', 0) >= 1)
        self.client.post(f"/api/jobs/{job['id']}/stop")
        stopped = wait_for(lambda: (lambda item: item if item['status'] == 'stopped' else None)(self.job(job['id'])))
        manifest = json.loads((Path(stopped['progress']['path']) / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['status'], 'stopped')
        self.assertGreaterEqual(manifest['counts']['saved_games'], 1)
        self.assertEqual(self.client.post('/api/batches/general', json=dict(
            white='Random', black='Random', games=1, max_plies=2)).status_code, 201)

    def test_shutdown_stops_running_work_and_saves(self):
        job = self.start_slow_batch()
        wait_for(lambda: self.job(job['id'])['progress'].get('saved_games', 0) >= 1)
        self.app.state.jobs.shutdown(timeout=60)
        path = Path(self.job(job['id'])['progress']['path'])
        manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['status'], 'stopped')
        self.assertGreaterEqual(manifest['counts']['saved_games'], 1)

    def test_invalid_settings_are_rejected(self):
        response = self.client.post('/api/batches/general', json=dict(white='Human', games=1))
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/batches/general', json=dict(white='Greedy', white_config='../x.json'))
        self.assertEqual(response.status_code, 400)

    def test_events_start_with_full_snapshot_then_follow_changes(self):
        async def collect():
            events = job_events(self.app.state.jobs, interval=0.05, limit=2)
            first = await anext(events)
            self.start_slow_batch()
            second = await anext(events)
            return first, second
        first, second = asyncio.run(collect())
        self.assertEqual(first, 'event: jobs\ndata: []\n\n')
        payload = json.loads(second.split('data: ', 1)[1])
        self.assertEqual(payload[0]['kind'], 'general_batch')
        self.assertEqual(payload[0]['link'], '/batch')

    def test_reads_answer_while_heavy_work_runs(self):
        self.start_slow_batch()
        future = self.app.state.home.refresh()
        future.result(timeout=30)
        self.assertEqual(self.client.get('/api/home').json()['status'], 'ready')


class HomeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        dataset = self.root / 'data/learning/053dcfa4edfb44a687e4d3886748c569'
        dataset.mkdir(parents=True)
        (dataset / 'dataset.json').write_text('{}', encoding='utf-8')
        (self.root / 'data/learning-setup/broken').mkdir(parents=True)
        (self.root / 'data/learning-ui.json').write_text(
            json.dumps({'names': {str(dataset): '2026/10/29 研究資料'}}, ensure_ascii=False), encoding='utf-8')
        self.app = create_app(self.root / 'static', project_root=self.root,
                              lock_path=self.root / 'data/.heavy-job.lock', scan_on_start=False)
        self.client = TestClient(self.app, client=LOCAL)

    def tearDown(self):
        self.app.state.jobs.shutdown(timeout=60)
        cleanup(self.temp)

    def test_scan_lists_resumable_work_and_recent_research(self):
        self.assertEqual(self.client.get('/api/home').json()['status'], 'scanning')
        self.app.state.home.refresh().result(timeout=30)
        home = self.client.get('/api/home').json()
        self.assertEqual(home['status'], 'ready')
        self.assertEqual(home['recent_research'][0]['name'], '2026/10/29 研究資料')
        self.assertEqual([(item['kind'], item['status_label']) for item in home['resumable']],
                         [('comparison_bundle', '無法讀取')])
        self.assertEqual(home['recent_records'], [])
        self.assertEqual(home['running'], [])

    def test_finished_job_triggers_rescan(self):
        self.app.state.home.refresh().result(timeout=30)
        response = self.client.post('/api/batches/general', json=dict(white='Random', black='Random', games=1, max_plies=2))
        self.assertEqual(response.status_code, 201)
        wait_for(lambda: self.client.get('/api/home').json()['recent_records'])
        record = self.client.get('/api/home').json()['recent_records'][0]
        self.assertEqual((record['kind_label'], record['games']), ('一般批次', 1))


if __name__ == '__main__':
    unittest.main()
