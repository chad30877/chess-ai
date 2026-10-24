"""可重現的非負位置權重學習與逐候選保存。"""
from collections import defaultdict
from copy import deepcopy
import json
import math
import multiprocessing
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from uuid import uuid4

import chess
from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.learning.labeling import load_labeled_dataset
from engine.learning.teacher import digest
from engine.sessions.experiment_resume import experiment_lock
from engine.storage.batch_storage import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
STAGES = ('opening', 'middlegame', 'endgame')


def training_rules():
    """在開始前凍結工程參數；測試分數不參與規則調整。"""
    import numpy, scipy
    return dict(version=1, strengths=[['weak', .001], ['medium', .01], ['strong', .1]],
        zero_scale=.1, solver='scipy.optimize.lsq_linear', method='bvls', lsq_solver='exact', tolerance=1e-10,
        objective='game-equal-squared-plus-standardized-origin-l2-v1',
        max_iter=1000, numpy=numpy.__version__, scipy=scipy.__version__,
        denominator_floor=1e-12, subset_relative_limit=.5,
        diagnostic='sorted-game-id-alternating-halves-v1', tie_tolerance=1e-12,
        selection_order=['strong','medium','weak'], max_seconds=28800)


def _weights(rows):
    counts=defaultdict(int)
    for row in rows: counts[row['game_id']]+=1
    return [1/(len(counts)*counts[row['game_id']]) for row in rows]


def calibrate(rows, stable, rules, check=lambda:None):
    """只傳入訓練組；教師原始 cp 映到固定 stable 的兵單位。"""
    evaluator=HandcraftedEvaluator(config=stable)
    def fit(samples):
        q=_weights(samples)
        values=[]
        for r in samples:
            check()
            values.append((r['label']['white_cp'],evaluator.evaluate(chess.Board(r['fen']))))
        denominator=sum(w*t*t for w,(t,s) in zip(q,values))
        if denominator<=rules['denominator_floor'] or not math.isfinite(denominator):
            raise ValueError('無法校準：教師分數分母為零或非有限')
        scale=sum(w*t*s for w,(t,s) in zip(q,values))/denominator
        if not math.isfinite(scale) or scale<=0: raise ValueError('無法校準：倍率非正或非有限')
        residuals=[(scale*t-s,w) for w,(t,s) in zip(q,values)]
        return dict(scale=scale,denominator=denominator,games=len({r['game_id'] for r in samples}),
            positions=len(samples),mae=sum(abs(r)*w for r,w in residuals),
            rmse=math.sqrt(sum(r*r*w for r,w in residuals)))
    result=fit(rows)
    games=sorted({r['game_id'] for r in rows})
    subsets=[]
    try:
        for ids in (set(games[::2]),set(games[1::2])):
            subsets.append(fit([r for r in rows if r['game_id'] in ids]))
        deviation=max(abs(s['scale']/result['scale']-1) for s in subsets)
        result.update(healthy=deviation<=rules['subset_relative_limit'],relative_deviation=deviation,
                      warning='' if deviation<=rules['subset_relative_limit'] else '校準子集倍率不穩定；不作可靠排名')
    except ValueError as exc:
        result.update(healthy=False,relative_deviation=None,warning=f'校準子集不足或退化：{exc}')
    result['subsets']=subsets
    return result


def extract_features(board, config, terms):
    """端點原始特徵先乘階段比例；零權重仍能保留非零特徵。"""
    detail=HandcraftedEvaluator(config=config).evaluate_breakdown(board)
    if not config.phase_enabled: raise ValueError('學習必須使用分階段設定')
    phase=detail.phase['middlegame']
    features,weights=[],[]
    for name in terms:
        for stage,factor in (('middlegame',phase),('endgame',1-phase)):
            term=detail.stage_terms[stage][name]
            if not term.enabled: raise ValueError('只能學習已啟用群組')
            features.append(factor*term.raw_value); weights.append(term.weight)
    return detail.terms['material'].contribution,features,weights


