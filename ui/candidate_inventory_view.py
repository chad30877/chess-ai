"""已保存研究結果的盤點與候選清單。"""
from engine.learning.candidate_inventory import load_candidate_inventory, load_all_candidate_inventory
from engine.learning.group_training import GROUPS


class InventoryView:
    def __init__(self):
        self.report = None
        self.tab = 'candidates'
        self.page = 0
        self.selected = 0
        self.selected_indices = set()
        self.origin_filter = None
        self.group_filter = None

    def open(self, path):
        self.report = load_candidate_inventory(path)
        self.tab = 'candidates'; self.page = self.selected = 0

    def open_first(self, root):
        self.report = load_all_candidate_inventory(root)
        self.report['all_sources'] = True
        self.tab = 'candidates'; self.page = self.selected = 0
        self.selected_indices = set(); self.origin_filter = self.group_filter = None

    def filtered(self):
        return [(index, row) for index, row in enumerate(self.report['candidates'])
                if (self.origin_filter is None or row['origin'] == self.origin_filter)
                and (self.group_filter is None or self.group_filter in row['groups'])]

    def action(self, action):
        if self.report.get('all_sources') and action == 'learning_inventory_origin':
            values = [None, 'legacy', 'group', 'combination']
            self.origin_filter = values[(values.index(self.origin_filter) + 1) % len(values)]
            self.page = 0
        elif self.report.get('all_sources') and action == 'learning_inventory_group':
            values = [None, *GROUPS]
            self.group_filter = values[(values.index(self.group_filter) + 1) % len(values)]
            self.page = 0
        elif action == 'learning_inventory_tab':
            self.tab = 'coverage' if self.tab == 'candidates' else 'candidates'; self.page = 0
        elif action == 'learning_inventory_next': self.page += 1
        elif action == 'learning_inventory_prev': self.page = max(0, self.page - 1)
        elif action.startswith('learning_inventory_candidate:'):
            self.selected = int(action.split(':')[1])
            if self.report.get('all_sources'):
                if self.selected in self.selected_indices:
                    self.selected_indices.remove(self.selected)
                    if self.selected_indices: self.selected = min(self.selected_indices)
                else: self.selected_indices.add(self.selected)

    def render(self, app):
        if self.report.get('all_sources'):
            return self.render_all(app)
        report = self.report
        app.text('組合研究 · 候選盤點', 50, 78, large=True)
        app.button('learning_inventory_back', '返回組合' if app.learning.inventory_return == 'combination' else '返回學習', (50, 120, 170, 34))
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

    def render_all(self, app):
        rows = self.filtered()
        pages = max(1, (len(rows) + 4) // 5)
        self.page = min(self.page, pages - 1)
        kinds = {'legacy': '舊棋子位置', 'group': '單群組', 'combination': '組合'}
        app.text('比較候選', 50, 78, large=True)
        app.button('learning_inventory_back', '返回學習', (50, 120, 170, 34))
        app.button('learning_inventory_origin', '來源：' + kinds.get(self.origin_filter, '全部'), (240, 120, 250, 34))
        app.button('learning_inventory_group', '群組：' + GROUPS.get(self.group_filter, '全部'), (510, 120, 330, 34))
        if not rows: app.text('沒有符合條件的候選', 50, 200)
        for row_index, (index, item) in enumerate(rows[self.page * 5:self.page * 5 + 5]):
            source = item['source']
            label = '、'.join(GROUPS.get(group, group) for group in item['groups'])
            tick = '[x] ' if index in self.selected_indices else '[ ] '
            detail = f"{tick}{kinds[item['origin']]} · {label} · {source['experiment_id'][-8:]} · 資料 {source['dataset_identity'][:10]}"
            app.button(f'learning_inventory_candidate:{index}', detail, (50, 195 + row_index * 60, 790, 36))
            app.text(f"教師誤差 {item['mae']:.4f} · 標記 {source['label_identity'][:10]}", 70, 232 + row_index * 60, muted=True, width=750)
        errors = self.report['errors']
        if errors: app.text(f'未完成或不可用 {len(errors)} 份 · …{errors[0]["path"][-60:]} · {errors[0]["error"]}', 50, 530, width=790)
        app.button('learning_inventory_prev', '上頁', (50, 650, 130, 34), enabled=self.page > 0)
        app.text(f'{self.page + 1}/{pages} · 已選 {len(self.selected_indices)}', 205, 658)
        app.button('learning_inventory_next', '下頁', (300, 650, 130, 34), enabled=self.page + 1 < pages)
        if self.selected_indices:
            app.button('learning_inventory_screen', '選此候選進行短對局', (490, 650, 350, 34), primary=True)
