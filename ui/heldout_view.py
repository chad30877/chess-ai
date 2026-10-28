"""已凍結候選的最終教師誤差評估。"""
from pathlib import Path
from engine.learning.final_comparison import load_final_comparison
from engine.learning.heldout import freeze_heldout, evaluate_heldout, load_heldout
from engine.learning.labeling import load_labeling


class HeldoutView:
    def __init__(self, root):
        self.root = Path(root); self.final_path = None; self.path = None; self.state = {}; self.labels = []
        self.label_index = self.result_index = 0; self.message = ''

    def open(self, final_path):
        self.final_path = Path(final_path); final = load_final_comparison(final_path)
        self.path = None; self.state = {}; self.message = ''; self.label_index = self.result_index = 0
        self.labels = []
        for file in sorted((self.root/'data/learning').glob('*/teacher-labels/*/snapshot.json')):
            try:
                label = load_labeling(file.parent)
                if label['ready']: self.labels.append(file.parent)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        entries = sorted((self.root/'data/learning-heldout').glob('*/snapshot.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        for file in entries:
            try:
                state = load_heldout(file.parent)
                if state['snapshot']['final_identity'] == final['identity']:
                    self.path = file.parent; self.state = state; break
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def action(self, action, app):
        try:
            if action == 'learning_heldout_back': app.learning.page = 'screening'
            elif action == 'learning_heldout_freeze':
                self.path = freeze_heldout(self.root,self.final_path); self.state = load_heldout(self.path)
            elif action == 'learning_heldout_label': self.label_index = (self.label_index+1)%len(self.labels)
            elif action == 'learning_heldout_result': self.result_index += 1
            elif action == 'learning_heldout_run':
                evaluate_heldout(self.path, self.labels[self.label_index]); self.state = load_heldout(self.path)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc: self.message = str(exc)

    def render(self, app):
        app.text('最終教師誤差評估', 50, 78, large=True)
        app.button('learning_heldout_back','返回篩選',(50,120,180,34))
        app.text('先凍結候選與評估用途；結果不供選擇或調整候選。',50,180,width=790)
        app.button('learning_heldout_freeze','凍結評估用途',(50,225,230,36),enabled=self.path is None,primary=True)
        if not self.path:
            app.text('尚未凍結',310,233,width=530); return
        app.text('凍結 '+self.state['snapshot']['identity'][:20],310,233,width=530)
        report = self.state.get('report')
        if not report:
            app.button('learning_heldout_label','切換教師資料',(50,290,230,36),enabled=bool(self.labels))
            app.text(str(self.labels[self.label_index]) if self.labels else '尚無完成標記的資料',50,340,width=790)
            app.button('learning_heldout_run','執行最終評估',(50,390,230,36),enabled=bool(self.labels),primary=True)
        else:
            results=report['results']; self.result_index %= len(results); row=results[self.result_index]; metric=row['metric']
            app.button('learning_heldout_result',f'候選 {self.result_index+1}/{len(results)}',(50,290,230,36),enabled=len(results)>1)
            app.text('資料 '+report['dataset_identity'][:20]+' · 標記 '+report['label_identity'][:20],50,340,width=790)
            app.text(('無法評估' if metric is None else f'逐盤 MAE {metric["mae"]:.4f} · {metric["games"]} 盤／{metric["positions"]} 局面' if metric['mae'] is not None else '無有效局面'),50,385,width=790)
            if metric:
                for i,(key,label) in enumerate((('opening','開局'),('middlegame','中局'),('endgame','殘局'))):
                    stage=metric['stages'][key]
                    app.text(f'{label} · {stage["games"]} 盤／{stage["positions"]} 局面',50,425+i*30,width=790)
            app.text('獨立條件可核對' if report['independent'] else '限制：'+'；'.join(report['limitations']),50,550,width=790)
            app.text(report['scope'],50,605,width=790)
        if self.message: app.text(self.message,50,650,width=790)
