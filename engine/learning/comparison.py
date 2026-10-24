"""把完整學習候選封存為各基準獨立的共同開局比較。"""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from engine.evaluation.config import EvaluationConfig
from engine.learning.teacher import digest
from engine.opening_book import OpeningBook
from engine.opening_lines import common_opening_lines
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig
from engine.sessions.experiment import ExperimentDefinition, freeze_comparison, stable_id, work_id
from engine.sessions.experiment_resume import resume_options
from engine.storage.batch_storage import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


def create_comparison(root, candidate, *, roles=('original','learned'), stable=False, opening_lines=None, max_plies=None):
    """預設正式32線；測試可提供小型合法線，不改搜尋及身份契約。"""
    source = deepcopy(candidate)
    for key in ('config','original','stable'): EvaluationConfig.from_dict(source[key])
    for key in ('kind','groups','experiment_id','snapshot_identity','candidate_identity','report'):
        if key not in source: raise ValueError('缺少完整學習來源：'+key)
    roles = list(roles)
    if not roles or len(set(roles)) != len(roles) or any(r not in ('original','learned') for r in roles):
        raise ValueError('請選擇原始或學習候選')
    lines = common_opening_lines(OpeningBook(),count=32,max_plies=12) if opening_lines is None else deepcopy(opening_lines)
    from engine.opening_lines import normalize_openings
    lines = normalize_openings([],lines)
    search = ComparisonSearchConfig(depth_plies=3,quiescence_depth=4,search_workers=1,transposition_capacity=4096)
    material = json.loads((ROOT/'configs/evaluation/learning-material.json').read_text(encoding='utf-8'))
    definitions = {}
    plan_id=uuid4().hex
    for baseline,config in [('material',material)]+([('stable',source['stable'])] if stable else []):
        side = lambda label,payload: ComparisonParticipant.alphabeta(label,EvaluationConfig.from_dict(payload),search=search)
        options = dict(baseline=side('純子力主基準' if baseline=='material' else 'stable 參考',config),
            candidates=[side('原始設定' if role=='original' else {'direct':'直接組合','joint':'聯合訓練'}.get(source['kind'],'學習設定'),
                source['original'] if role=='original' else source['config']) for role in roles],
            initial_fens=[line['initial_fen'] for line in lines], opening_lines=lines,repetitions=1,
            base_seed=10000,max_plies=max_plies,claim_draw=False,name='學習結果 · '+baseline,tags=['learning-research'],workers=4)
        definition = freeze_comparison(options).to_dict()
        definition['learning_source'] = dict(source=source,baseline=baseline,roles=roles,plan_id=plan_id)
        for item,role in zip(definition['candidates'],roles):
            item['role']=role
            item['id']=stable_id(dict(source=digest(source),role=role,config=item['config']))
        definition.pop('id'); definition['id']=stable_id(definition)
        definitions[baseline]=definition
    path = Path(root)/'data/learning-comparisons'/plan_id
    payload = dict(format_version=1,id=path.name,source=source,roles=roles,definitions=definitions,
                   planned_games=sum(d['planned_games'] for d in definitions.values()))
    payload['identity']=digest(payload)
    path.mkdir(parents=True)
    write_json_atomic(path/'snapshot.json',payload)
    return path


def load_comparison_plan(path):
    value=json.loads((Path(path)/'snapshot.json').read_text(encoding='utf-8'))
    content=dict(value); content.pop('identity',None)
    if value.get('format_version')!=1 or value.get('identity')!=digest(content): raise ValueError('比較計畫身份或版本不符')
    return value


def comparison_batch(path, baseline):
    """由保存的實驗身份尋找批次，重開不依賴 UI 記憶體。"""
    path=Path(path); definition=load_comparison_plan(path)['definitions'][baseline]
    matches=[]
    for file in (path.parents[2]/'data/batches').glob('*/manifest.json'):
        try: manifest=json.loads(file.read_text(encoding='utf-8'))
        except (OSError,ValueError): continue
        actual=manifest.get('settings',{}).get('experiment')
        if actual and actual.get('id')==definition['id']:
            if actual!=definition: raise ValueError('比較來源與凍結計畫不符')
            matches.append(file.parent)
    if len(matches)>1: raise ValueError('同一計畫有重複批次，請由紀錄選取確認')
    return matches[0] if matches else None


def comparison_options(path, baseline):
    path=Path(path); definition=load_comparison_plan(path)['definitions'][baseline]
    batch=comparison_batch(path,baseline)
    return resume_options(batch) if batch else ExperimentDefinition(json.dumps(definition)).options(path.parents[2]/'data/batches')


def comparison_report(path):
    """以已驗證的逐場提交建立各基準／候選／開局摘要；MAE 獨立保存。"""
    from engine.replay.comparison_catalog import load_comparison
    from engine.sessions.evaluation_comparison import comparison_progress
    plan=load_comparison_plan(path)
    report=dict(plan=plan,baselines={},limitation='有限共同開局觀察；教師誤差與對戰結果分開，不保證棋力提升。')
    for baseline,definition in plan['definitions'].items():
        batch=comparison_batch(path,baseline)
        raw={}; summary=None; manifest={}
        if batch:
            summary=load_comparison(batch/'manifest.json')
            manifest=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
            raw=json.loads((batch/'comparison.json').read_text(encoding='utf-8'))
        rows=[]
        for index,item in enumerate(definition['candidates']):
            role=item['role']; openings=[]
            for position,line in enumerate(definition['opening_lines'],1):
                pairs=[p for p in raw.get('pairs',[]) if p.get('candidate_index',0)==index and p['position_index']==position]
                games=[g for p in pairs for g in p['games'] if g['termination']!='user_stop']
                counts={key:sum(g['candidate_outcome']==outcome for g in games) for key,outcome in
                    [('wins','win'),('draws','draw'),('losses','loss'),('unfinished','unfinished')]}
                progress=comparison_progress(pairs)
                identities={work_id(definition,index,position,white) for white in (False,True)}
                historical=[g for p in raw.get('historical_attempts',[]) for g in p['games'] if g.get('work_id') in identities]
                historical += [g for p in pairs for g in p['games'] if g['termination']=='user_stop']
                openings.append(dict(position_index=position,line=line,**counts,planned_games=2,pending_games=2-len(games),
                    completed_pairs=progress['completed_pairs'],incomplete_pairs=1-progress['completed_pairs'],
                    interrupted_attempts=len(historical),elapsed_seconds=sum(g['elapsed_seconds'] for g in games+historical)))
            total={key:sum(o[key] for o in openings) for key in ('wins','draws','losses','unfinished','planned_games','pending_games','completed_pairs','incomplete_pairs','interrupted_attempts','elapsed_seconds')}
            teacher_role=role if role in plan['source']['report'].get('validation',{}) else 'learned'
            teacher={split:deepcopy(plan['source']['report'].get(split,{}).get(teacher_role)) for split in ('validation','test')}
            rows.append(dict(id=item['id'],role=role,label=item['label'],config=item['config'],teacher=teacher,openings=openings,**total))
        settings=manifest.get('settings',{})
        report['baselines'][baseline]=dict(status=summary.status if summary else 'not-started',path=batch,candidates=rows,
            requested_workers=settings.get('requested_workers',definition['workers']),actual_workers=settings.get('workers'),
            elapsed_seconds=summary.experiment_elapsed_seconds if summary else 0,
            replays=[g.path for g in summary.games if g.path] if summary else [],settings=definition)
    return report
