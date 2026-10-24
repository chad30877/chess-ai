"""自選群組的實際權重預覽、固定對照及聯合結果。"""
import json
from pathlib import Path
from uuid import uuid4
from engine.evaluation.config import EvaluationConfig
from engine.learning.group_training import GROUPS, load_group_training, load_group_candidate
from engine.learning.combination_training import (CombinationRun, preview_combination, load_combination,
    load_combination_candidate, save_combination_config)
from ui.replay_evaluation_editor import TERM_LABELS


def _number(value): return f'{value:.4f}' if value is not None else '無資料'


class CombinationView:
    def __init__(self, root):
        self.root = Path(root); self.source_path = self.path = self.run = self._loaded_run = None
        self.selected = {'mobility','king-safety'}; self.sources = {}; self.preview = {}; self.state = {}
        self.entries = []; self.index = self.stage = self.weight_page = 0
        self.kind = 'direct'; self.weights = self.advanced = False; self.saved = None; self.message = ''
    def active(self): return self.run is not None and not self.run.future.done()
    def selection_changed(self):
        return bool(self.state.get('snapshot')) and self.selected != set(self.state['snapshot']['groups'])
    def open(self, source_path):
        self.source_path = Path(source_path)
        groups = load_group_training(source_path)
        self.sources = {g:load_group_candidate(source_path,g) for g,r in groups['groups'].items() if r['report']}
        self.selected = {'mobility','king-safety'}; self.path = self.run = self._loaded_run = None
        self.state = {}; self.index = 0; self.saved = None; self.message = ''; self.update_preview()
        self.entries = []
        for entry in sorted((self.source_path.parents[1]/'combinations').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            snapshot = json.loads(entry.read_text(encoding='utf-8'))
            if snapshot['sources'][0]['snapshot_identity'] == groups['snapshot']['identity']: self.entries.append(entry)
        if self.entries: self.load(self.entries[0].parent)
    def update_preview(self):
        self.preview = {}; self.message = ''
        if not self.selected: self.message = '請選擇群組'; return
        missing = self.selected - self.sources.keys()
        if missing: self.message = '請先完成：'+'、'.join(GROUPS[g] for g in GROUPS if g in missing); return
        self.preview = preview_combination([self.sources[g] for g in GROUPS if g in self.selected])
    def load(self, path):
        self.path = Path(path); self.state = load_combination(path); self.saved = None
        self.selected = set(self.state['snapshot']['groups']); self.update_preview()
    def action(self, action, app):
        try:
            if action == 'learning_combination_stop' and self.active(): self.run.stop(); return
            if action.startswith('learning_combination_kind:'):
                self.kind = action.split(':')[1]; self.saved = None; self.weight_page = 0; return
            if action == 'learning_combination_weights': self.weights = not self.weights; return
            if action == 'learning_combination_weights_next': self.weight_page += 1; return
            if action == 'learning_combination_stage': self.stage = (self.stage+1)%4; return
            if action == 'learning_combination_advanced': self.advanced = not self.advanced; return
            if self.active(): return
            if action.startswith('learning_combination_toggle:'):
                group = action.split(':')[1]
                if group in self.selected: self.selected.remove(group)
                else: self.selected.add(group)
                self.update_preview(); self.weights = True; self.weight_page = 0
                if self.preview and self.selection_changed(): self.message = '選組已變更；預覽新組合，按新建套用'
            elif action == 'learning_combination_new' and self.preview:
                self.path = self.source_path.parents[1]/'combinations'/uuid4().hex
                self.state = {}; self.saved = None; self.message = ''
                self.run = CombinationRun(self.path,app.executor,source_path=self.source_path,groups=self.preview['groups'])
            elif action == 'learning_combination_resume' and self.path:
                self.run = CombinationRun(self.path,app.executor)
            elif action in ('learning_combination_prev','learning_combination_next'):
                self.index = (self.index+(1 if action.endswith('next') else -1))%len(self.entries)
                self.run = self._loaded_run = None; self.load(self.entries[self.index].parent)
            elif action in ('learning_combination_save','learning_combination_battle','learning_combination_compare'):
                if self.selection_changed(): raise ValueError('選組已變更；請先新建組合')
                candidate = load_combination_candidate(self.path,self.kind)
                if action == 'learning_combination_compare': app.learning.open_comparison(candidate); return
                target = self.root/'configs/evaluation'/f'learned-{self.path.name}-{self.kind}.json'
                if target.exists():
                    if EvaluationConfig.from_dict(json.loads(target.read_text(encoding='utf-8'))).to_dict() != candidate['config']:
                        raise ValueError('另存目標已變更；請使用新實驗')
                    self.saved = target
                else: self.saved = save_combination_config(self.path,self.kind,target)
                self.message = '已另存 '+self.saved.name
                if action == 'learning_combination_battle':
                    app.live_evaluation_file = self.saved
                    if self.saved not in app.live_evaluation_files: app.live_evaluation_files.append(self.saved)
                    app.new_setup('human')
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc: self.message = str(exc)
    def render(self, app):
        active = self.active()
        if self.run:
            if active: self.state.update(self.run.snapshot())
            elif self._loaded_run is not self.run:
                runtime = self.run.snapshot()
                try:
                    self.load(self.run.path)
                    entry = self.run.path/'snapshot.json'
                    if entry not in self.entries: self.entries.insert(0,entry)
                except (OSError,ValueError) as exc: self.state = runtime; self.message = str(exc)
                if runtime.get('status') == 'failed' and self.state.get('status') != 'completed': self.state.update(status='failed',error=runtime.get('error',''))
                self._loaded_run = self.run
        state = self.state; snapshot = state.get('snapshot',{}); results = state.get('results',{})
        result = results.get(self.kind,{}); report = result.get('report'); frozen = result.get('frozen')
        draft = self.selection_changed()
        app.text('學習實驗 · 自選群組組合',50,78,large=True)
        app.button('learning_groups','五個單群組',(50,120,190,34),enabled=not active)
        app.text(f'已保存 {min(self.index+1,len(self.entries))}/{len(self.entries)}',260,128,muted=True)
        app.button('learning_combination_prev','上一份',(540,120,140,32),enabled=len(self.entries)>1 and not active)
        app.button('learning_combination_next','下一份',(700,120,140,32),enabled=len(self.entries)>1 and not active)
        for i,(g,label) in enumerate(GROUPS.items()):
            app.button('learning_combination_toggle:'+g,('[x] ' if g in self.selected else '[ ] ')+label,(50+i*160,164,148,32),enabled=not active)
        app.button('learning_combination_new','新建組合＋聯合三候選',(50,210,260,36),enabled=bool(self.preview) and not active,primary=True)
        app.button('learning_combination_resume','續跑／重試',(330,210,210,36),enabled=bool(self.path) and state.get('status')!='completed' and not active)
        app.button('learning_combination_stop','停止',(560,210,120,36),enabled=active)
        statuses = dict(ready='待開始',queued='準備中',running='執行中',completed='完成',stopped='已停止',failed='失敗',interrupted='待續跑')
        app.text(f'{statuses.get(state.get("status"),"權重預覽")} · 聯合候選 {state.get("completed",0)}/3 · {state.get("elapsed_seconds",0):.1f} 秒 · {state.get("current_candidate","")}',50,259,width=790)
        source_id = snapshot.get('sources',[next(iter(self.sources.values()),{})])[0].get('experiment_id','')
        app.text(f'來源 {source_id[:12]} · 沿用已曝光測試資料'+(f'（{len(snapshot["prior_test_experiments"])} 份）' if snapshot else ''),50,288,muted=True,width=790)
        cal = state.get('calibration') or next(iter(self.sources.values()),{}).get('calibration')
        if cal: app.text(f'共用倍率 {cal["scale"]:.7f} · '+('診斷正常' if cal['healthy'] else cal['warning']),50,316,width=790)
        if self.message or state.get('error'): app.text(self.message or state['error'],50,344,width=790)
        for i,(kind,label) in enumerate((('direct','直接組合'),('joint','聯合訓練'),('controls','固定四設定'))):
            app.button('learning_combination_kind:'+kind,('> ' if self.kind==kind else '')+label,(50+i*225,380,210,32))
        app.button('learning_combination_stage',['全部','開局','中局','殘局'][self.stage],(735,380,105,32))
        app.button('learning_combination_weights','誤差結果' if self.weights else '實際權重／開關',(50,422,230,30))
        app.button('learning_combination_advanced','進階條件',(620,422,220,30))
        stage = [None,'opening','middlegame','endgame'][self.stage]
        def metric(value): return value['stages'][stage] if stage else value
        if self.advanced:
            rules = snapshot.get('rules') or next(iter(self.sources.values()),{}).get('rules',{})
            app.text('校準只沿用來源訓練組；聯合懲罰中心固定為選中群組原始值。',50,467,width=790)
            if cal:
                app.text(f'訓練 {cal["games"]} 盤／{cal["positions"]} 局面 · 殘差 MAE {cal["mae"]:.4f} ／ RMSE {cal["rmse"]:.4f}',50,500,width=790)
                app.text(f'子集最大倍率偏差 {_number(cal["relative_deviation"])} ／ 門檻 {rules.get("subset_relative_limit",.5)}',50,533,width=790)
                app.text('校準身份 '+cal['identity'][:24],50,566,muted=True,width=790)
            app.text(f'NNLS bvls · 容差 {rules.get("tolerance")} · numpy {rules.get("numpy")} ／ scipy {rules.get("scipy")}',50,599,width=790)
            app.text('來源凍結：'+'、'.join(s['frozen_identity'][:12] for s in snapshot.get('sources',[])),50,632,muted=True,width=790)
        elif self.weights:
            show_saved = frozen and not draft
            payload = frozen['config'] if show_saved else self.preview.get('direct')
            original = snapshot.get('original') if show_saved else self.preview.get('original')
            terms = snapshot.get('terms',[]) if show_saved else self.preview.get('terms',[])
            if payload:
                pages = max(1,(len(terms)+3)//4); self.weight_page %= pages
                for i,name in enumerate(terms[self.weight_page*4:self.weight_page*4+4]):
                    before,after = original['terms'][name],payload['terms'][name]
                    app.text(f'{TERM_LABELS.get(name,name)} · 中 {before["weight"]:.4f} → {after["weight"]:.4f} ／ 殘 {before["endgame_weight"]:.4f} → {after["endgame_weight"]:.4f}',50,467+i*29,width=790)
                app.button('learning_combination_weights_next',f'權重 {self.weight_page+1}/{pages}',(620,594,220,30),enabled=pages>1)
                app.text('啟用：子力＋'+'、'.join(GROUPS[g] for g in (snapshot.get('groups',[]) if show_saved else self.preview['groups'])),50,630,muted=True,width=790)
        elif self.kind == 'controls':
            controls = state.get('controls')
            if controls:
                for i,(key,label) in enumerate((('material','純子力'),('mobility','加活動力'),('king-safety','加王安全'),('both','兩者皆加'))):
                    val,test = (metric(controls[s]['metrics'][key]) for s in ('validation','test'))
                    app.text(f'{label}　驗 {_number(val["mae"])}　測 {_number(test["mae"])} · 盤/局面 {val["games"]}/{val["positions"]} · {test["games"]}/{test["positions"]}',50,467+i*29,width=790)
                for i,(key,label) in enumerate((('without_mobility','子力背景'),('with_mobility','活動力背景'))):
                    delta = [controls[s]['king_increments'][key] for s in ('validation','test')]
                    values = [d['stages'][stage] if stage else d['mae'] for d in delta]
                    app.text(f'加入王安全 Δ · {label}　驗 {_number(values[0])} ／ 測 {_number(values[1])}',50,592+i*29,width=790)
            else: app.text('固定四設定需同時選取活動力與王安全，並完成直接組合。',50,468,width=790)
        elif report:
            for i,(key,label) in enumerate((('material','純子力'),('original','同組原始'),('learned','直接組合' if self.kind=='direct' else '聯合學習'),('stable','stable'))):
                val,test = (metric(report[s][key]) for s in ('validation','test'))
                app.text(f'{label}　驗 {_number(val["mae"])}　測 {_number(test["mae"])} · 盤/局面 {val["games"]}/{val["positions"]} · {test["games"]}/{test["positions"]}',50,467+i*29,width=790)
            app.text('優先對戰觀察' if report['priority_battle_observation'] else '保留完整結果；未標示優先對戰觀察',50,594,muted=True,width=790)
            if self.kind == 'joint':
                candidates = state.get('candidates',{})
                app.text('驗證選定 '+frozen['strength']+' · '+' / '.join(n+' '+_number(c['validation']['mae']) for n,c in candidates.items()),50,625,muted=True,width=790)
        else: app.text('原始權重作聯合懲罰中心；直接組合保留單組學習權重。',50,468,width=790)
        if self.advanced:
            app.text('整次八小時 · λ .001/.01/.1 · 非負 · 加法特徵 · 不以測試選參數',50,665,muted=True,width=790)
        else: app.text('逐盤 MAE；負增量代表誤差改善，教師誤差不代表棋力。',50,665,muted=True,width=790)
        app.button('learning_combination_save','另存完整設定',(50,708,250,34),enabled=bool(report) and not active and not draft)
        app.button('learning_combination_battle','載入真人對戰',(320,708,250,34),enabled=bool(report) and not active and not draft)
        app.button('learning_combination_compare','共同開局比較',(590,708,250,34),enabled=bool(report) and not active and not draft and hasattr(app.learning,'open_comparison'))
