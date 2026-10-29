"""已保存研究結果的盤點與候選清單。"""
from engine.learning.candidate_inventory import load_candidate_inventory
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
        from engine.learning.config_catalog import load_catalog, project_root
        self.root = project_root(root)
        self.catalog_root = root
        self.report = load_catalog(root)
        self.query = self.draft = ''
        self.focus = None
        self.sort = 'name'
        self.context = None
        self.rating_contexts = {}
        self.rating_future = None
        self.ratings_loaded = False
        self.evaluation_filter = None
        self.message = ''
        self.details = False
        self.tab = 'candidates'; self.page = self.selected = 0
        self.selected_indices = set(); self.origin_filter = self.group_filter = None

    def contexts(self):
        if self.sort == 'rating': return self.rating_contexts
        if self.sort == 'mae':
            return {row['metric_context']: row['teacher'] + ' / ' + row['metric_context'][:6]
                    for row in self.report['candidates'] if row['metric_context']}
        return {}

    def value(self, row):
        if self.sort == 'mae':
            peers = [r for r in self.report['candidates'] if r['config_identity'] == row['config_identity']
                     and r['metric_context'] == self.context and r['mae'] is not None]
            return max(peers, key=lambda r:r['metric_date'])['mae'] if peers else None
        if self.sort == 'rating': return row['ratings'].get(self.context, {}).get('value')
        return None

    def filtered(self):
        rows = [(index, row) for index, row in enumerate(self.report['candidates'])
                if (self.origin_filter is None or row.get('method') == self.origin_filter)
                and (self.group_filter is None or self.group_filter in row['groups'])
                and (self.evaluation_filter is None or bool(row.get('ratings')) == self.evaluation_filter)
                and self.query.casefold() in (row.get('name', '') + ' ' + row.get('teacher', '') + ' ' + row.get('code', '')).casefold()]
        if self.sort == 'name': return sorted(rows, key=lambda item:item[1]['name'].casefold())
        def key(item):
            value = self.value(item[1])
            return value is None, (-value if self.sort == 'rating' else value) if value is not None else 0, item[1]['name']
        return sorted(rows, key=key)

    def input(self, event):
        import pygame
        if not self.focus or event.type not in (pygame.TEXTINPUT, pygame.KEYDOWN): return False
        if event.type == pygame.TEXTINPUT: self.draft += event.text
        elif event.key == pygame.K_BACKSPACE: self.draft = self.draft[:-1]
        elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL: self.draft = ''
        elif event.key == pygame.K_RETURN:
            if self.focus == 'query': self.query = self.draft; self.page = 0
            elif self.draft.strip():
                import json
                from engine.storage.batch_storage import write_json_atomic
                state_path = self.root / 'data/learning-ui.json'
                try: state = json.loads(state_path.read_text(encoding='utf-8'))
                except (OSError, ValueError): state = {}
                row = self.report['candidates'][self.selected]
                row['name'] = self.draft.strip()
                state.setdefault('names', {})[row['name_key']] = row['name']
                state_path.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(state_path, state)
            self.focus = None; pygame.key.stop_text_input()
        elif event.key == pygame.K_ESCAPE: self.focus = None; pygame.key.stop_text_input()
        return True

    def action(self, action, app=None):
        import pygame
        if action == 'learning_inventory_origin':
            values = [None, 'D', 'J', 'U']
            self.origin_filter = values[(values.index(self.origin_filter) + 1) % len(values)]; self.page = 0
        elif action == 'learning_inventory_group':
            values = [None, *GROUPS]
            self.group_filter = values[(values.index(self.group_filter) + 1) % len(values)]; self.page = 0
        elif action in ('learning_inventory_query', 'learning_inventory_rename'):
            self.focus = 'query' if action.endswith('query') else 'rename'
            self.draft = self.query if self.focus == 'query' else self.report['candidates'][self.selected]['name']
            pygame.key.start_text_input()
        elif action == 'learning_inventory_sort':
            values = ['name', 'rating', 'mae']
            self.sort = values[(values.index(self.sort) + 1) % len(values)]
            self.context = next(iter(self.contexts()), None)
            self.page = 0
            if self.sort == 'rating' and not self.ratings_loaded and self.rating_future is None and app:
                from engine.learning.config_catalog import load_ratings
                self.rating_future = app.read_executor.submit(load_ratings, self.root)
        elif action == 'learning_inventory_evaluated':
            values = [None, True, False]
            self.evaluation_filter = values[(values.index(self.evaluation_filter) + 1) % len(values)]
            self.page = 0
            if not self.ratings_loaded and self.rating_future is None and app:
                from engine.learning.config_catalog import load_ratings
                self.rating_future = app.read_executor.submit(load_ratings, self.root)
        elif action == 'learning_inventory_context':
            values = list(self.contexts())
            if values: self.context = values[(values.index(self.context) + 1) % len(values)] if self.context in values else values[0]
            self.page = 0
        elif action == 'learning_inventory_details': self.details = not self.details
        elif action == 'learning_inventory_refresh': self.open_first(self.catalog_root)
        elif action == 'learning_inventory_tab': self.tab = 'coverage' if self.tab == 'candidates' else 'candidates'; self.page = 0
        elif action == 'learning_inventory_next': self.page += 1
        elif action == 'learning_inventory_prev': self.page = max(0, self.page - 1)
        elif action.startswith('learning_inventory_candidate:'):
            self.selected = int(action.split(':')[1])
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
        if self.rating_future is not None and self.rating_future.done():
            try:
                ratings, self.rating_contexts = self.rating_future.result()
                for row in self.report['candidates']: row['ratings'] = ratings.get(row['config_identity'], {})
                self.ratings_loaded = True
                if self.context not in self.contexts(): self.context = next(iter(self.contexts()), None)
            except Exception as exc: self.message = str(exc)
            self.rating_future = None
        rows = self.filtered()
        pages = max(1, (len(rows) + 3) // 4)
        self.page = min(self.page, pages - 1)
        app.text('比較候選', 50, 78, large=True)
        app.button('learning_inventory_refresh', '重新整理', (650, 74, 190, 34))
        app.button('learning_inventory_query', self.draft + ' |' if self.focus == 'query' else '搜尋：' + self.query, (50, 125, 370, 34))
        app.button('learning_inventory_origin', '方式：' + (self.origin_filter or '全部'), (435, 125, 185, 34))
        app.button('learning_inventory_group', GROUPS.get(self.group_filter, '全部群組'), (635, 125, 205, 34))
        app.button('learning_inventory_sort', '排序：' + {'name':'名稱', 'rating':'棋力 高→低', 'mae':'驗證誤差 低→高'}[self.sort], (50, 170, 245, 34))
        app.button('learning_inventory_context', '評估來源：' + self.contexts().get(self.context, '未評估'), (310, 170, 350, 34), enabled=bool(self.contexts()))
        app.button('learning_inventory_evaluated', {None:'全部棋力狀態', True:'已有棋力', False:'尚無棋力'}[self.evaluation_filter], (675, 170, 165, 34))
        app.text('D=直接組合  J=聯合學習  U=自訂', 50, 218, muted=True, width=790)
        app.text('P=棋子位置  S=兵形  M=活動力  K=王安全  C=協調  -=未使用', 50, 246, muted=True, width=790)
        if not rows: app.text('沒有符合條件的設定', 50, 290)
        for offset, (index, row) in enumerate(rows[self.page * 4:self.page * 4 + 4]):
            value = self.value(row)
            metric = '未評估' if value is None else (f'{value:.0f} ' + row['ratings'].get(self.context, {}).get('status', '') if self.sort == 'rating' else f'MAE {value:.4f}')
            if self.sort == 'name': metric = ''
            tick = '[x]' if index in self.selected_indices else '[ ]'
            app.button(f'learning_inventory_candidate:{index}', f'{tick} {row["name"]}   {row["method"]}:{row["code"]}   {metric}', (50, 285 + offset * 68, 790, 36))
            app.text('教師：' + row['teacher'], 65, 324 + offset * 68, muted=True, width=770)
        if self.rating_future: app.text('載入棋力結果…', 50, 562)
        elif self.message: app.text(self.message, 50, 562, width=790)
        elif self.report['errors']: app.text(f'略過 {len(self.report["errors"])} 份不可用設定', 50, 562, width=790)
        app.button('learning_inventory_prev', '上頁', (50, 600, 120, 34), enabled=self.page > 0)
        app.text(f'{self.page+1}/{pages} · 已選 {len(self.selected_indices)}', 185, 607)
        app.button('learning_inventory_next', '下頁', (370, 600, 120, 34), enabled=self.page + 1 < pages)
        app.button('learning_inventory_rename', self.draft + ' |' if self.focus == 'rename' else '重新命名', (505, 600, 335, 34), enabled=len(self.selected_indices) == 1)
        app.button('learning_inventory_history', '比較紀錄', (50, 650, 190, 34))
        app.button('learning_inventory_details', '來源詳情', (255, 650, 190, 34), enabled=len(self.selected_indices) == 1)
        app.button('learning_inventory_setup', '比較所選設定', (490, 650, 350, 34), enabled=bool(self.selected_indices), primary=True)
        if self.details and self.selected_indices:
            row = self.report['candidates'][self.selected]
            app.text(row['path'], 50, 700, muted=True, width=580)
            app.button('learning_inventory_compare', '權重對照', (650, 695, 190, 34), enabled=len(self.selected_indices) == 1)
            if row['source'].get('label_path'):
                app.text('教師來源：' + row['source']['label_path'], 50, 738, muted=True, width=790)