def evaluate_errors(rows, config, scale, check=lambda:None):
    evaluator=HandcraftedEvaluator(config=config)
    groups=defaultdict(list); stages={s:defaultdict(list) for s in STAGES}
    for row in rows:
        check()
        error=abs(evaluator.evaluate(chess.Board(row['fen']))-scale*row['label']['white_cp'])
        groups[row['game_id']].append(error); stages[row['stage']][row['game_id']].append(error)
    def average(group):
        return dict(mae=sum(sum(v)/len(v) for v in group.values())/len(group) if group else None,
                    games=len(group),positions=sum(map(len,group.values())))
    return dict(**average(groups),stages={s:average(g) for s,g in stages.items()})


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def create_training(label_path, *, run_path=None):
    """固定資料、原始權重及所有規則後建立棋子位置學習實驗。"""
    labeled=load_labeled_dataset(label_path)
    rules=training_rules()
    original=_read(ROOT/'configs/evaluation/learning-piece-square.json')
    stable=_read(ROOT/'configs/evaluation/stable.json')
    test_identity=digest([labeled['snapshot']['dataset_sha256'],sorted(r['position_id'] for r in labeled['positions'] if r['split']=='test')])
    prior=[]
    for entry in (Path(label_path)/'training').glob('*/snapshot.json'):
        earlier=_read(entry)
        if (entry.parent/'report.json').exists() and earlier.get('dataset_identity')==labeled['snapshot']['dataset_sha256']:
            prior.append(dict(experiment_id=earlier['id'],snapshot_identity=earlier['identity'],label_identity=earlier['label_identity']))
    path=Path(run_path) if run_path else Path(label_path)/'training'/uuid4().hex
    if path.exists(): raise ValueError('學習條件不可變；請建立新實驗')
    path.mkdir(parents=True)
    inputs=dict(label_snapshot=labeled['snapshot'],positions=labeled['positions'],dataset_sha256=labeled['snapshot']['dataset_sha256'])
    snapshot=dict(format_version=1,id=path.name,label_path=str(Path(label_path).resolve()),
        inputs_sha256=digest(inputs),rules=rules,stable=stable,original=original,
        groups=['piece-square'],terms=['piece_square'],kind='single',
        column_order=['piece_square:middlegame','piece_square:endgame'],
        original_weights=[original['terms']['piece_square']['weight'],original['terms']['piece_square']['endgame_weight']],
        scales=[original['terms']['piece_square']['weight'] or rules['zero_scale'],original['terms']['piece_square']['endgame_weight'] or rules['zero_scale']],
        dataset_identity=labeled['snapshot']['dataset_sha256'],label_identity=labeled['snapshot']['identity'],
        test_data_identity=test_identity,prior_test_experiments=prior,
        data_use='沿用教師標記資料；本實驗驗證選擇後首次凍結測試。其他實驗可能已使用同一測試資料。')
    snapshot['identity']=digest(snapshot)
    write_json_atomic(path/'inputs.json',inputs)
    write_json_atomic(path/'snapshot.json',snapshot)
    (path/'candidates').mkdir()
    write_json_atomic(path/'status.json',dict(status='ready',elapsed_seconds=0,error=''))
    return path


def load_training(path):
    """已提交候選與測試報告是事實來源；讀取不重新評估測試。"""
    path=Path(path); snapshot=_read(path/'snapshot.json')
    identity=dict(snapshot); identity.pop('identity',None)
    if snapshot.get('format_version')!=1 or digest(identity)!=snapshot['identity']:
        raise ValueError('學習快照身份或版本不符')
    candidates={}
    for file in (path/'candidates').glob('*.json'):
        record=_read(file)
        content=dict(record); content.pop('identity',None)
        if record.get('snapshot_identity')!=snapshot['identity'] or record.get('strength')!=file.stem:
            raise ValueError('學習候選身份不符')
        if record.get('identity')!=digest(content): raise ValueError('已提交學習候選內容已變更')
        EvaluationConfig.from_dict(record['config'])
        candidates[file.stem]=record
    state=_read(path/'status.json')
    for name in ('calibration','frozen','report'):
        state[name]=_read(path/f'{name}.json') if (path/f'{name}.json').exists() else None
    if state['calibration'] and state['calibration'].get('snapshot_identity')!=snapshot['identity']:
        raise ValueError('校準參照身份不符')
    if state['frozen'] and state['frozen'].get('snapshot_identity')!=snapshot['identity']:
        raise ValueError('凍結候選身份不符')
    if state['frozen']:
        source=candidates.get(state['frozen']['strength'])
        if source is None or source['config']!=state['frozen']['config'] or source['validation']!=state['frozen']['validation']:
            raise ValueError('凍結結果與已提交候選不同')
    if state['report']:
        if not state['frozen'] or state['report']['frozen_identity']!=digest(state['frozen']):
            raise ValueError('測試報告與凍結候選不符')
        state['status']='completed'
    elif state['status'] in ('running','completed'):
        state['status']='interrupted'
    state.update(path=str(path),snapshot=snapshot,candidates=candidates,completed=len(candidates),total=len(snapshot['rules']['strengths']))
    return state


