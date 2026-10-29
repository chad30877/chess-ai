"""以背景讀取更新報告，並隔離已切換來源的結果。"""
from time import monotonic


class ReportRefresh:
    def __init__(self):
        self.future = None
        self.path = None
        self.next_at = 0
        self.error = None

    @staticmethod
    def _read(loader, path):
        try:
            return loader(path), None
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            return None, str(exc)

    def poll(self, path, loader, executor):
        if path != self.path:
            self.path, self.future, self.next_at, self.error = path, None, 0, None
        result = None
        if self.future is not None and self.future.done():
            result = self.future.result()
            self.error = result[1]
            self.future = None
            self.next_at = monotonic() + 1
        if self.future is None and monotonic() >= self.next_at:
            self.future = executor.submit(self._read, loader, path)
        return result
