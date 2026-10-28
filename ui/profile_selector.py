"""共用評分設定選擇小視窗；確認前保留原入口的選擇。"""

import json
from dataclasses import asdict

from engine.sessions.evaluation_comparison import ComparisonSearchConfig

import pygame

from engine.evaluation.config import EvaluationConfig
from engine.learning.rating import profile_rating
from ui.controls import BORDER, PANEL, TEXT
from ui.evaluation_profiles import config_summary
from ui.replay_evaluation_editor import GROUPS

def rating_search(depth, workers, capacity):
    return asdict(ComparisonSearchConfig(depth_plies=int(depth), search_workers=int(workers),
                                         transposition_capacity=int(capacity)))


FILTER_GROUPS = tuple(group for group in GROUPS if group[0] not in ('material', 'phase'))


class ProfileSelector:
    PAGE_SIZE = 7

    def __init__(self, directory, selected, apply, *, multiple=False, excluded=(), search=None, max_plies=None):
        self.project = directory.parent.parent
        self.search = search
        self.max_plies = max_plies
        self.ratings = {}
        self.rating_path = None
        self.rating_details = False
        self.rating_page = 0
        self.paths = sorted(path for path in directory.glob('*.json') if path not in excluded)
        self.multiple = multiple
        self.configs = {}
        self.groups = {}
        for path in self.paths:
            try:
                config = EvaluationConfig.from_dict(json.loads(path.read_text(encoding='utf-8')))
                self.configs[path] = config
                terms = config.to_dict()['terms']
                self.groups[path] = {key for key, _, names in FILTER_GROUPS
                                     if any(terms[name]['enabled'] for name in names)}
            except (OSError, ValueError, TypeError, KeyError):
                pass
        self.selected = set(selected) & self.configs.keys()
        self.rating_path = next(iter(self.selected), None)
        self.apply = apply
        self.query = ''
        self.focused = False
        self.offset = 0
        self.message = ''
        self.filter_groups = set()
        self.exact = False

    def results(self):
        return [path for path in self.paths
                if self.query.casefold() in path.stem.casefold()
                and (not self.filter_groups or path in self.groups and
                     self.filter_groups <= self.groups[path])
                and (not self.exact or self.groups.get(path) == self.filter_groups)]

    def rating(self, path):
        if path not in self.ratings:
            self.ratings[path] = profile_rating(self.project, self.configs[path].to_dict(),
                                                search=self.search, max_plies=self.max_plies)
        return self.ratings[path]

    def scroll(self, amount):
        self.offset = max(0, min(self.offset + amount, max(0, len(self.results()) - self.PAGE_SIZE)))

    def action(self, action, app):
        if action == 'profile_cancel':
            self.close(app)
        elif action == 'profile_rating':
            self.rating_details = not self.rating_details
            self.rating_page = 0
        elif action == 'profile_rating_next':
            self.rating_page += 1
        elif action == 'profile_search':
            self.focused = True
            pygame.key.start_text_input()
        elif action.startswith('profile_row:'):
            index = int(action.split(':')[1])
            path = self.results()[index]
            if path in self.configs:
                self.rating_path = path
                if self.multiple:
                    self.selected.symmetric_difference_update({path})
                else:
                    self.selected = {path}
        elif action.startswith('profile_group:'):
            self.filter_groups.symmetric_difference_update({action.split(':')[1]})
            self.offset = 0
        elif action == 'profile_exact':
            self.exact = not self.exact
            self.offset = 0
        elif action == 'profile_prev':
            self.scroll(-self.PAGE_SIZE)
        elif action == 'profile_next':
            self.scroll(self.PAGE_SIZE)
        elif action == 'profile_confirm':
            try:
                for path in self.selected:
                    EvaluationConfig.from_dict(json.loads(path.read_text(encoding='utf-8')))
                self.apply(sorted(self.selected))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.message = f'無法載入設定：{exc}'
                return
            self.close(app)

    def close(self, app):
        app.profile_selector = None
        pygame.key.stop_text_input()

    def input(self, event, app):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close(app)
            elif self.focused:
                if event.key == pygame.K_BACKSPACE:
                    self.query = self.query[:-1]
                elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                    self.query = ''
                self.offset = 0
        elif event.type == pygame.TEXTINPUT and self.focused:
            self.query += event.text
            self.offset = 0
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll(-event.y * 3)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for button in reversed(app.buttons):
                if button.enabled and button.rect.collidepoint(event.pos):
                    self.action(button.action, app)
                    break

    def render(self, app):
        overlay = pygame.Surface(app.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        app.screen.blit(overlay, (0, 0))
        app.buttons = []
        app.draw_rect(PANEL, (95, 85, 710, 650), border_radius=10)
        app.draw_rect(BORDER, (95, 85, 710, 650), width=1, border_radius=10)
        app.text('選擇候選設定（可多選）' if self.multiple else '選擇評分設定', 115, 100, large=True)
        if self.rating_details and self.rating_path in self.configs:
            report = self.rating(self.rating_path)
            estimate = report if report['rating'] is not None else report['provisional']
            app.text(self.rating_path.stem, 115, 150, large=True)
            if estimate and estimate['rating'] is not None:
                label = '正式' if report['rating'] is not None else '暫估'
                app.text(f'{label}棋力 {estimate["rating"]:.0f} · {estimate["games"]}局 · {estimate["wins"]}勝{estimate["draws"]}和{estimate["losses"]}敗', 115, 205, width=670)
                interval = estimate['interval']
                app.text(f'區間 {interval[0]:.0f}–{interval[1]:.0f}' if interval else '不確定區間：無法估算', 115, 245, width=670)
                sources = estimate['sources']
                pages = max(1, (len(sources) + 2) // 3)
                self.rating_page %= pages
                for i, source in enumerate(sources[self.rating_page * 3:self.rating_page * 3 + 3]):
                    app.text(source, 115, 410 + i * 40, width=670)
                app.button('profile_rating_next', f'來源 {self.rating_page + 1}/{pages}', (115, 550, 160, 35), enabled=pages > 1)
            else:
                app.text('尚未評分', 115, 205, width=670)
            search = report['conditions']['search']
            app.text(f'深度 {search["depth_plies"]} · q{search["quiescence_depth"]} · worker {search["search_workers"]} · 表項 {search["transposition_capacity"]}', 115, 305, width=670)
            app.text(f'和棋宣告 {"開" if report["conditions"]["claim_draw"] else "關"} · 手數上限 {report["conditions"]["max_plies"] if report["conditions"]["max_plies"] is not None else "無"}', 115, 345, width=670)
            app.text(report['limitation'], 115, 610, width=670)
            app.button('profile_rating', '返回設定', (665, 680, 120, 36))
            return
        app.button('profile_search', '名稱：' + self.query + ('│' if self.focused else ''), (115, 147, 670, 38))
        for index, (key, label, _) in enumerate(FILTER_GROUPS):
            app.button('profile_group:' + key, ('■ ' if key in self.filter_groups else '□ ') + label,
                       (115 + index * 134, 192, 128, 32), primary=key in self.filter_groups)
        results = self.results()
        app.button('profile_exact', ('■ ' if self.exact else '□ ') + '僅此組合', (115, 231, 150, 30))
        app.text(f'{len(results)} 份設定 · 已選 {len(self.selected)}', 280, 234, muted=True)
        for index, path in enumerate(results[self.offset:self.offset + self.PAGE_SIZE], self.offset):
            y = 271 + (index - self.offset) * 52
            app.button(f'profile_row:{index}', '', (115, y, 670, 49),
                       enabled=path in self.configs, primary=path in self.selected)
            app.text(('已選 · ' if path in self.selected else '') + path.stem, 128, y, width=640)
            summary = config_summary(self.configs[path]) if path in self.configs else '設定檔無法讀取'
            if path in self.configs:
                rating = self.rating(path)
                estimate = rating if rating['rating'] is not None else rating['provisional']
                score = ('正式' if rating['rating'] is not None else '暫估') + f' {estimate["rating"]:.0f} · {estimate["games"]}局' if estimate and estimate['rating'] is not None else '尚未評分'
                summary += '｜' + score
            app.draw_label(app.small_font, summary, (128, y + 25), TEXT, 640)
        app.text(self.message, 115, 639, width=670)
        app.button('profile_prev', '上一頁', (115, 680, 105, 36), enabled=self.offset > 0)
        app.button('profile_next', '下一頁', (230, 680, 105, 36), enabled=self.offset + self.PAGE_SIZE < len(results))
        app.button('profile_rating', '棋力明細', (355, 680, 150, 36), enabled=self.rating_path in self.configs)
        app.button('profile_cancel', '取消', (535, 680, 115, 36))
        app.button('profile_confirm', '套用', (665, 680, 120, 36), enabled=bool(self.selected), primary=True)
