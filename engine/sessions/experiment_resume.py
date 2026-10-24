"""從不可變快照續跑，以作業系統鎖防止同一實驗重複派工。"""
from contextlib import contextmanager
import json
import os
from pathlib import Path

@contextmanager
def experiment_lock(path):
    stream = (Path(path) / '.execution.lock').open('a+b')
    try:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('此實驗已有執行者') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('此實驗已有執行者') from exc
        yield
    finally:
        stream.close()

def resume_options(path):
    from engine.sessions.experiment import ExperimentDefinition
    path = Path(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    data = manifest.get('settings', {}).get('experiment')
    if not data:
        raise ValueError('此舊紀錄缺少實驗快照，無法續跑')
    if data.get('schema_version') not in (1, 2) or data.get('program_version') != 'weight-experiment-1':
        raise ValueError('實驗版本不相容，請建立新實驗')
    if manifest.get('schema_version') != 2:
        raise ValueError('保存契約不相容，請建立新實驗')
    return dict(ExperimentDefinition(json.dumps(data)).options(path.parent), resume_path=path)

def resume_experiment(path, **callbacks):
    from engine.sessions.evaluation_comparison import run_evaluation_comparison
    return run_evaluation_comparison(**resume_options(path), **callbacks)

def recover_pairs(writer, definition):
    """棋譜是提交事實；摘要過期時由穩定工作識別重建。"""
    from engine.sessions.experiment import work_id
    from engine.sessions.evaluation_comparison import comparison_game_record
    replays = writer.recover_committed_games()
    by_id = {}
    for _, replay in replays:
        metadata = replay['metadata']
        if metadata['termination'] != 'user_stop':
            by_id[metadata['execution']['work_id']] = metadata
    pairs = []
    attempts = []
    for index, candidate in enumerate(definition['candidates']):
        for number in range(1, len(definition['initial_fens'])*definition['repetitions']+1):
            position = (number-1)//definition['repetitions']
            games = []
            for white in (False, True):
                identity = work_id(definition,index,number,white)
                meta = by_id.get(identity)
                if not meta:
                    continue
                summary = meta['summary']
                games.append(comparison_game_record(summary, meta['execution'], white))
            if games:
                pair=dict(pair_number=number,position_index=position+1,repetition=(number-1)%definition['repetitions']+1,
                          initial_fen=definition['initial_fens'][position],seed=definition['base_seed']+number-1,games=games)
                if 'opening_lines' in definition:
                    pair['opening_line'] = definition['opening_lines'][position]
                if len(definition['candidates']) > 1:
                    pair.update(candidate_index=index,candidate_label=candidate['label'])
                pairs.append(pair)
    for _, replay in replays:
        meta = replay['metadata']
        if meta['termination'] != 'user_stop':
            continue
        execution = meta['execution']
        for index, candidate in enumerate(definition['candidates']):
            if candidate['id'] == execution['candidate_id']:
                white = execution['game_number'] % 2 == 0
                summary = meta['summary']
                attempts.append(dict(candidate_index=index, games=[comparison_game_record(summary, execution, white)]))
                break
    return pairs, attempts
