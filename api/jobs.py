"""伺服器持有的工作登錄處：建立、查詢、停止，以及全機重度工作互斥。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from threading import Lock

from engine.sessions.heavy_job import DEFAULT_LOCK_PATH, HeavyJobExecutor

FINISHED = {'completed', 'stopped', 'failed'}


@dataclass
class Job:
    id: str
    kind: str
    label: str
    link: str
    run: object
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='seconds'))

    def snapshot(self):
        state = self.run.snapshot()
        status = state.get('status', 'running')
        if self.run.future.done() and status not in FINISHED:
            # 工作函式已返回但未回報終態時，以 future 為準。
            status = 'failed' if self.run.future.exception() else 'completed'
        return dict(id=self.id, kind=self.kind, label=self.label, link=self.link,
                    started_at=self.started_at, status=status,
                    can_pause=bool(getattr(self.run, 'can_pause', False)), progress=_progress(state))


def _progress(state):
    keys = ('saved_games', 'requested_games', 'completed_games', 'unfinished', 'batch_id', 'path', 'error',
            'requested_workers', 'actual_workers', 'waiting_work', 'running_work', 'finished_work')
    return {key: state[key] for key in keys if key in state}


class JobService:
    """重度工作共用一個執行器與全機鎖；讀取工作使用另外的執行緒池。"""

    def __init__(self, *, lock_path=DEFAULT_LOCK_PATH, heavy_workers=4, read_workers=2):
        self._heavy_pool = ThreadPoolExecutor(max_workers=heavy_workers, thread_name_prefix='heavy')
        self.heavy = HeavyJobExecutor(self._heavy_pool, program='網頁介面', lock_path=lock_path)
        self.reads = ThreadPoolExecutor(max_workers=read_workers, thread_name_prefix='read')
        self._jobs = {}
        self._ids = count(1)
        self._lock = Lock()
        self._listeners = []

    def start(self, kind, label, link, create):
        """create(executor) 建構工作物件；取不到全機鎖時丟出 HeavyJobBusy。"""
        with self._lock:
            self.heavy.label = label
            run = create(self.heavy)
            job = Job(str(next(self._ids)), kind, label, link, run)
            self._jobs[job.id] = job
        run.future.add_done_callback(lambda _: self._notify_finished(job))
        return job

    def on_finished(self, listener):
        self._listeners.append(listener)

    def _notify_finished(self, job):
        for listener in self._listeners:
            listener(job)

    def get(self, job_id):
        return self._jobs.get(job_id)

    def snapshots(self):
        with self._lock:
            jobs = list(self._jobs.values())
        return [job.snapshot() for job in jobs]

    def running(self):
        return [item for item in self.snapshots() if item['status'] not in FINISHED]

    def control(self, job_id, action):
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if action == 'stop':
            job.run.stop()
        elif action in ('pause', 'resume') and getattr(job.run, 'can_pause', False):
            getattr(job.run, action)()
        else:
            raise ValueError(f'此工作不支援{action}')
        return job.snapshot()

    def shutdown(self, timeout=None):
        """停止所有工作並等待保存完成。"""
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if not job.run.future.done():
                job.run.stop()
        for job in jobs:
            try:
                job.run.future.result(timeout=timeout)
            except Exception:
                pass
        self._heavy_pool.shutdown(wait=True, cancel_futures=True)
        self.reads.shutdown(wait=False, cancel_futures=True)
