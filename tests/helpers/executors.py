"""Deterministic executor for controlling background jobs in tests."""

from concurrent.futures import Future


class ManualExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future

    def finish(self, index=-1):
        future, fn, args = self.jobs[index]
        future.set_result(fn(*args))
