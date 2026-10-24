"""不可變的權重實驗快照與穩定工作識別。"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig


def stable_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def enabled_weight_fields(config):
    payload = config.to_dict()
    return tuple(f'{name}.{weight}' for name, term in payload['terms'].items()
                 if name != 'material' and term['enabled']
                 for weight in (('weight', 'endgame_weight') if config.phase_enabled else ('weight',)))


@dataclass(frozen=True)
class ExperimentDefinition:
    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)

    def options(self, batch_root):
        data = self.to_dict()
        search = ComparisonSearchConfig(**data['search'])
        participant = lambda item: ComparisonParticipant.alphabeta(item['label'], EvaluationConfig.from_dict(item['config']), search=search)
        options = dict(baseline=participant(data['baseline']), candidates=[participant(c) for c in data['candidates']],
                    initial_fens=tuple(data['initial_fens']), repetitions=data['repetitions'], base_seed=data['base_seed'],
                    max_plies=data['max_plies'], claim_draw=data['claim_draw'], batch_root=batch_root,
                    name=data['name'], tags=data['tags'], experiment_definition=data)
        if 'opening_lines' in data:
            options['opening_lines'] = data['opening_lines']
        return options


MAX_CANDIDATES = 10000


def parse_values(text):
    from decimal import Decimal, InvalidOperation
    try:
        if ':' in text:
            start, end, step = [Decimal(x.strip()) for x in text.split(':')]
            if not all(x.is_finite() for x in (start, end, step)) or start < 0 or end < start or step <= 0:
                raise ValueError("範圍需為非負起點、遞增終點及正間隔")
            count = int((end - start) // step) + 1
            if count > MAX_CANDIDATES:
                raise ValueError("候選數超過 10000 上限")
            numbers = [float(start + step * index) for index in range(count)]
        else:
            parts = text.split(',')
            if len(parts) > MAX_CANDIDATES:
                raise ValueError("候選數超過 10000 上限")
            numbers = [float(value.strip()) for value in parts]
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("無效權重範圍") from exc
    if any(not math.isfinite(value) or value < 0 for value in numbers):
        raise ValueError("權重需為有限非負數")
    return numbers


def rule_values(config, rule):
    if rule['field'] not in enabled_weight_fields(config):
        raise ValueError('請選擇已啟用的權重')
    term, weight = rule['field'].split('.')
    base = config.to_dict()['terms'][term][weight]
    numbers = parse_values(rule['values'])
    if rule['mode'] == 'percent':
        if base == 0:
            raise ValueError('零基準請使用實際值')
        numbers = [value * base / 100 for value in numbers]
    elif rule['mode'] != 'actual':
        raise ValueError('無效表示模式')
    if any(not math.isfinite(value) for value in numbers):
        raise ValueError('權重需為有限數')
    if 'actual_values' in rule:
        numbers = list(rule['actual_values'])
        if any(not math.isfinite(value) or value < 0 for value in numbers):
            raise ValueError('權重需為有限非負數')
    return numbers


def build_experiment(options, field=None, values=None, *, rules=None):
    from itertools import product
    config = options['baseline'].evaluation_config
    baseline = config.to_dict()
    rules = rules if rules is not None else [dict(field=field, values=values, mode='actual')]
    if not rules or len({r['field'] for r in rules}) != len(rules):
        raise ValueError('請選擇不同權重')
    dimensions = []
    count = 1
    for rule in rules:
        numbers = rule_values(config, rule)
        count *= len(numbers)
        if count > MAX_CANDIDATES:
            raise ValueError('候選數超過 10000 上限，請縮小範圍')
        dimensions.append(numbers)
    seen, candidates, duplicates, unchanged = set(), [], 0, 0
    for combination in product(*dimensions):
        payload = config.to_dict()
        differences = {}
        for rule, value in zip(rules, combination):
            term, weight = rule['field'].split('.')
            payload['terms'][term][weight] = value
            differences[rule['field']] = value
        payload = EvaluationConfig.from_dict(payload).to_dict()
        identity = stable_id(payload)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        if payload == baseline:
            unchanged += 1
            continue
        candidates.append(dict(id=identity, label=f'候選 {len(candidates) + 1}：' + '; '.join(f'{key}={value!r}' for key, value in differences.items()), config=payload, differences=differences))
    data = dict(schema_version=1, program_version='weight-experiment-1',
                baseline=dict(label=options['baseline'].label, config=baseline), candidates=candidates,
                search=asdict(options['baseline'].search_config), initial_fens=list(options['initial_fens']),
                repetitions=options['repetitions'], base_seed=options['base_seed'],
                seed_policy='base_seed + pair_number - 1; reset each color and candidate',
                max_plies=options['max_plies'], claim_draw=options['claim_draw'], name=options['name'], tags=options['tags'],
                generation=dict(rules=rules, raw_candidate_count=count), duplicate_count=duplicates, baseline_count=unchanged,
                planned_games=len(candidates)*len(options['initial_fens'])*options['repetitions']*2)
    if options.get('opening_lines') is not None:
        data.update(schema_version=2, opening_lines=options['opening_lines'])
    data['id'] = stable_id(data)
    return ExperimentDefinition(json.dumps(data, sort_keys=True))


def freeze_comparison(options):
    """保存既有設定檔及共同開局，重開不再讀取可變來源。"""
    def snapshot(side):
        config = side.evaluation_config.to_dict()
        return dict(label=side.label, config=config,
                    id=stable_id(dict(label=side.label, config=config)), differences={})

    data = dict(schema_version=2, program_version='weight-experiment-1',
                baseline=snapshot(options['baseline']),
                candidates=[snapshot(side) for side in options['candidates']],
                search=asdict(options['baseline'].search_config),
                initial_fens=list(options['initial_fens']), opening_lines=options['opening_lines'],
                repetitions=options['repetitions'], base_seed=options['base_seed'],
                max_plies=options['max_plies'], claim_draw=options['claim_draw'],
                name=options['name'], tags=options['tags'], generation=dict(mode='files'),
                planned_games=len(options['candidates'])*len(options['opening_lines'])*options['repetitions']*2)
    data['id'] = stable_id(data)
    return ExperimentDefinition(json.dumps(data, sort_keys=True))


def work_id(definition, candidate_index, pair_number, candidate_is_white):
    return stable_id([definition['id'], definition['candidates'][candidate_index]['id'], pair_number, candidate_is_white])
