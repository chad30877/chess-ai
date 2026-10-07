"""在背景執行共用比較服務，提供可安全讀取的進度與停止訊號。"""

from threading import Event, Lock

from engine.sessions.evaluation_comparison import run_evaluation_comparison


class ComparisonRun:
    def __init__(self, options: dict, executor):
        self._stop = Event()
        self._lock = Lock()
        self.options = dict(options)
        pairs = len(options["initial_fens"]) * options["repetitions"]
        self._state = dict(status="running", batch_id="", path="", error="", current_game=0,
                           requested_games=pairs * 2, requested_pairs=pairs, saved_games=0,
                           completed_games=0, unfinished=0, completed_pairs=0, incomplete_pairs=0,
                           saved_pairs=0, paired_score_rate=None, last_replay=None)
        self.future = executor.submit(self._run)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def stop(self):
        with self._lock:
            if self._state["status"] == "running":
                self._stop.set()
                self._state["status"] = "stopping"

    def _progress(self, state):
        with self._lock:
            self._state.update(state)
            if self._stop.is_set() and state["status"] == "running":
                self._state["status"] = "stopping"

    def _run(self):
        try:
            return run_evaluation_comparison(**self.options, control=lambda: not self._stop.is_set(),
                                             progress=self._progress)
        except Exception as exc:
            with self._lock:
                self._state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            return None
