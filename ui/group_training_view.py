"""五個獨立群組的共用預算、誤差比較與完整設定另存。"""
from pathlib import Path
from uuid import uuid4
import json
from engine.evaluation.config import EvaluationConfig
from ui.replay_evaluation_editor import TERM_LABELS
from engine.learning.group_training import GROUPS, GroupTrainingRun, load_group_training, save_group_config, load_group_candidate


def _number(value): return f'{value:.4f}' if value is not None else '無資料'


class GroupTrainingView:
    def __init__(self, root):
        self.root = Path(root); self.labels = self.path = self.run = self._loaded_run = None
        self.state = {}; self.entries = []; self.index = 0; self.message = ''; self.saved = None
        self.selected = set(GROUPS); self.group = next(iter(GROUPS)); self.stage = 0
        self.detail = self.advanced = False; self.weight_page = 0
    def active(self): return self.run is not None and not self.run.future.done()
    def open(self, labels):
        self.labels = Path(labels); self.path = self.run = self._loaded_run = None
        self.state = {}; self.message = ''; self.saved = None; self.index = 0
        self.entries = sorted((self.labels/'group-training').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        if self.entries: self.load(self.entries[0].parent)
    def load(self, path):
        self.path = Path(path); self.state = load_group_training(path); self.saved = None
        if self.group not in self.state['groups']: self.group = next(iter(self.state['groups']))
    def action(self, action, app):
        try:
            if action == 'learning_groups_compare' and not self.active():
                app.learning.open_comparison(load_group_candidate(self.path,self.group)); return
            if action == 'learning_groups_stop' and self.active(): self.run.stop(); return
            if action.startswith('learning_groups_select:'):
                self.group = action.split(':')[1]; self.saved = None; self.weight_page = 0; return
            if action == 'learning_groups_detail': self.detail = not self.detail; return
            if action == 'learning_groups_advanced': self.advanced = not self.advanced; return
            if action == 'learning_groups_stage': self.stage = (self.stage+1)%4; return
            if action == 'learning_groups_weights_next': self.weight_page += 1; return
            if self.active(): return
            if action.startswith('learning_groups_toggle:'):
                group = action.split(':')[1]
                if group in self.selected: self.selected.remove(group)
                else: self.selected.add(group)
            elif action == 'learning_groups_new':
                groups = [g for g in GROUPS if g in self.selected]
                if not groups: raise ValueError('請至少選擇一組')
                self.path = self.labels/'group-training'/uuid4().hex
                self.state = {}; self.saved = None; self.message = ''; self.index = 0
                self.run = GroupTrainingRun(self.path,app.executor,label_path=self.labels,groups=groups)
            elif action == 'learning_groups_resume' and self.path:
                self.run = GroupTrainingRun(self.path,app.executor); self.message = ''
            elif action in ('learning_groups_prev','learning_groups_next'):
                self.index = (self.index+(1 if action.endswith('next') else -1))%len(self.entries)
                self.run = self._loaded_run = None; self.load(self.entries[self.index].parent)
            elif action in ('learning_groups_save','learning_groups_battle'):
                target = self.root/'configs/evaluation'/f'learned-{self.path.name}-{self.group}.json'
                if self.saved is None:
                    if target.exists():
                        existing = EvaluationConfig.from_dict(json.loads(target.read_text(encoding='utf-8')))
                        if existing.to_dict() != self.state['groups'][self.group]['frozen']['config']: raise ValueError('另存目標已變更；請使用新實驗')
                        self.saved = target
                    else: self.saved = save_group_config(self.path,self.group,target)
                self.message = '已另存 '+self.saved.name
                if action == 'learning_groups_battle':
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
                if runtime.get('status') == 'failed' and self.state.get('status') != 'completed':
                    self.state.update(status='failed',error=runtime.get('error',''))
                self._loaded_run = self.run
        s = self.state; groups = s.get('groups',{}); snapshot = s.get('snapshot',{})
        app.text('學習實驗 · 五個單群組',50,78,large=True)
        app.button('learning_labels','教師標記',(50,120,190,34),enabled=not active)
        app.text(f'已保存 {min(self.index+1,len(self.entries))}/{len(self.entries)}',260,128,muted=True)
        app.button('learning_groups_prev','上一份',(540,120,140,32),enabled=len(self.entries)>1 and not active)
        app.button('learning_groups_next','下一份',(700,120,140,32),enabled=len(self.entries)>1 and not active)
        for index,(group,label) in enumerate(GROUPS.items()):
            app.button('learning_groups_toggle:'+group,('[x] ' if group in self.selected else '[ ] ')+label,
                       (50+index*160,164,148,32),enabled=not active)
        app.button('learning_groups_new','新建並學習',(50,210,230,36),enabled=bool(self.selected) and not active,primary=True)
        app.button('learning_groups_resume','續跑／重試',(300,210,230,36),enabled=bool(self.path) and s.get('status')!='completed' and not active)
        app.button('learning_groups_stop','停止',(550,210,130,36),enabled=active)
        app.button('learning_combinations','組合',(700,210,140,36),enabled=bool(s.get('completed_groups')) and not active)
        statuses = {'ready':'待開始','queued':'準備中','running':'訓練中','completed':'完成','stopped':'已停止','failed':'失敗','partial':'部分失敗','interrupted':'待續跑','incomplete':'未完成'}
        if s:
            app.text(f'{statuses.get(s["status"],s["status"])} · 候選 {s["completed"]}/{s["total"]} · 完成 {s["completed_groups"]} 組 · 失敗 {s["failed_groups"]} 組 · {s.get("elapsed_seconds",0):.1f} 秒',50,263,width=790)
        cal = s.get('calibration')
        if cal: app.text(f'共用倍率 {cal["scale"]:.7f} · '+('診斷正常' if cal['healthy'] else '診斷異常，不作可靠排名'),50,293,width=790)
        elif active: app.text(GROUPS.get(s.get('current_group'),'準備資料／共用校準')+' · '+s.get('current_candidate',''),50,293,muted=True,width=790)
        if self.message or s.get('error'): app.text(self.message or s['error'],50,322,width=790)
        app.button('learning_groups_stage',['全部階段','開局','中局','殘局'][self.stage],(50,356,190,30))
        app.button('learning_groups_detail','結果總覽' if self.detail else '選中群組權重',(260,356,250,30),enabled=bool(groups))
        app.button('learning_groups_advanced','進階條件',(620,356,220,30))
        stage = [None,'opening','middlegame','endgame'][self.stage]
        current = groups.get(self.group,{})
        report = current.get('report')
        def metric(split,name):
            value = report[split][name]
            return value['stages'][stage] if stage else value
        if self.detail and current:
            app.text(GROUPS[self.group]+' · 中局／殘局：原始 → 學習',50,402,width=790)
            definition = snapshot['definitions'][self.group]
            frozen = current.get('frozen')
            if frozen:
                terms = definition['terms']; pages = max(1,(len(terms)+3)//4); self.weight_page %= pages
                for index,name in enumerate(terms[self.weight_page*4:self.weight_page*4+4]):
                    original = definition['original']['terms'][name]; learned = frozen['config']['terms'][name]
                    app.text(f'{TERM_LABELS.get(name,name)}　{original["weight"]:.4f} → {learned["weight"]:.4f} ／ {original["endgame_weight"]:.4f} → {learned["endgame_weight"]:.4f}',50,438+index*30,width=790)
                app.button('learning_groups_weights_next',f'權重 {self.weight_page+1}/{pages}',(620,400,220,30),enabled=pages>1)
            else: app.text('尚無凍結設定 · '+ '；'.join(current.get('errors',{}).values()),50,440,width=790)
        else:
            for index,(group,label) in enumerate(GROUPS.items()):
                result = groups.get(group,{})
                status = result.get('status','incomplete')
                if active: status = s.get('group_states',{}).get(group,status)
                text = label+' · '+statuses.get(status,status)
                r = result.get('report')
                if r:
                    values=[]
                    for split in ('validation','test'):
                        values.append('/'.join(_number((r[split][name]['stages'][stage] if stage else r[split][name])['mae']) for name in ('original','learned')))
                    text += '　驗 '+values[0]+'　測 '+values[1]
                    if r['priority_battle_observation']: text += ' · 優先觀察'
                if group == self.group: text = '> '+text
                app.button('learning_groups_select:'+group,text,(50,400+index*33,790,30),enabled=bool(result))
        if report:
            val,test = metric('validation','learned'),metric('test','learned')
            app.text(f'有效盤／局面 驗 {val["games"]}/{val["positions"]} · 測 {test["games"]}/{test["positions"]} · 純子力 {_number(metric("validation","material")["mae"])}/{_number(metric("test","material")["mae"])} · stable {_number(metric("validation","stable")["mae"])}/{_number(metric("test","stable")["mae"])}',50,574,width=790)
            for index,(name,label) in enumerate((('original','原始'),('learned','學習'))):
                deltas=[]
                for baseline in ('material','stable'):
                    values=[]
                    for split in ('validation','test'):
                        value=report['deltas'][split][name][baseline]
                        values.append(_number(value['stages'][stage] if stage else value['mae']))
                    deltas.append(('子力' if baseline=='material' else 'stable')+' '+ '/'.join(values))
                app.text(label+' Δ驗／測：'+' · '.join(deltas),50,607+index*28,muted=True,width=790)
        if self.advanced and snapshot:
            app.text(f'同次共用八小時 · λ .001/.01/.1 · 沿用 {len(snapshot["prior_test_experiments"])} 份已曝光測試來源',50,667,muted=True,width=790)
        else: app.text('逐盤 MAE；原始／學習並列，負差值代表誤差較小，不代表棋力。',50,667,muted=True,width=790)
        app.button('learning_groups_save','另存選中完整設定',(50,708,290,34),enabled=bool(report) and not active)
        app.button('learning_groups_battle','載入真人對戰',(360,708,260,34),enabled=bool(report) and not active)
        app.button('learning_groups_compare','共同開局比較',(640,708,200,34),enabled=bool(report) and not active)
