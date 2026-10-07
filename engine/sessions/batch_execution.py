"""共用背景派發、進度與合作式控制；對局配對由各模式負責。"""

from threading import Condition
from time import monotonic


class BatchExecution:
    mode = "general"
    can_pause = True

    def __init__(self, executor, *, requested_games, **progress):
        self._condition = Condition()
        self._paused = self._stopped = False
        self._state = dict(status="running", current_game=0, saved_games=0,
                           requested_games=requested_games, batch_id="", path="", error="",
                           completed_games=0, unfinished=0, last_replay=None, **progress)
        self.future = executor.submit(self._run)

    def snapshot(self):
        with self._condition:
            return dict(self._state)

    def _progress(self, state):
        with self._condition:
            self._state.update(state)
            if self._state["status"] == "running":
                if self._stopped:
                    self._state["status"] = "stopping"
                elif self._paused:
                    self._state["status"] = "paused"

    def pause(self):
        with self._condition:
            if self.can_pause and self._state["status"] == "running":
                self._paused = True
                self._state["status"] = "paused"
                self._condition.notify_all()

    def resume(self):
        with self._condition:
            if self._state["status"] == "paused" and not self._stopped:
                self._paused = False
                self._state["status"] = "running"
                self._condition.notify_all()

    def stop(self):
        with self._condition:
            if self._state["status"] in ("running", "paused"):
                self._stopped = True
                self._state["status"] = "stopping"
                self._condition.notify_all()

    def _control(self):
        with self._condition:
            while self._paused and not self._stopped:
                self._condition.wait()
            return not self._stopped

    def _wait_interval(self, seconds):
        remaining = seconds
        with self._condition:
            while remaining > 0 and not self._stopped:
                if self._paused:
                    self._condition.wait()
                    continue
                start = monotonic()
                self._condition.wait(timeout=remaining)
                remaining -= monotonic() - start
        return self._control()

    def _run(self):
        try:
            return self._execute()
        except Exception as exc:
            self._progress(dict(status="failed", error=f"{type(exc).__name__}: {exc}"))
            return None


def start_batch(mode, settings, root, executor):
    """兩種設定共用派發入口，保持配對與統計政策分離。"""
    from engine.sessions.batch_run import BatchRun
    from engine.sessions.comparison_run import ComparisonRun

    if mode == "general":
        return BatchRun(settings, root, executor)
    if mode == "evaluation":
        return ComparisonRun({**settings, "batch_root": root}, executor)
    raise ValueError(f"未知批次模式：{mode}")
