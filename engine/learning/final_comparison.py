"""凍結使用者選定的候選，並沿用條件完全相同的比較計畫。"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json

from engine.learning.comparison import create_comparison, load_comparison_plan
from engine.learning.teacher import digest
from engine.storage.batch_storage import write_json_atomic


def freeze_final_comparison(root, candidates, *, learned_only=False):
    root = Path(root)
    candidates = deepcopy(list(candidates))
    if not 1 <= len(candidates) <= 5:
        raise ValueError('請選擇一至五個候選')
    identities = [digest(c['config']) for c in candidates]
    if len(set(identities)) != len(identities):
        raise ValueError('候選設定內容不可重複')
    entries = []
    for source in candidates:
        path = create_comparison(root, source, roles=('learned',), stable=True)
        template = load_comparison_plan(path)
        matching = {}
        # 基準各自核對；既有計畫可同時包含原始與學習設定。
        for file in sorted((root / 'data/learning-comparisons').glob('*/snapshot.json')):
            if file.parent == path:
                continue
            try:
                old = load_comparison_plan(file.parent)
                if digest(old['source']) != digest(source):
                    continue
                if learned_only and (old.get('roles') != ['learned'] or
                        any(len(definition.get('candidates', [])) != 1 or
                            definition['candidates'][0].get('role') != 'learned'
                            for definition in old['definitions'].values())):
                    continue
                for baseline, definition in old['definitions'].items():
                    if baseline not in template['definitions']:
                        continue
                    expected = template['definitions'][baseline]
                    keys = ('opening_lines', 'search', 'workers', 'max_plies', 'claim_draw', 'base_seed', 'repetitions', 'baseline')
                    if (all(definition.get(k) == expected.get(k) for k in keys)
                        and any(item.get('role') == 'learned' and item['config'] == source['config'] for item in definition['candidates'])):
                        matching.setdefault(baseline, (file.parent, definition))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if len(matching) == 2 and matching['material'][0] == matching['stable'][0]:
            path = matching['material'][0]
        elif matching:
            for baseline, (_, definition) in matching.items():
                template['definitions'][baseline] = definition
            template['planned_games'] = sum(d['planned_games'] for d in template['definitions'].values())
            template.pop('identity')
            template['identity'] = digest(template)
            write_json_atomic(path / 'snapshot.json', template)
        entries.append(dict(source=source, path=str(path), plan_identity=load_comparison_plan(path)['identity']))
    path = root / 'data/learning-final' / uuid4().hex
    path.mkdir(parents=True)
    snapshot = dict(format_version=1, candidates=entries)
    snapshot['identity'] = digest(snapshot)
    write_json_atomic(path / 'snapshot.json', snapshot)
    return path


def load_final_comparison(path):
    value = json.loads((Path(path) / 'snapshot.json').read_text(encoding='utf-8'))
    content = dict(value); content.pop('identity', None)
    if value.get('format_version') != 1 or value.get('identity') != digest(content):
        raise ValueError('完整比較候選身份或版本不符')
    for entry in value['candidates']:
        plan = load_comparison_plan(entry['path'])
        if plan['identity'] != entry['plan_identity'] or digest(plan['source']) != digest(entry['source']):
            raise ValueError('完整比較來源與凍結候選不符')
    return value
