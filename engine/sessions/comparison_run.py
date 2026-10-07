"""評分比較的配對政策，背景控制使用共用批次執行機制。"""

from engine.sessions.batch_execution import BatchExecution
from engine.sessions.evaluation_comparison import run_evaluation_comparison


class ComparisonRun(BatchExecution):
    mode = "evaluation"
    can_pause = False

    def __init__(self, options: dict, executor):
        self.options = dict(options)
        pairs = len(options["initial_fens"]) * options["repetitions"]
        super().__init__(executor, requested_games=pairs * 2, requested_pairs=pairs,
                         completed_pairs=0, incomplete_pairs=0, saved_pairs=0, paired_score_rate=None)

    def _execute(self):
        return run_evaluation_comparison(**self.options, control=self._control,
                                         progress=self._progress)