def _solve_worker(connection, features, targets, weights, original, scales, strength, rules):
    try:
        import numpy as np
        from scipy.optimize import lsq_linear
        q=np.sqrt(np.asarray(weights))
        penalty=np.diag(np.sqrt(strength)/np.asarray(scales))
        a=np.vstack((np.asarray(features)*q[:,None],penalty))
        b=np.concatenate((np.asarray(targets)*q,penalty@np.asarray(original)))
        result=lsq_linear(a,b,bounds=(0,np.inf),method=rules['method'],lsq_solver=rules['lsq_solver'],
            tol=rules['tolerance'],max_iter=rules['max_iter'])
        if not result.success or not np.isfinite(result.x).all() or (result.x<0).any():
            raise ValueError('求解未收斂或產生非法權重：'+str(result.message))
        connection.send(dict(weights=result.x.tolist(),optimality=float(result.optimality),iterations=int(result.nit),error=''))
    except BaseException as exc:
        connection.send(dict(error=str(exc)))
    finally:
        connection.close()


class TrainingStopped(Exception):
    pass


def fit_position_weights(rows, config, terms, scale, strength, rules, *, check=lambda:None, started=lambda pid:None):
    """以真實局面學習並回傳完整合法設定；只調所選端點權重。"""
    if not rows: raise ValueError('訓練組沒有有效資料')
    features=[]; targets=[]; original=[]
    for row in rows:
        check()
        bias,feature,original=extract_features(chess.Board(row['fen']),config,terms)
        features.append(feature); targets.append(scale*row['label']['white_cp']-bias)
    snapshot=dict(original_weights=original,scales=[abs(w) or rules['zero_scale'] for w in original],rules=rules)
    solved=_solve(features,targets,_weights(rows),snapshot,strength,check,started)
    payload=config.to_dict()
    for index,term in enumerate(terms):
        payload['terms'][term]['weight'],payload['terms'][term]['endgame_weight']=solved['weights'][index*2:index*2+2]
    return EvaluationConfig.from_dict(payload),solved


def _solve(features,targets,weights,snapshot,strength,check,started):
    context=multiprocessing.get_context('spawn')
    receive,send=context.Pipe(duplex=False)
    process=context.Process(target=_solve_worker,args=(send,features,targets,weights,
        snapshot['original_weights'],snapshot['scales'],strength,snapshot['rules']))
    try:
        check(); process.start(); send.close(); started(process.pid)
        while True:
            check()
            if receive.poll(.02):
                try: result=receive.recv()
                except EOFError as exc: raise ValueError('求解程序異常退出') from exc
                check()
                if result['error']: raise ValueError(result['error'])
                return result
            if not process.is_alive(): raise ValueError('求解程序異常退出')
    finally:
        if process.pid:
            if process.is_alive(): process.terminate()
            process.join(timeout=2)
            if process.is_alive(): process.kill(); process.join(timeout=2)
        receive.close(); send.close()


