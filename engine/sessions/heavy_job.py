"""全機同時只跑一個重度工作：以作業系統檔案鎖跨程序互斥，pygame 與網頁伺服器共用。"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH = ROOT / 'data' / '.heavy-job.lock'


class HeavyJobBusy(ValueError):
    """另一個重度工作正持有全機鎖；owner 為佔用者自述，可能為 None。"""

    def __init__(self, owner):
        self.owner = owner
        label = owner.get('label') if owner else None
        program = owner.get('program') if owner else None
        detail = f'{program}：{label}' if label and program else (label or program or '另一個程序')
        super().__init__(f'已有重度工作執行中（{detail}），請等它結束或先停止')


def _owner_path(lock_path):
    return Path(lock_path).with_suffix('.owner.json')


def read_owner(lock_path=None):
    try:
        return json.loads(_owner_path(lock_path or DEFAULT_LOCK_PATH).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


class HeavyJobHold:
    """持有中的全機鎖；release 可重複呼叫。"""

    def __init__(self, stream, lock_path):
        self._stream = stream
        self._lock_path = Path(lock_path)
        self._guard = Lock()

    def release(self):
        with self._guard:
            if self._stream is None:
                return
            try:
                _owner_path(self._lock_path).unlink(missing_ok=True)
            except OSError:
                pass
            if os.name == 'nt':
                import msvcrt
                try:
                    self._stream.seek(0)
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self._stream.close()
            self._stream = None


def acquire(*, program, label, lock_path=None):
    """不等待：取得則回傳 HeavyJobHold，否則丟出 HeavyJobBusy。"""
    lock_path = Path(lock_path or DEFAULT_LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise HeavyJobBusy(read_owner(lock_path)) from None
    owner = dict(program=program, label=label, pid=os.getpid(),
                 started_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    try:
        _owner_path(lock_path).write_text(json.dumps(owner, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass
    return HeavyJobHold(stream, lock_path)


class HeavyJobExecutor:
    """包住執行器：每次 submit 先取得全機鎖，工作結束後釋放。

    取不到鎖時在 submit 當下丟出 HeavyJobBusy，工作物件不會開始執行。
    """

    def __init__(self, executor, *, program, lock_path=None):
        self._executor = executor
        self._program = program
        self._lock_path = lock_path
        self.label = '重度工作'

    def submit(self, fn, *args, **kwargs):
        hold = acquire(program=self._program, label=self.label, lock_path=self._lock_path)
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except BaseException:
            hold.release()
            raise
        future.add_done_callback(lambda _: hold.release())
        return future

    def __getattr__(self, name):
        return getattr(self._executor, name)
