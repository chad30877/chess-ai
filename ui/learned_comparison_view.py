"""學習來源、不可變比較預覽及各基準獨立研究報告。"""
from pathlib import Path
from uuid import uuid4
from engine.learning.comparison import create_comparison, load_comparison_plan, comparison_options, comparison_report
from engine.learning.teacher import digest
from engine.sessions.comparison_run import ComparisonRun
from engine.storage.batch_storage import write_json_atomic
from ui.replay_evaluation_editor import TERM_LABELS


class LearnedComparisonView:
    def __init__(self,root):
        self.root=Path(root); self.source=None; self.path=None; self.report=None; self.message=''
        self.roles={'original','learned'}; self.stable=False; self.baseline='material'
        self.page=0; self.candidate=0; self.config=False; self.config_page=0; self.config_side=0
        self.opening_index=None
        self.entries=[]; self.index=0
    def open(self,source):
        self.source=source; self.path=None; self.report=None; self.message=''; self.page=0; self.index=0
        self.roles={'original','learned'}; self.stable=False; self.baseline='material'; self.config=False
        self.entries=[]
        for file in sorted((self.root/'data/learning-comparisons').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            if digest(load_comparison_plan(file.parent)['source'])==digest(source): self.entries.append(file.parent)
        if self.entries: self.open_plan(self.entries[0])
    def open_plan(self,path):
        self.path=Path(path); self.report=comparison_report(path); plan=self.report['plan']; self.source=plan['source']
        self.roles=set(plan['roles']); self.stable='stable' in plan['definitions']; self.baseline='material'; self.page=0; self.candidate=0
    def action(self,action,app):
        try:
            if action=='learning_compare_back': app.learning.page='groups'; return
            if action=='learning_compare_config': self.config=not self.config; self.config_page=0; return
            if action.startswith('learning_compare_opening:'): self.opening_index=int(action.split(':')[1]); return
            if action=='learning_compare_opening_back': self.opening_index=None; return
            if action=='learning_compare_config_next': self.config_page+=1; return
            if action=='learning_compare_config_side': self.config_side+=1; self.config_page=0; return
            if action=='learning_compare_new': self.path=None; self.report=None; self.message=''; return
            if action in ('learning_compare_prev_plan','learning_compare_next_plan'):
                self.index=(self.index+(1 if action.endswith('next_plan') else -1))%len(self.entries)
                self.open_plan(self.entries[self.index]); return
            if action=='learning_compare_stable' and not self.path: self.stable=not self.stable
            elif action.startswith('learning_compare_role:') and not self.path:
                role=action.split(':')[1]
                if role in self.roles: self.roles.remove(role)
                else: self.roles.add(role)
            elif action.startswith('learning_compare_baseline:'):
                self.baseline=action.split(':')[1]; self.page=0
            elif action=='learning_compare_candidate': self.candidate+=1; self.page=0
            elif action in ('learning_compare_prev','learning_compare_next'):
                self.page=max(0,self.page+(1 if action.endswith('next') else -1))
            elif action=='learning_compare_freeze':
                self.path=create_comparison(self.root,self.source,roles=[r for r in ('original','learned') if r in self.roles],stable=self.stable)
                self.entries.insert(0,self.path); self.index=0; self.open_plan(self.path)
            elif action=='learning_compare_start' and self.path:
                if app.batch and not app.batch.future.done(): raise ValueError('請先停止目前批次')
                app.batch=ComparisonRun(comparison_options(self.path,self.baseline),app.executor)
                app.batch_mode='evaluation'; app.mode='auto'; app.batch_games_page=0
            elif action=='learning_compare_records' and self.path:
                data=comparison_report(self.path)['baselines'][self.baseline]
                if data['path']: app.show_records(batch_id=data['path'].name)
            elif action=='learning_compare_replay' and self.path:
                data=comparison_report(self.path)['baselines'][self.baseline]
                if data['replays']: app.open_replay(str(data['replays'][-1]),return_to='learning')
            elif action=='learning_compare_save' and self.path:
                data=comparison_report(self.path)['baselines'][self.baseline]['candidates']
                row=data[self.candidate%len(data)]
                target=self.root/'configs/evaluation'/f'comparison-{row["role"]}-{uuid4().hex[:12]}.json'
                target.parent.mkdir(parents=True,exist_ok=True); write_json_atomic(target,row['config'])
                self.message='已另存 '+target.name
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc: self.message=str(exc)
    def render(self,app):
        app.text('學習結果 · 共同開局比較',50,78,large=True)
        app.button('learning_compare_back','學習結果',(50,120,180,32))
        app.button('learning_compare_prev_plan','上一份',(250,120,130,32),enabled=len(self.entries)>1)
        app.button('learning_compare_next_plan','下一份',(400,120,130,32),enabled=len(self.entries)>1)
        app.button('learning_compare_new','另建比較',(650,120,190,32),enabled=bool(self.path))
        if not self.source: return
        from engine.learning.group_training import GROUPS
        app.text(f'來源 {self.source["experiment_id"][:16]} · '+','.join(GROUPS.get(g,g) for g in self.source['groups'])+' · '+{'single':'單群組','direct':'直接組合','joint':'聯合訓練'}.get(self.source['kind'],self.source['kind']),50,165,width=790)
        app.text('Alpha-Beta 3／q4 · 同時4局 · 每局1 worker · TT 4096',50,194,width=790)
        app.text('32條共同線 × 換色2局／候選／基準 · 不申請和棋 · 無手數上限',50,223,width=790)
        app.button('learning_compare_config','返回開局／結果' if self.config else '完整設定',(620,260,220,32))
        if not self.path:
            for index,role in enumerate(('original','learned')):
                app.button('learning_compare_role:'+role,('✓ ' if role in self.roles else '')+('原始設定' if role=='original' else '學習／組合設定'),(50+index*265,260,250,32))
            app.button('learning_compare_stable',('✓ ' if self.stable else '')+'額外 stable 參考',(50,310,320,36))
            count=len(self.roles)*64
            app.text(f'純子力主比較 {count}局'+(f' ＋ stable {count}局' if self.stable else '')+f' ＝ 共{count*(2 if self.stable else 1)}局',50,365,width=790)
            app.text('原始與學習保留各自身份；各基準分開統計。',50,412,muted=True,width=790)
            app.button('learning_compare_freeze','凍結預覽條件',(50,470,340,40),enabled=bool(self.roles),primary=True)
            if self.config: self._config(app,[self.source['original'],self.source['config'],self.source['stable']],['原始','學習／組合','stable'],top=530)
        else:
            try: self.report=comparison_report(self.path)
            except (OSError,ValueError,KeyError) as exc: self.message=str(exc); return
            data=self.report['baselines'][self.baseline]; plan=self.report['plan']
            for index,key in enumerate(plan['definitions']):
                app.button('learning_compare_baseline:'+key,'純子力主比較' if key=='material' else 'stable 參考',(50+index*275,260,260,32),primary=self.baseline==key)
            app.text(f'本基準 {plan["definitions"][self.baseline]["planned_games"]}局 · 全計畫 {plan["planned_games"]}局 · '+{'not-started':'未開始','stopped':'已停止','completed':'完成','failed':'失敗','generating':'執行中'}.get(data['status'],data['status']),50,306,width=790)
            rows=data['candidates']; self.candidate%=len(rows); row=rows[self.candidate]
            app.button('learning_compare_candidate',row['label']+'／切換',(50,342,240,32))
            if self.config:
                definition=plan['definitions'][self.baseline]
                self._config(app,[definition['baseline']['config'],*[r['config'] for r in rows],
                    dict(search=definition['search'],workers=definition['workers'],claim_draw=definition['claim_draw'],max_plies=definition['max_plies'],base_seed=definition['base_seed'])],
                    ['基準',*[r['label'] for r in rows],'搜尋與規則'],top=390)
            elif self.opening_index is not None:
                opening=row['openings'][self.opening_index]; line=opening['line']
                app.text(f'{opening["position_index"]}. '+line.get('name',''),50,390,width=790)
                moves=line['moves_uci']
                for index in range(3): app.text(' '.join(moves[index*4:index*4+4]),50,425+index*27,width=790)
                app.text(f'完整配對 {opening["completed_pairs"]}/1 · 未完成 {opening["unfinished"]} · 待執行 {opening["pending_games"]} · 中斷 {opening["interrupted_attempts"]} · {opening["elapsed_seconds"]:.2f}秒',50,518,width=790)
                app.text('來源 '+str(line.get('source',{}).get('url',line.get('source',{}).get('repository','已保存來源快照'))),50,550,muted=True,width=790)
                app.button('learning_compare_opening_back','返回逐開局報告',(50,592,300,32))
            else:
                app.text(f'勝 {row["wins"]}／和 {row["draws"]}／敗 {row["losses"]} · 未完成 {row["unfinished"]} · 待執行 {row["pending_games"]}',310,348,width=530)
                app.text(f'完整配對 {row["completed_pairs"]}/{len(row["openings"])} · 不完整 {row["incomplete_pairs"]} · 中斷嘗試 {row["interrupted_attempts"]} · 對局 {row["elapsed_seconds"]:.1f}秒',50,390,width=790)
                def metric(split):
                    value=row['teacher'][split]
                    return f'{value["mae"]:.4f} ({value["games"]}盤/{value["positions"]}局面)' if value and value.get('mae') is not None else '無資料'
                app.text('教師逐盤MAE：驗 '+metric('validation')+' · 測 '+metric('test'),50,423,width=790)
                pages=max(1,(len(row['openings'])+2)//3); self.page=min(self.page,pages-1)
                for index,opening in enumerate(row['openings'][self.page*3:self.page*3+3]):
                    y=462+index*44
                    app.button('learning_compare_opening:'+str(opening['position_index']-1),
                        f'{opening["position_index"]}. {opening["line"].get("eco","")} {opening["line"].get("name","")}',(50,y,390,39))
                    app.text(f'{opening["wins"]}勝{opening["draws"]}和{opening["losses"]}敗 · 未完{opening["unfinished"]}/待{opening["pending_games"]}',455,y,width=385)
                    app.text(f'完整對{opening["completed_pairs"]} · 中斷{opening["interrupted_attempts"]} · {opening["elapsed_seconds"]:.2f}秒',455,y+19,muted=True,width=385)
                app.button('learning_compare_prev','上一頁',(50,602,145,30),enabled=self.page>0)
                app.text(f'共同開局 {self.page+1}/{pages}',220,607,muted=True)
                app.button('learning_compare_next','下一頁',(420,602,145,30),enabled=self.page+1<pages)
            active=app.batch is not None and not app.batch.future.done()
            app.button('learning_compare_start','開始／續跑此基準',(50,648,260,36),enabled=not active and data['status']!='completed',primary=True)
            app.button('learning_compare_records','逐局紀錄',(330,648,160,36),enabled=bool(data['path']))
            app.button('learning_compare_replay','回放',(510,648,130,36),enabled=bool(data['replays']))
            app.button('learning_compare_save','另存候選',(660,648,180,36))
        app.text(self.message or '教師誤差與對戰分開；有限觀察不保證棋力提升。',50,714,muted=True,width=790)
    def _config(self,app,configs,labels,top):
        self.config_side%=len(configs); config=configs[self.config_side]
        app.button('learning_compare_config_side',labels[self.config_side]+'／切換',(50,top,230,30))
        app.text('分階段 '+str(config.get('phase',{}).get('enabled','—'))+' · 所有欄位逐頁檢視',300,top+4,width=540)
        def flatten(value,prefix=''):
            for name,item in value.items():
                key=prefix+TERM_LABELS.get(name,name)
                if isinstance(item,dict): yield from flatten(item,key+'.')
                else: yield key+' = '+str(item)
        terms=list(flatten(config)); pages=max(1,(len(terms)+2)//3); self.config_page%=pages
        for index,line in enumerate(terms[self.config_page*3:self.config_page*3+3]):
            app.text(line,50,top+40+index*27,width=790)
        app.button('learning_compare_config_next',f'權重 {self.config_page+1}/{pages}',(620,top+115,220,30))
