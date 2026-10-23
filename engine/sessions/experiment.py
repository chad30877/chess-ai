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
        return dict(baseline=participant(data['baseline']), candidates=[participant(c) for c in data['candidates']],
                    initial_fens=tuple(data['initial_fens']), repetitions=data['repetitions'], base_seed=data['base_seed'],
                    max_plies=data['max_plies'], claim_draw=data['claim_draw'], batch_root=batch_root,
                    name=data['name'], tags=data['tags'], experiment_definition=data)


def build_experiment(options, field, values):
    config = options['baseline'].evaluation_config
    if field not in enabled_weight_fields(config):
        raise ValueError('請選擇已啟用的權重')
    term, weight = field.split('.')
    baseline = config.to_dict()
    seen, candidates, duplicates, unchanged = set(), [], 0, 0
    numbers = [float(value.strip()) for value in values.split(',')]
    if len(numbers) > 10000:
        raise ValueError('候選值上限為 10000')
    for value in numbers:
        if not math.isfinite(value) or value < 0:
            raise ValueError('權重需為有限非負數')
        payload = config.to_dict()
        payload['terms'][term][weight] = value
        payload = EvaluationConfig.from_dict(payload).to_dict()
        identity = stable_id(payload)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        if payload == baseline:
            unchanged += 1
            continue
        candidates.append(dict(id=identity, label=f'{field}={value:g}', config=payload, differences={field: value}))
    data = dict(schema_version=1, program_version='weight-experiment-1',
                baseline=dict(label=options['baseline'].label, config=baseline), candidates=candidates,
                search=asdict(options['baseline'].search_config), initial_fens=list(options['initial_fens']),
                repetitions=options['repetitions'], base_seed=options['base_seed'],
                seed_policy='base_seed + pair_number - 1; reset each color and candidate',
                max_plies=options['max_plies'], claim_draw=options['claim_draw'], name=options['name'], tags=options['tags'],
                generation=dict(field=field, values=numbers), duplicate_count=duplicates, baseline_count=unchanged,
                planned_games=len(candidates)*len(options['initial_fens'])*options['repetitions']*2)
    data['id'] = stable_id(data)
    return ExperimentDefinition(json.dumps(data, sort_keys=True))


def work_id(definition, candidate_index, pair_number, candidate_is_white):
    return stable_id([definition['id'], definition['candidates'][candidate_index]['id'], pair_number, candidate_is_white])
