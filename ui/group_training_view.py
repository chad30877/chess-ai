"""五個獨立群組的共用預算、誤差比較與完整設定另存。"""
from pathlib import Path
from uuid import uuid4
import json
from engine.evaluation.config import EvaluationConfig
from engine.learning.comparison import load_comparison_plan, comparison_report
from ui.replay_evaluation_editor import TERM_LABELS
from engine.learning.group_training import GROUPS, GroupTrainingRun, load_group_training, save_group_config, load_group_candidate


def _number(value): return f'{value:.4f}' if value is not None else '無資料'


class GroupTrainingView:
    def __init__(self, root):
        self.root = Path(root); self.labels = self.path = self.run = self._loaded_run = None
        self.state = {}; self.entries = []; self.index = 0; self.message = ''; self.saved = None
        self.selected = set(GROUPS); self.group = next(iter(GROUPS)); self.stage = 0
        self.detail = self.advanced = False; self.weight_page = 0; self.load_error = False; self.draft = True
        self.compared = None; self.comparison_future = None
    def active(self): return self.run is not None and not self.run.future.done()
    def open(self, labels, preferred=None):
        self.labels = Path(labels); self.path = self.run = self._loaded_run = None
        self.state = {}; self.message = ''; self.saved = None; self.index = 0
        self.entries = sorted((self.labels/'group-training').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        chosen = Path(preferred) if preferred else (self.entries[0].parent if self.entries else None)
        self.draft = not bool(chosen)
        if chosen:
            self.index = next((i for i, e in enumerate(self.entries) if e.parent == chosen), 0)
            try: self.load(chosen)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.path = chosen; self.state = {}; self.load_error = True; self.message = f'無法讀取 {chosen}：{exc}'
    def load(self, path):
        self.path = Path(path); self.state = load_group_training(path); self.saved = None; self.load_error = False; self.draft = False
        if self.group not in self.state['groups']: self.group = next(iter(self.state['groups']))
        self.compared = None; self.comparison_future = None
    @staticmethod
    def comparison_evidence(root, identities):
        compared = set()
        for folder in ('learning-comparisons', 'learning-screening'):
            for file in (root/'data'/folder).glob('*/snapshot.json'):
                try:
                    plan = load_comparison_plan(file.parent)
                    group = identities.get(plan['source'].get('frozen_identity'))
                    if group:
                        report = comparison_report(file.parent)
                        if any(row['role'] == 'learned' and row['wins'] + row['draws'] + row['losses'] > 0
                               for baseline in report['baselines'].values() for row in baseline['candidates']):
                            compared.add(group)
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    continue
        return compared
    def action(self, action, app):
        try:
            if action == 'learning_groups_compare' and not self.active():
                app.learning.open_comparison(load_group_candidate(self.path,self.group), app.read_executor, 'group', self.path); return
            if action == 'learning_groups_stop' and self.active(): self.run.stop(); return
            if action.startswith('learning_groups_select:'):
                self.group = action.split(':')[1]; self.saved = None; self.weight_page = 0; return
            if action == 'learning_groups_draft' and not self.active():
                self.selected = set(GROUPS); self.draft = True; self.message = ''; return
            if action == 'learning_groups_draft_cancel': self.draft = False; return
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
                self.draft = False
            elif action == 'learning_groups_resume' and self.path and not self.load_error:
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
        if self.compared is None and not any(result.get('frozen') for result in groups.values()): self.compared = set()
        if self.compared is None and self.comparison_future is None and any(result.get('frozen') for result in groups.values()):
            identities = {result['frozen']['identity']: group for group, result in groups.items() if result.get('frozen')}
            self.comparison_future = app.read_executor.submit(self.comparison_evidence, self.root, identities)
        if self.comparison_future is not None and self.comparison_future.done():
            try: self.compared = self.comparison_future.result()
            except (OSError, ValueError, KeyError, TypeError, IndexError): self.compared = set()
            self.comparison_future = None
        app.text('學習實驗 · 單群組學習',50,78,large=True)
        app.button('learning_labels','教師標記',(50,120,190,34))
        app.button('learning_training','舊棋子位置成果',(260,120,250,32),enabled=bool(self.labels) and (self.labels/'training').is_dir() and not active)
        app.button('learning_groups_prev','上一份',(540,120,140,32),enabled=len(self.entries)>1 and not active)
        app.button('learning_groups_next','下一份',(700,120,140,32),enabled=len(self.entries)>1 and not active)
        if self.draft:
            for index,(group,label) in enumerate(GROUPS.items()):
                app.button('learning_groups_toggle:'+group,('[x] ' if group in self.selected else '[ ] ')+label,
                           (50+index*160,164,148,32),enabled=not active)
            app.button('learning_groups_new',f'開始學習 {len(self.selected)} 個群組',(50,210,230,36),enabled=bool(self.selected) and not active,primary=True)
            if self.path: app.button('learning_groups_draft_cancel','返回結果',(300,210,230,36),enabled=not active)
            if self.message: app.text(self.message,50,263,width=790)
            return
        else:
            app.button('learning_groups_draft','以此建立新訓練',(50,210,230,36),enabled=not active,primary=True)
        if not self.draft: app.button('learning_groups_resume','續跑原條件',(300,210,230,36),enabled=bool(self.path) and not self.load_error and s.get('status')!='completed' and not active)
        app.button('learning_groups_stop','停止',(550,210,130,36),enabled=active)
        app.button('learning_combinations','組合',(700,210,140,36),enabled=bool(s.get('completed_groups')))
        statuses = {'ready':'待開始','queued':'準備中','running':'訓練中','completed':'完成','stopped':'已停止','failed':'失敗','partial':'部分失敗','interrupted':'待續跑','incomplete':'未完成','not-selected':'未選取'}
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
                status = result.get('status','incomplete') if group in groups else 'not-selected'
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
        if report and self.detail:
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
        comparison = '查找比較紀錄…' if self.compared is None else ('已有對戰紀錄' if self.group in self.compared else '尚未比較')
        summary = comparison+' · 教師誤差不代表棋力提升'
        if self.advanced and snapshot:
            summary += f' · 共用八小時 · λ .001/.01/.1 · 已曝光 {len(snapshot["prior_test_experiments"])} 份'
        app.text(summary,50,667,muted=True,width=790)
        app.button('learning_groups_save','另存選中完整設定',(50,708,290,34),enabled=bool(report) and not active)
        app.button('learning_groups_battle','載入真人對戰',(360,708,260,34),enabled=bool(report) and not active)
        app.button('learning_groups_compare','共同開局比較',(640,708,200,34),enabled=bool(report) and not active)
