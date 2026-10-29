"""真實教師的有限流程驗證，不啟動正式長實驗。"""
import json
from pathlib import Path
from time import perf_counter
from tempfile import TemporaryDirectory
from engine.learning.dataset import create_dataset
from engine.learning.teacher import run_pilot, choose_budget
from engine.learning.labeling import create_labeling, run_labeling, load_labeling
from tests.test_learning_dataset import pgn_games

def main():
    root = Path.cwd()
    start = perf_counter()
    with TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
        work = Path(folder)
        pgn = work / 'small.pgn'; pgn.write_text(pgn_games(2), encoding='utf-8')
        dataset = create_dataset(work / 'data', pgn, seed=20261029)
        pilot = run_pilot(dataset, str(root / 'tools/stockfish/stockfish-windows-x86-64-universal.exe'), workers=2)
        choose_budget(pilot, 50000)
        labels = create_labeling(dataset, pilot, reuse=True)
        run_labeling(labels)
        saved = load_labeling(labels)
        assert saved['ready'], saved.get('error')
        assert create_labeling(dataset, pilot, reuse=True) == labels
        result = dict(status=saved['status'], completed=saved['completed'], total=saved['total'], reuse=True, seconds=round(perf_counter()-start, 2))
        (Path(__file__).with_name('real-teacher.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(result)
if __name__ == '__main__': main()
