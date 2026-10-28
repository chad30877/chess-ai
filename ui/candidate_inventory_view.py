"""已保存研究結果的盤點與候選清單。"""
from engine.learning.candidate_inventory import load_candidate_inventory
from engine.learning.group_training import GROUPS


class InventoryView:
    def __init__(self):
        self.report = None
        self.tab = 'candidates'
        self.page = 0
        self.selected = 0

    def open(self, path):
        self.report = load_candidate_inventory(path)
        self.tab = 'candidates'; self.page = self.selected = 0

    def action(self, action):
        if action == 'learning_inventory_tab':
            self.tab = 'coverage' if self.tab == 'candidates' else 'candidates'; self.page = 0
        elif action == 'learning_inventory_next': self.page += 1
        elif action == 'learning_inventory_prev': self.page = max(0, self.page - 1)
        elif action.startswith('learning_inventory_candidate:'):
            self.selected = int(action.split(':')[1])

    def render(self, app):
        report = self.report
        app.text('組合研究 · 候選盤點', 50, 78, large=True)
        app.button('learning_inventory_back', '返回組合', (50, 120, 170, 34))
        app.button('learning_inventory_tab', '查看覆蓋' if self.tab == 'candidates' else '查看候選', (240, 120, 170, 34))
        app.text('完整排名' if report['complete'] else '部分排名：仍有缺漏、失敗或不相容紀錄', 50, 170, width=790)
        app.text('資料 ' + report['dataset_identity'][:14] + ' · 標記 ' + report['label_identity'][:14], 50, 202, width=790)
        cal = report['calibration']
        app.text('校準 ' + (cal['identity'][:14] if cal else '尚未完成') + ' · 測試 ' + report['test_data_identity'][:14] + ' 已曝光', 50, 230, width=790)
        app.text(report['exposure'], 50, 258, width=790)
        if self.tab == 'candidates':
            candidates = report['candidates']; self.page = min(self.page, max(0, (len(candidates)-1)//5))
            for row, candidate in enumerate(candidates[self.page*5:self.page*5+5]):
                index = self.page*5+row
                label = '、'.join(GROUPS[g] for g in candidate['groups'])
                kind = {'single':'單群組', 'direct':'直接', 'joint':'聯合'}[candidate['kind']]
                app.button(f'learning_inventory_candidate:{index}', f'{index+1}. {label} · {kind} · {candidate["mae"]:.4f} · {candidate["games"]} 盤/{candidate["positions"]} 局面', (50, 300+row*38, 790, 34))
            if candidates:
                candidate = candidates[self.selected]
                stages = candidate['stages']
                def stage(name):
                    item = stages[name]; return f'{item["games"]}盤/{item["positions"]}局面'
                app.text('階段：開局 '+stage('opening')+' · 中局 '+stage('middlegame')+' · 殘局 '+stage('endgame'), 50, 512, width=790)
                app.text('來源 '+candidate['source']['experiment_id']+' · '+candidate['kind'], 50, 544, width=790)
                app.text('來源與曝光：'+candidate['source']['test_data_identity'][:20]+' · 已曝光測試 '+str(len(candidate['source']['prior_test_experiments']))+' 份', 50, 576, width=790)
                app.button('learning_inventory_screen', '選此候選進行短對局', (490, 650, 350, 34), primary=True)
            else: app.text('尚無有效候選', 50, 310, width=790)
            pages = max(1, (len(candidates)+4)//5)
        else:
            entries = list(report['entries'].items()); pages = (len(entries)+7)//8; self.page = min(self.page, pages-1)
            labels = {'completed':'完成', 'missing':'缺漏', 'failed':'失敗', 'incomplete':'未完成', 'invalid':'無有效驗證資料'}
            for row, (groups, statuses) in enumerate(entries[self.page*8:self.page*8+8]):
                name = '、'.join(GROUPS[g] for g in groups)
                status = ' / '.join({'single':'單組', 'direct':'直接', 'joint':'聯合'}[k]+':'+labels[v] for k,v in statuses.items())
                app.text(name+' · '+status, 50, 300+row*34, width=790)
            if report['errors']:
                error = report['errors'][0]
                app.text(f'不相容或損壞 {len(report["errors"])} 份：{error["path"]} · {error["error"]}', 50, 590, width=790)
        app.button('learning_inventory_prev', '上頁', (50, 650, 130, 34), enabled=self.page>0)
        app.text(f'{self.page+1}/{pages}', 205, 658)
        app.button('learning_inventory_next', '下頁', (300, 650, 130, 34), enabled=self.page+1<pages)