def run_training(path, *, stop=None, progress=lambda state:None, now=monotonic, started_at=None):
    """一次共用八小時；只重跑未完成候選，測試只針對已凍結設定。"""
    path=Path(path)
    with experiment_lock(path):
        saved=load_training(path)
        if saved['report']: return path
        snapshot=saved['snapshot']; rules=snapshot['rules']; began=now() if started_at is None else started_at
        state=dict(status='running',elapsed_seconds=0,error='',completed=saved['completed'],total=saved['total'],current_candidate='',worker_pid=None)
        def report(**updates):
            state.update(updates,elapsed_seconds=now()-began)
            write_json_atomic(path/'status.json',state)
            progress(deepcopy(state))
        def check():
            if stop is not None and stop.is_set(): raise TrainingStopped('使用者停止；未完成候選可手動續跑')
            if now()-began>=rules['max_seconds']: raise TrainingStopped('已達八小時上限；未完成候選可手動續跑')
        try:
            report(); check()
            current=training_rules()
            if any(rules[k]!=current[k] for k in ('numpy','scipy','version')):
                raise ValueError('數值程式版本與凍結快照不同；請建立新實驗')
            inputs=_read(path/'inputs.json'); check()
            if digest(inputs)!=snapshot['inputs_sha256']: raise ValueError('訓練資料身份不符')
            rows={split:[r for r in inputs['positions'] if r['split']==split] for split in ('train','validation','test')}
            if not rows['train']: raise ValueError('訓練組沒有有效資料')
            stable=EvaluationConfig.from_dict(snapshot['stable']); original=EvaluationConfig.from_dict(snapshot['original'])
            calibration=saved['calibration']
            if calibration is None:
                calibration=calibrate(rows['train'],stable,rules,check); check()
                calibration['reference']=snapshot['stable']; calibration['snapshot_identity']=snapshot['identity']
                write_json_atomic(path/'calibration.json',calibration)
            scale=calibration['scale']; check()
            candidates=saved['candidates']
            if saved['frozen'] is None:
                for name,strength in rules['strengths']:
                    check()
                    if name in candidates: continue
                    report(current_candidate=name,worker_pid=None)
                    config,solved=fit_position_weights(rows['train'],original,snapshot['terms'],scale,strength,rules,
                        check=check,started=lambda pid:report(worker_pid=pid))
                    validation=evaluate_errors(rows['validation'],config,scale,check)
                    record=dict(strength=name,penalty=strength,config=config.to_dict(),validation=validation,
                        solver=solved,snapshot_identity=snapshot['identity'])
                    record['identity']=digest(record)
                    check(); write_json_atomic(path/'candidates'/f'{name}.json',record)
                    candidates[name]=record
                    report(completed=len(candidates),worker_pid=None)
                check()
                eligible=[candidates[name] for name in rules['selection_order'] if candidates[name]['validation']['mae'] is not None]
                if not eligible: raise ValueError('驗證組無資料，無法選定或宣告完成獨立評估')
                best=eligible[0]
                for item in eligible[1:]:
                    if item['validation']['mae']<best['validation']['mae']-rules['tie_tolerance']: best=item
                frozen=dict(strength=best['strength'],config=best['config'],validation=best['validation'],
                    snapshot_identity=snapshot['identity'],selection_order=rules['selection_order'])
                check(); write_json_atomic(path/'frozen.json',frozen)
            else: frozen=saved['frozen']
            material_payload=deepcopy(snapshot['original'])
            for term,settings in material_payload['terms'].items(): settings['enabled']=term=='material'
            configs=dict(material=EvaluationConfig.from_dict(material_payload),original=original,
                learned=EvaluationConfig.from_dict(frozen['config']),stable=stable)
            report(current_candidate='frozen-test',worker_pid=None)
            metrics={split:{name:evaluate_errors(rows[split],config,scale,check) for name,config in configs.items()}
                     for split in ('validation','test')}
            improvement=all(metrics[s]['original']['mae'] is not None and metrics[s]['learned']['mae'] is not None and
                metrics[s]['learned']['mae']<metrics[s]['original']['mae'] for s in ('validation','test'))
            final=dict(frozen_identity=digest(frozen),**metrics,reliable_ranking=calibration['healthy'],
                       priority_battle_observation=calibration['healthy'] and improvement,data_use=snapshot['data_use'])
            check(); write_json_atomic(path/'report.json',final)
            report(status='completed',current_candidate='',worker_pid=None)
        except TrainingStopped as exc:
            report(status='stopped',error=str(exc),worker_pid=None)
        except Exception as exc:
            report(status='failed',error=str(exc),worker_pid=None)
    return path


def save_training_config(path, destination):
    saved=load_training(path)
    if not saved['frozen']: raise ValueError('尚未凍結可另存的候選')
    config=EvaluationConfig.from_dict(saved['frozen']['config'])
    destination=Path(destination)
    if destination.exists(): raise ValueError('目標已存在；請使用新檔名')
    destination.parent.mkdir(parents=True,exist_ok=True)
    write_json_atomic(destination,config.to_dict())
    return destination


class TrainingRun:
    def __init__(self,path,executor,*,label_path=None,**options):
        self.path=Path(path); self._stop=Event(); self._lock=Lock(); self.label_path=label_path
        if label_path is None:
            saved=load_training(path)
            self._state={key:saved[key] for key in ('status','completed','total','elapsed_seconds','error')}
        else:
            self._state=dict(status='queued',completed=0,total=3,elapsed_seconds=0,error='')
        self.future=executor.submit(self._work,options)
    def _work(self,options):
        try:
            began=options.get('now',monotonic)()
            if self.label_path is not None:
                create_training(self.label_path,run_path=self.path)
            return run_training(self.path,stop=self._stop,progress=self._progress,started_at=began,**options)
        except Exception as exc: self._progress(dict(status='failed',error=str(exc)))
    def _progress(self,state):
        with self._lock: self._state.update(state)
    def snapshot(self):
        with self._lock: return deepcopy(self._state)
    def stop(self): self._stop.set()
