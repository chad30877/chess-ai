"""單群組學習、凍結結果及完整設定另存介面。"""
from pathlib import Path
from uuid import uuid4
from engine.learning.training import TrainingRun, load_training, save_training_config

class TrainingView:
    def __init__(self, root):
        self.root=Path(root); self.labels=self.path=self.run=self._loaded_run=None
        self.state={}; self.message=''; self.advanced=False; self.stage=0; self.index=0; self.saved=None
        self.entries=[]
    def active(self): return self.run is not None and not self.run.future.done()
    def open(self,labels):
        self.labels=Path(labels); self.run=self._loaded_run=None; self.message=''; self.index=0
        self.entries=sorted((self.labels/'training').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        self.state={}; self.path=None; self.saved=None
        if self.entries: self.load(self.entries[0].parent)
    def load(self,path):
        self.path=Path(path); self.state=load_training(path); self.saved=None
    def action(self,action,app):
        try:
            if action=='learning_training_stop' and self.active(): self.run.stop(); return
            if self.active(): return
            if action=='learning_training_new':
                self.path=self.labels/'training'/uuid4().hex
                self.index=0; self.saved=None; self.state={}
                self.run=TrainingRun(self.path,app.executor,label_path=self.labels)
            elif action=='learning_training_resume' and self.path and not self.state.get('report'):
                self.run=TrainingRun(self.path,app.executor)
            elif action=='learning_training_advanced': self.advanced=not self.advanced
            elif action=='learning_training_stage': self.stage=(self.stage+1)%4
            elif action in ('learning_training_prev','learning_training_next'):
                self.index=(self.index+(1 if action.endswith('next') else -1))%len(self.entries)
                self.run=self._loaded_run=None; self.load(self.entries[self.index].parent)
            elif action in ('learning_training_save','learning_training_battle') and self.state.get('frozen'):
                if self.saved is None:
                    target=self.root/'configs/evaluation'/('learned-'+self.path.name+'.json')
                    if target.exists():
                        from engine.evaluation.config import EvaluationConfig
                        import json
                        existing=EvaluationConfig.from_dict(json.loads(target.read_text(encoding='utf-8')))
                        wanted=EvaluationConfig.from_dict(self.state['frozen']['config'])
                        if existing.to_dict()!=wanted.to_dict(): raise ValueError('另存目標已改動，請保留原檔並建立新學習實驗')
                        self.saved=target
                    else: self.saved=save_training_config(self.path,target)
                self.message='已另存 '+self.saved.name
                if action=='learning_training_battle':
                    app.live_evaluation_file=self.saved
                    if self.saved not in app.live_evaluation_files: app.live_evaluation_files.append(self.saved)
                    app.new_setup('human')
        except (ValueError,OSError,KeyError,TypeError) as exc: self.message=str(exc)
    def render(self,app):
        active=self.active()
        if self.run:
            if active:
                self.state.update(self.run.snapshot())
            elif self._loaded_run is not self.run:
                runtime=self.run.snapshot()
                try:
                    self.load(self.run.path)
                    entry=self.run.path/'snapshot.json'
                    if entry not in self.entries: self.entries.insert(0,entry)
                except (OSError,ValueError) as exc:
                    self.state=runtime
                    self.message=str(exc)
                if runtime.get('status')=='failed' and not self.state.get('report'):
                    self.state.update(status='failed',error=runtime.get('error',''))
                self._loaded_run=self.run
        s=self.state; frozen=s.get('frozen'); report=s.get('report'); cal=s.get('calibration')
        app.text('學習實驗 · 棋子位置',50,78,large=True)
        app.button('learning_labels','教師標記',(50,120,190,34),enabled=not active)
        if s.get('snapshot'):
            source=s['snapshot']
            app.text(f'沿用標記 {source["label_identity"][:10]}… · 已有 {len(source.get("prior_test_experiments",[]))} 份實驗使用同資料測試',260,128,muted=True,width=580)
        app.button('learning_training_new','新建並學習',(50,166,210,36),enabled=not active,primary=True)
        app.button('learning_training_resume','續跑／重試',(280,166,210,36),enabled=bool(self.path) and not report and not active)
        app.button('learning_training_stop','停止',(510,166,130,36),enabled=active)
        statuses={'queued':'準備中','running':'訓練中','completed':'完成','stopped':'已停止','failed':'失敗','interrupted':'待續跑','ready':'待開始'}
        if s:
            app.text(f'{statuses.get(s["status"],s["status"])} · 已完成 {s["completed"]}/{s["total"]} 候選 · {s.get("elapsed_seconds",0):.1f} 秒',50,220,width=790)
        if self.message or s.get('error'): app.text(self.message or s['error'],50,250,width=790)
        if cal:
            app.text(f'共用倍率 {cal["scale"]:.7f} · 校準殘差 MAE {cal["mae"]:.4f} · '+('診斷正常' if cal['healthy'] else '診斷異常'),50,282,width=790)
            if cal.get('warning'): app.text(cal['warning'],50,308,width=790)
        candidates=s.get('candidates',{})
        if candidates:
            text=' / '.join(f'{label} {candidates[key]["validation"]["mae"]:.5f}' if key in candidates and candidates[key]['validation']['mae'] is not None else f'{label} 待完成' for key,label in (('weak','弱'),('medium','中'),('strong','強')))
            app.text('驗證 MAE：'+text,50,338,width=790)
        if frozen:
            original=s['snapshot']['original']['terms']['piece_square']; learned=frozen['config']['terms']['piece_square']
            app.text(f'選定 { {"weak":"弱","medium":"中","strong":"強"}[frozen["strength"]] } · 中局 {original["weight"]:.5f} → {learned["weight"]:.5f} · 殘局 {original["endgame_weight"]:.5f} → {learned["endgame_weight"]:.5f}',50,370,width=790)
        stage_keys=[None,'opening','middlegame','endgame']; stage_labels=['全部階段','開局','中局','殘局']
        app.button('learning_training_stage',stage_labels[self.stage],(620,408,210,30),enabled=bool(report))
        if report:
            app.text('逐盤 MAE　　驗證／測試（有效盤／局面）',50,410,width=550)
            for index,(name,label) in enumerate((('material','純子力'),('original','原始同組'),('learned','學習同組'),('stable','stable'))):
                values=[]
                for split in ('validation','test'):
                    metric=report[split][name]
                    if self.stage: metric=metric['stages'][stage_keys[self.stage]]
                    values.append((f'{metric["mae"]:.4f}' if metric['mae'] is not None else '無資料')+f'（{metric["games"]}/{metric["positions"]}）')
                app.text(label+'　 '+ ' ／ '.join(values),50,448+index*28,width=790)
            app.text('優先對戰觀察' if report['priority_battle_observation'] else '獨立誤差結果；不代表棋力提升',50,563,muted=True,width=790)
        app.button('learning_training_save','另存完整設定',(50,600,220,34),enabled=bool(frozen) and not active)
        app.button('learning_training_battle','載入真人對戰',(290,600,220,34),enabled=bool(frozen) and not active)
        app.button('learning_training_advanced','進階條件',(600,600,230,34))
        if self.advanced and s.get('snapshot'):
            rules=s['snapshot']['rules']
            app.text(f'NNLS {rules["method"]} · λ .001 / .01 / .1 · 固定子力 · 每次共用八小時',50,647,width=790)
            deviation=cal.get('relative_deviation') if cal else None
            diagnostic=f'{deviation:.1%}' if deviation is not None else '不足'
            app.text(f'容差 {rules["tolerance"]} · 子集偏差 {diagnostic}／50% · 同分優先強懲罰',50,675,muted=True,width=790)
        app.text(f'已保存學習 {min(self.index+1,len(self.entries))}/{len(self.entries)}',50,725)
        app.button('learning_training_prev','上一份',(460,715,160,32),enabled=len(self.entries)>1 and not active)
        app.button('learning_training_next','下一份',(650,715,160,32),enabled=len(self.entries)>1 and not active)
