"""可控制的外部教師程序。"""
from pathlib import Path
import sys

def make_engine(root):
    path = Path(root) / "uci.py"
    path.write_text('''import sys
fresh = 'initial'
for line in sys.stdin:
 line=line.strip()
 if line=='uci':
  print('id name Stockfish 19', flush=True)
  print('option name Threads type spin default 1 min 1 max 16', flush=True)
  print('option name Hash type spin default 16 min 1 max 128', flush=True)
  print('option name SyzygyPath type string default <empty>', flush=True)
  print('option name SyzygyProbeLimit type spin default 7 min 0 max 7', flush=True)
  print('uciok', flush=True)
 elif line=='ucinewgame': fresh='new'
 elif line=='setoption name Clear Hash':
  assert fresh=='new'
  fresh='cleared'
 elif line=='isready':
  if fresh=='cleared': fresh='ready'
  print('readyok', flush=True)
 elif line.startswith('position '):
  moves=line.split(' moves ')[1].split() if ' moves ' in line else []
 elif line.startswith('go '):
  assert fresh=='ready'
  fresh='used'
  import chess
  board=chess.Board()
  for m in moves: board.push_uci(m)
  best=next(iter(board.legal_moves)).uci()
  print('info depth 1 score cp 999 lowerbound nodes 20', flush=True)
  print('info depth 2 score cp 25 nodes '+line.split()[-1]+' pv '+best, flush=True)
  print('bestmove '+best, flush=True)
 elif line=='quit': break
''', encoding='utf-8')
    return [sys.executable, str(path)]
