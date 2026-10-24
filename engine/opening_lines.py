"""共同開局線的合法歷史與固定來源選取。"""

from collections import defaultdict, deque
from copy import deepcopy

import chess


def replay_opening(line, *, claim_draw=False):
    board = chess.Board(line['initial_fen'])
    if not board.is_valid():
        raise ValueError('開局線起始局面無效')
    for uci in line['moves_uci']:
        if board.is_game_over(claim_draw=claim_draw):
            raise ValueError('開局線已終局')
        board.push_uci(uci)
    if board.is_game_over(claim_draw=claim_draw):
        raise ValueError('開局線已終局')
    return board


def normalize_openings(initial_fens, opening_lines=None, *, claim_draw=False):
    if opening_lines is None:
        return [dict(initial_fen=fen, moves_uci=[], name='', source={}) for fen in initial_fens]
    if not opening_lines:
        raise ValueError('至少需要一條開局線')
    lines = deepcopy(list(opening_lines))
    for line in lines:
        if not isinstance(line.get('moves_uci'), list):
            raise ValueError('開局線需有完整 UCI 前綴')
        replay_opening(line, claim_draw=claim_draw)
        line['initial_fen'] = chess.Board(line['initial_fen']).fen()
    return lines


def common_opening_lines(book, count=32, max_plies=12):
    """按 ECO 類型輪流選取，以實際前綴去重，不足時拒絕湊數。"""
    if count < 1 or not 1 <= max_plies <= 12:
        raise ValueError('共同開局需為正數，前綴上限為 1–12 手')
    groups = defaultdict(deque)
    seen = set()
    for entry in sorted(book.lines, key=lambda item: (item['eco'], item['name'])):
        moves = entry['moves_uci'][:max_plies]
        identity = tuple(moves)
        if not moves or identity in seen:
            continue
        line = dict(initial_fen=chess.STARTING_FEN, moves_uci=moves,
                    name=entry['name'], eco=entry['eco'], source=deepcopy(book.source))
        try:
            replay_opening(line)
        except ValueError:
            continue
        seen.add(identity)
        groups[entry['eco'][:2]].append(line)
    selected = []
    while groups and len(selected) < count:
        for key in sorted(groups, key=lambda code: (code[1:], code[0])):
            selected.append(groups[key].popleft())
            if not groups[key]:
                del groups[key]
            if len(selected) == count:
                break
    if len(selected) < count:
        raise ValueError(f'不同合法開局線不足：需要 {count} 條，僅有 {len(selected)} 條')
    return selected
