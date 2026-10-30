"""搬移副本中的研究資料，依原始內容重建雜湊引用，不重跑實驗。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys


HASH = re.compile(r'[0-9a-f]{64}\Z')


def checksum(value, ascii_only=False):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=ascii_only,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def nodes(value, seen=None):
    if seen is None:
        seen = set()
    if isinstance(value, (dict, list)):
        if id(value) in seen:
            return
        seen.add(id(value))
    yield value
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from nodes(item, seen)
    elif isinstance(value, list):
        for item in value:
            yield from nodes(item, seen)


class SharedJson:
    """共用重複快照的唯讀物件，避免同一訓練輸入佔用數十份記憶體。"""

    def __init__(self):
        self.pool = {}

    @staticmethod
    def token(value):
        return (type(value), id(value)) if isinstance(value, (dict, list)) else (type(value), value)

    def intern(self, value):
        if isinstance(value, str):
            return sys.intern(value)
        if isinstance(value, dict):
            value = {sys.intern(key): self.intern(item) for key, item in value.items()}
            key = (dict, tuple(sorted((name, self.token(item)) for name, item in value.items())))
        elif isinstance(value, list):
            value = [self.intern(item) for item in value]
            key = (list, tuple(self.token(item) for item in value))
        else:
            return value
        return self.pool.setdefault(key, value)


class Relocation:
    """先在記憶體完成整個相依圖；無法驗證時不寫入任何資料。"""

    def __init__(self, documents, source, destination):
        self.documents = documents
        source = str(source).rstrip('/\\')
        self.destination = str(destination).rstrip('/\\')
        parts = re.split(r'[/\\]', source)
        self.path_pattern = re.compile(r'[/\\]'.join(re.escape(p) for p in parts)
                                       + r'(?=$|[/\\\s\"\'])', re.IGNORECASE)
        visited = set()
        self.references = {node for value in documents.values() for node in nodes(value, visited)
                           if isinstance(node, str) and HASH.fullmatch(node)}
        self.recipes = {}
        self.resolved = {}
        self.resolving = set()
        self.discovered = set()
        self.transformed = {}
        for filename, value in documents.items():
            self._discover(value, str(filename))

    def _register(self, value, ascii_only=False, expected=None):
        identity = checksum(value, ascii_only)
        if expected is not None and identity != expected:
            raise ValueError('原始內容身分不符：' + expected)
        if identity in self.references:
            self.recipes.setdefault(identity, {}).setdefault(ascii_only, value)

    def _discover(self, value, filename):
        if not isinstance(value, (dict, list)):
            return
        if id(value) in self.discovered:
            return
        self.discovered.add(id(value))
        self._register(value)
        self._register(value, True)
        if isinstance(value, list):
            for item in value:
                self._discover(item, filename)
            return
        identity = value.get('identity')
        if isinstance(identity, str) and HASH.fullmatch(identity):
            content = {key: item for key, item in value.items() if key != 'identity'}
            # 本專案的 identity 欄位皆為含其餘欄位的研究內容封印。
            self._register(content, expected=identity)
        if value.get('program_version') == 'weight-experiment-1':
            content = {key: item for key, item in value.items() if key != 'id'}
            self._register(content, True, value['id'])
            source = value.get('learning_source', {}).get('source')
            if source is not None:
                # 候選 id 的合成內容使用來源 digest，但該 digest 未必另存於 JSON。
                self.references.add(checksum(source))
                self._register(source)
            for candidate in value['candidates']:
                if source is not None:
                    self._register(dict(source=checksum(source), role=candidate['role'],
                                        config=candidate['config']), True, candidate['id'])
                for number in range(1, len(value['initial_fens']) * value['repetitions'] + 1):
                    for white in (False, True):
                        self._register([value['id'], candidate['id'], number, white], True)
        if {'snapshot_identity', 'sample_id', 'work_id', 'label'} <= value.keys():
            self._register([value['snapshot_identity'], value['sample_id']],
                           expected=value['work_id'])
        if 'positions' in value and isinstance(value['positions'], list):
            snapshot = value.get('label_snapshot', {})
            dataset = value.get('dataset_sha256', snapshot.get('dataset_sha256'))
            if dataset:
                test_ids = sorted(row['position_id'] for row in value['positions']
                                  if row.get('split') == 'test')
                self._register([dataset, test_ids])
        for item in value.values():
            self._discover(item, filename)

    def _resolve(self, identity):
        if identity in self.resolved:
            return self.resolved[identity]
        if identity not in self.recipes:
            return identity
        if identity in self.resolving:
            raise ValueError('內容身分出現循環相依：' + identity)
        self.resolving.add(identity)
        # 同一 ASCII 原文可能同時符合兩種編碼；不猜測有歧義的遷移結果。
        results = {checksum(self.transform(value), ascii_only)
                   for ascii_only, value in self.recipes[identity].items()}
        self.resolving.remove(identity)
        if len(results) != 1:
            raise ValueError('原始身分對應多種遷移結果：' + identity)
        result = results.pop()
        self.resolved[identity] = result
        return result

    def transform(self, value):
        if isinstance(value, (dict, list)) and id(value) in self.transformed:
            return self.transformed[id(value)]
        if isinstance(value, str):
            if HASH.fullmatch(value):
                return self._resolve(value)
            return self.path_pattern.sub(lambda match: self.destination, value)
        if isinstance(value, list):
            result = [self.transform(item) for item in value]
            self.transformed[id(value)] = result
            return result
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                target = self.transform(key)
                if target in result:
                    raise ValueError('搬移後字典索引衝突：' + target)
                result[target] = self.transform(item)
            self.transformed[id(value)] = result
            return result
        return value

    def plan(self):
        result = {name: self.transform(value) for name, value in self.documents.items()}
        visited = set()
        for name, value in result.items():
            if any(isinstance(node, str) and self.path_pattern.search(node) for node in nodes(value, visited)):
                raise ValueError('仍有來源路徑：' + str(name))
        return result


def read_documents(root):
    paths = []
    for folder in ('data', 'configs'):
        paths.extend((Path(root) / folder).rglob('*.json'))
    experiments = Path(root) / 'experiments.json'
    if experiments.exists():
        paths.append(experiments)
    shared = SharedJson()
    paths.sort()
    documents = {}
    with ThreadPoolExecutor(max_workers=8) as reader:
        # 限制預讀批量；不把所有大型輸入副本同時留在讀取佇列。
        for offset in range(0, len(paths), 32):
            batch = paths[offset:offset + 32]
            for path, text in zip(batch, reader.map(lambda path: path.read_text(encoding='utf-8-sig'), batch)):
                documents[path.relative_to(root)] = shared.intern(json.loads(text))
    return documents


def verify_project(root):
    """使用正式讀取入口驗證各種既有實驗，回傳可跨目錄比較的進度。"""
    from engine.learning.dataset import load_dataset
    from engine.learning.teacher import load_pilot
    from engine.learning.labeling import load_labeling
    from engine.learning.training import load_training
    from engine.learning.group_training import load_group_training
    from engine.learning.combination_training import load_combination
    from engine.learning.combination_batch import load_combination_batch
    from engine.learning.comparison import comparison_batch, comparison_report, load_comparison_plan
    from engine.learning.config_catalog import load_catalog, validate_catalog_row
    from engine.sessions.experiment_resume import resume_options, recover_pairs
    root = Path(root)
    summary = {}
    loaders = {'teacher-pilots': load_pilot, 'teacher-labels': load_labeling,
               'training': load_training, 'group-training': load_group_training,
               'combinations': load_combination, 'combination-batches': load_combination_batch}
    for path in sorted((root / 'data/learning').glob('*/dataset.json')):
        data = load_dataset(path.parent)
        summary[str(path.relative_to(root))] = dict(positions=len(data['positions']))
    for path in sorted((root / 'data/learning').rglob('snapshot.json')):
        kind = path.parent.parent.name
        if kind not in loaders:
            raise ValueError('未知研究資料類型：' + str(path))
        state = loaders[kind](path.parent)
        summary[str(path.relative_to(root))] = {
            key: state[key] for key in ('status', 'completed', 'total', 'remaining', 'ready',
                                       'completed_groups') if key in state}
    catalog = load_catalog(root / 'data/learning')
    if catalog['errors']:
        raise ValueError('候選目錄驗證失敗：' + str(catalog['errors']))
    for row in catalog['candidates']:
        validate_catalog_row(row)
    summary['catalog'] = dict(count=len(catalog['candidates']),
                              configs=sorted(checksum(row['source']['config']) for row in catalog['candidates']))
    for folder in ('learning-comparisons', 'learning-screening'):
        for path in sorted((root / 'data' / folder).glob('*/snapshot.json')):
            plan = load_comparison_plan(path.parent)
            report = comparison_report(path.parent)
            summary[str(path.relative_to(root))] = {
                key: [{metric: row[metric] for metric in ('wins', 'draws', 'losses', 'unfinished',
                       'planned_games', 'pending_games', 'completed_pairs', 'incomplete_pairs',
                       'interrupted_attempts')} for row in value['candidates']]
                for key, value in report['baselines'].items()}
            for baseline, definition in plan['definitions'].items():
                batch = comparison_batch(path.parent, baseline)
                if batch:
                    resume_options(batch)
                    # recover_pairs 只需此讀取方法；避免建立 writer 修改原批次。
                    class ReadOnlyWriter:
                        def recover_committed_games(self):
                            result = []
                            for replay_file in sorted((batch / 'replays').glob('*.json')):
                                replay = json.loads(replay_file.read_text(encoding='utf-8'))
                                result.append((replay_file, replay))
                            return result
                    pairs, attempts = recover_pairs(ReadOnlyWriter(), definition)
                    summary[str(batch.relative_to(root))] = dict(
                        recovered_games=sum(len(pair['games']) for pair in pairs),
                        interrupted_games=sum(len(pair['games']) for pair in attempts))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source')
    parser.add_argument('--destination')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.verify:
        report = verify_project(root)
    else:
        if not args.source or not args.destination:
            parser.error('請提供 --source 與 --destination')
        if args.apply and root != Path(args.destination).resolve():
            parser.error('只允許寫入目的地副本')
        print('讀取研究資料…', flush=True)
        original = read_documents(root)
        print(f'建立 {len(original)} 份文件的身分相依圖…', flush=True)
        relocation = Relocation(original, args.source, args.destination)
        updated = relocation.plan()
        print('身分相依圖已完成驗證。', flush=True)
        changed = [name for name in original if original[name] != updated[name]]
        report = dict(documents=len(original), changed=len(changed),
                      identities=sum(old != new for old, new in relocation.resolved.items()),
                      changed_files=[str(name) for name in changed])
        if args.apply:
            # 先確認規劃期間無人修改資料；來源副本仍保留供整批回復。
            def unchanged(entry):
                name, content = entry
                if json.loads((root / name).read_text(encoding='utf-8-sig')) != content:
                    raise ValueError('規劃期間資料已變更，拒絕寫入：' + str(name))
            with ThreadPoolExecutor(max_workers=4) as reader:
                for _ in reader.map(unchanged, original.items()):
                    pass
            print(f'套用 {len(changed)} 份更新…', flush=True)
            for name in changed:
                path = root / name
                stat = path.stat()
                temporary = path.with_name(path.name + '.relocation-tmp')
                with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                    json.dump(updated[name], stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.write('\n')
                temporary.replace(path)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    display = dict(verified_entries=len(report), candidates=report['catalog']['count']) if args.verify else {
        key: value for key, value in report.items() if key != 'changed_files'}
    print(json.dumps(display, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
