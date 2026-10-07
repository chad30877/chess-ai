"""三種對局資料共用的清單、摘要、設定與回放導覽。"""

import json
from datetime import datetime

from engine.storage.data_ids import TAIPEI, date_key

from engine.replay.records_catalog import RecordsCatalog
from ui.controls import MUTED, TEXT

OUTCOMES = {"win": "勝", "draw": "和", "loss": "敗", "unfinished": "未完成"}
RESULTS = {"win": "白勝", "draw": "和", "loss": "黑勝", "unfinished": "未完成", "unknown": "結果未記錄或損壞"}
KINDS = {"batch": "一般批次", "comparison": "評分比較", "comparison_unavailable": "比較摘要不可用", "standalone": "非批次"}
STATES = {"completed": "完成", "generating": "產生中", "stopped": "已停止", "failed": "失敗"}
COLORS = {"win": (108, 210, 158), "draw": (163, 175, 191), "loss": (130, 153, 183)}


def present(value):
    return str(value) if value is not None and value != "" else "未記錄"


def elapsed(value):
    return "未記錄" if value is None else f"{value:.3f} 秒"


def time_label(timestamp):
    if date_key(timestamp) == "日期不詳":
        return "日期時間未記錄"
    return datetime.fromisoformat(timestamp).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


class RecordsView:
    PAGE_SIZE = 5

    def __init__(self, root):
        self.catalog = RecordsCatalog(root)
        self.selected = None
        self.selected_game = None
        self.highlight_key = None
        self.offset = self.list_offset = self.date_offset = 0
        self.date = None
        self.choosing_date = False
        self.settings_side = None
        self.settings_offset = 0
        self.message = ""

    @property
    def summary(self):
        return self.catalog.get(self.selected)

    @property
    def options(self):
        if self.choosing_date:
            return [None] + self.catalog.dates
        return self.summary.games_on(self.date) if self.summary else self.catalog.on_date(self.date)

    def select(self, key):
        self.list_offset = self.offset
        self.selected = self.highlight_key = key
        self.offset = 0
        self.selected_game = None
        self.message = ""

    def scroll(self, amount):
        attr = "date_offset" if self.choosing_date else "offset"
        setattr(self, attr, max(0, min(getattr(self, attr) + amount, max(0, len(self.options) - self.PAGE_SIZE))))

    def back(self):
        if self.settings_side:
            self.settings_side = None
        elif self.choosing_date:
            self.choosing_date = False
        elif self.summary:
            self.selected = None
            self.offset = self.list_offset
            self.scroll(0)
        else:
            return False
        self.message = ""
        return True

    def action(self, action, app):
        if action == "comparison_new":
            if app.batch and not app.batch.future.done():
                self.message = "請先返回批次並停止目前對戰，再設定新增比較。"
                return
            app.new_setup("auto")
            app.batch_mode = "evaluation"
        elif action == "records_refresh":
            self.catalog.refresh()
            if self.selected and self.summary is None:
                self.selected = self.settings_side = None
                self.offset = self.list_offset
            self.scroll(0)
            self.message = ""
        elif action == "records_back":
            if not self.back():
                if app.records_return_mode:
                    app.mode = app.records_return_mode
                else:
                    app.request_leave("home")
        elif action == "records_dates":
            self.choosing_date = True
            self.date_offset = 0
        elif action.startswith("records_date:"):
            self.date = self.options[int(action.split(":")[1])]
            self.choosing_date = False
            self.offset = self.list_offset = 0
            self.highlight_key = None
        elif action.startswith("records_entry:"):
            self.select(self.options[int(action.split(":")[1])].key)
        elif action.startswith("records_settings:") and self.summary:
            self.settings_side = action.split(":")[1]
            self.settings_offset = 0
        elif action in ("records_prev", "records_next"):
            amount = -1 if action.endswith("prev") else 1
            if self.settings_side:
                self.settings_offset = max(0, self.settings_offset + amount * 18)
            else:
                self.scroll(amount * self.PAGE_SIZE)
        elif action.startswith("records_game:") and self.summary:
            game = self.options[int(action.split(":")[1])]
            self.selected_game = game.game_id
            if game.path is None:
                self.message = game.issue or "此局棋譜缺漏，結果仍保留。"
            elif not app.open_replay(game.path, return_to="records", record=game):
                self.message = app.message

    def render(self, app):
        app.text("對局紀錄", 64, 80, large=True)
        if self.settings_side:
            self._settings(app)
            return
        if self.summary and not self.choosing_date:
            self._summary(app)
        else:
            self._list(app)
        offset = self.date_offset if self.choosing_date else self.offset
        total = len(self.options)
        app.button("records_prev", "上一頁", (460, 672, 180, 40), enabled=offset > 0)
        app.button("records_next", "下一頁", (656, 672, 180, 40), enabled=offset + self.PAGE_SIZE < total)

    def _list(self, app):
        app.button("records_dates", "日期：" + (self.date or "全部"), (64, 124, 376, 36))
        options = self.options
        offset = self.date_offset if self.choosing_date else self.offset
        for row, index in enumerate(range(offset, min(len(options), offset + self.PAGE_SIZE))):
            item = options[index]
            y = 178 + row * 78
            if self.choosing_date:
                app.button(f"records_date:{index}", item or "全部日期", (64, y, 772, 64))
            else:
                app.button(f"records_entry:{index}", f"{KINDS[item.kind]}　{item.batch_id}　{item.name}",
                           (64, y, 772, 45), primary=item.key == self.highlight_key)
                app.draw_label(app.small_font, item.error or f"{len(item.games)} 局　｜　日期：{'、'.join(sorted(item.dates))}",
                               (64, y + 48), MUTED, 772)
        if not options:
            app.text("尚無已保存的對局紀錄。", 64, 196, muted=True)
        app.text(self.message or f"{offset + 1 if options else 0}–{min(len(options), offset + self.PAGE_SIZE)} / {len(options)} 筆", 64, 600, muted=True)
        app.button("records_back", "返回清單" if self.choosing_date else "返回", (64, 625, 180, 36))
        app.button("records_refresh", "重新整理", (64, 672, 180, 40))
        app.button("comparison_new", "新增比較", (258, 672, 180, 40), primary=True,
                   enabled=app.batch is None or app.batch.future.done())

    def _summary(self, app):
        summary, comparison = self.summary, self.summary.comparison
        app.text(f"{KINDS[summary.kind]}　{summary.batch_id}　{summary.name}", 64, 124, width=772)
        if comparison:
            candidate, baseline = comparison.participants["candidate"], comparison.participants["baseline"]
            app.text(f"候選：{candidate['label']} ({candidate['strategy']})　vs　基準：{baseline['label']} ({baseline['strategy']})", 64, 157, width=772)
            app.text(f"固定一般深度：{comparison.budget['depth_plies']} ply　｜　狀態：{present(STATES.get(summary.status, summary.status))}　｜　對局總耗時：{elapsed(summary.elapsed_seconds)}", 64, 190, width=772)
            rate = "無資料" if comparison.paired_score_rate is None else f"{comparison.paired_score_rate:.1%}"
            counts = dict(win=comparison.wins, draw=comparison.draws, loss=comparison.losses, unfinished=comparison.unfinished)
            app.text(f"候選方：{counts['win']} 勝　{counts['draw']} 和　{counts['loss']} 敗　{counts['unfinished']} 未完成　｜　完整配對得分率：{rate}", 64, 225, width=772)
            for x, side, label in ((64, "baseline", "基準完整設定"), (258, "candidate", "候選完整設定"), (452, "diff", "設定差異"), (646, "all", "批次保存設定")):
                app.button("records_settings:" + side, label, (x, 289, 180, 36))
            footer = f"完整配對：{comparison.completed_pairs}　｜　不完整配對：{comparison.incomplete_pairs}"
        else:
            def players(side):
                values = list(dict.fromkeys(game.white if side == "white" else game.black for game in summary.games))
                if values:
                    return "、".join(present(value) for value in values)
                strategies = (summary.settings or {}).get("strategies", {})
                saved = strategies.get(side, {}) if isinstance(strategies, dict) else {}
                return present(saved.get("strategy")) if isinstance(saved, dict) else "未記錄"
            app.text(f"白方：{players('white')}　｜　黑方：{players('black')}", 64, 157, width=772)
            app.text(f"狀態：{present(STATES.get(summary.status, summary.status))}　｜　對局總耗時：{elapsed(summary.elapsed_seconds)}", 64, 190, width=772)
            counts = summary.counts
            app.text(f"白勝 {counts['win']}　｜　和 {counts['draw']}　｜　黑勝 {counts['loss']}　｜　未完成 {counts['unfinished']}　｜　結果未記錄或損壞 {counts['unknown']}", 64, 225, width=772)
            app.button("records_settings:all", "保存設定", (64, 289, 220, 36))
            footer = f"已保存棋局：{len(summary.games)}"
        completed = sum(counts[k] for k in ("win", "draw", "loss"))
        x = 64
        for kind in ("win", "draw", "loss"):
            width = 772 * counts[kind] / completed if completed else 0
            if width:
                app.draw_rect(COLORS[kind], (x, 260, width, 14))
                x += width
        games = self.options
        for row, index in enumerate(range(self.offset, min(len(games), self.offset + self.PAGE_SIZE))):
            self._game_row(app, games[index], index, 342 + row * 49, comparison)
        app.draw_label(app.small_font, footer + f"　｜　日期：{self.date or '全部'}　｜　本頁 {self.offset + 1 if games else 0}–{min(len(games), self.offset + self.PAGE_SIZE)} / {len(games)} 局", (64, 596), MUTED, 772)
        hint = "得分率僅計完整配對；小樣本不代表棋力提升。點選棋局回放。" if comparison else "點選棋局回放；設定與統計均來自保存資料。"
        app.draw_label(app.small_font, self.message or summary.error or hint, (64, 625), MUTED, 772)
        app.button("records_back", "返回紀錄清單", (64, 672, 200, 40))

    def _game_row(self, app, game, index, y, comparison):
        detail = (f"候選執{'白' if game.candidate_color == 'white' else '黑'}　{OUTCOMES[game.outcome]}" if comparison
                  else f"{time_label(game.started_at)}　{present(game.white)}／{present(game.black)}　{RESULTS[game.result_kind]}")
        app.button(f"records_game:{index}", "", (64, y, 772, 43), enabled=game.path is not None,
                   primary=game.game_id == self.selected_game)
        app.draw_label(app.small_font, f"{game.game_id}　{detail}", (76, y + 2), TEXT, 748)
        reason = app.comparison_reason(game.termination) if game.termination else "未記錄"
        app.draw_label(app.small_font, f"耗時：{elapsed(game.elapsed_seconds)}　｜　結束原因：{reason}　{game.issue}",
                       (76, y + 22), MUTED, 748)

    def _settings(self, app):
        side = self.settings_side
        app.text({"candidate": "候選完整設定", "baseline": "基準完整設定", "diff": "基準與候選設定差異", "all": "保存設定"}[side], 64, 125)
        if side == "diff":
            def differences(left, right):
                result = {}
                for key in sorted(left.keys() | right.keys()):
                    if key == "label":
                        continue
                    a, b = left.get(key), right.get(key)
                    if isinstance(a, dict) and isinstance(b, dict):
                        children = differences(a, b)
                        if children:
                            result[key] = children
                    elif a != b:
                        result[key] = {"基準": a, "候選": b}
                return result
            payload = differences(self.summary.comparison.participants["baseline"], self.summary.comparison.participants["candidate"])
            payload = payload or {"說明": "雙方保存的設定相同（不比較名稱）"}
        elif side == "all":
            payload = self.summary.settings if self.summary.settings is not None else {"設定": "未記錄"}
        else:
            payload = self.summary.comparison.participants[side]
        # 依實際文字寬度換行，確保長字串也能完整讀取。
        lines = []
        for line in json.dumps(payload, ensure_ascii=False, indent=2).splitlines():
            current = ""
            for char in line:
                if app.small_font.size(current + char)[0] > round(772 * app.scale):
                    lines.append(current)
                    current = ""
                current += char
            lines.append(current)
        self.settings_offset = min(self.settings_offset, max(0, len(lines) - 18))
        for row, line in enumerate(lines[self.settings_offset:self.settings_offset + 18]):
            app.draw_label(app.small_font, line, (64, 174 + row * 24), TEXT)
        app.text(f"{self.settings_offset + 1}–{min(len(lines), self.settings_offset + 18)} / {len(lines)} 行（保存的實際設定）", 64, 622, muted=True)
        app.button("records_back", "返回結果", (64, 672, 200, 40))
        app.button("records_prev", "上一頁", (460, 672, 180, 40), enabled=self.settings_offset > 0)
        app.button("records_next", "下一頁", (656, 672, 180, 40), enabled=self.settings_offset + 18 < len(lines))
