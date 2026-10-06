"""Read-only comparison result screens, sharing the application's scaled controls."""

import json

from engine.replay.comparison_catalog import ComparisonCatalog
from ui.controls import MUTED, TEXT


OUTCOMES = {"win": "勝", "draw": "和", "loss": "敗", "unfinished": "未完成"}
COLORS = {"win": (108, 210, 158), "draw": (163, 175, 191),
          "loss": (130, 153, 183), "unfinished": (239, 184, 89)}


class ComparisonView:
    PAGE_SIZE = 5

    def __init__(self, root):
        self.catalog = ComparisonCatalog(root)
        self.selected = None
        self.offset = 0
        self.settings_side = None
        self.settings_offset = 0
        self.message = ""

    @property
    def summary(self):
        return self.catalog.entries[self.selected] if self.selected is not None else None

    def scroll(self, amount):
        total = len(self.summary.games) if self.summary else len(self.catalog.entries) + len(self.catalog.errors)
        self.offset = max(0, min(self.offset + amount, max(0, total - self.PAGE_SIZE)))

    def action(self, action, app):
        if action == "comparison_refresh":
            self.catalog.refresh()
            self.selected = None
            self.offset = 0
            self.settings_side = None
            self.message = ""
        elif action == "comparison_back":
            if self.settings_side:
                self.settings_side = None
            else:
                self.selected = None
                self.offset = 0
            self.message = ""
        elif action.startswith("comparison_batch:"):
            self.selected = int(action.split(":")[1])
            self.offset = 0
            self.message = ""
        elif action.startswith("comparison_settings:"):
            self.settings_side = action.split(":")[1]
            self.settings_offset = 0
        elif action in ("comparison_prev", "comparison_next"):
            if self.settings_side:
                self.settings_offset = max(0, self.settings_offset + (-18 if action.endswith("prev") else 18))
            else:
                self.scroll(-self.PAGE_SIZE if action.endswith("prev") else self.PAGE_SIZE)
        elif action.startswith("comparison_game:") and self.summary:
            game = self.summary.games[int(action.split(":")[1])]
            if game.path is None:
                self.message = "此局棋譜缺漏，結果仍保留。"
            elif not app.open_replay(game.path):
                self.message = app.message

    def render(self, app):
        app.text("棋力比較", 64, 80, large=True)
        if self.settings_side:
            self._settings(app)
            return
        summary = self.summary
        if summary is None:
            app.text("選擇已保存的比較批次", 64, 127, muted=True)
            entries = self.catalog.entries
            total = len(entries) + len(self.catalog.errors)
            for row, index in enumerate(range(self.offset, min(total, self.offset + self.PAGE_SIZE))):
                y = 178 + row * 78
                if index < len(entries):
                    item = entries[index]
                    app.button(f"comparison_batch:{index}", f"{item.batch_id}　{item.name}", (64, y, 772, 64))
                else:
                    error = self.catalog.errors[index - len(entries)]
                    app.draw_label(app.small_font, error, (64, y + 8), COLORS["unfinished"], 772)
                    app.text("此批次無法顯示比較摘要；可用棋譜回放查找已保存棋局。", 64, y + 33, muted=True, width=772)
            if not total:
                app.text("尚無比較結果。請先以比較 CLI 產生批次。", 64, 196, muted=True)
            app.text(f"{len(entries)} 個比較批次　｜　{len(self.catalog.errors)} 筆資料問題", 64, 600, muted=True)
            app.button("comparison_refresh", "重新整理", (64, 672, 180, 40))
        else:
            app.text(f"{summary.batch_id}　{summary.name}", 64, 124, width=772)
            candidate, baseline = summary.participants["candidate"], summary.participants["baseline"]
            app.text(f"候選：{candidate['label']} ({candidate['strategy']})　vs　基準：{baseline['label']} ({baseline['strategy']})", 64, 157, width=772)
            status = {"completed": "完成", "generating": "產生中", "stopped": "已停止", "failed": "失敗"}.get(summary.status, summary.status)
            app.text(f"固定一般深度：{summary.budget['depth_plies']} ply　｜　批次：{status}　｜　對局總耗時：{summary.elapsed_seconds:.3f} 秒", 64, 190, width=772)
            rate = "無資料" if summary.score_rate is None else f"{summary.score_rate:.1%}"
            app.text(f"候選方：{summary.wins} 勝　{summary.draws} 和　{summary.losses} 敗　{summary.unfinished} 未完成　｜　得分率：{rate}", 64, 225, width=772)
            completed = summary.wins + summary.draws + summary.losses
            x = 64
            for outcome, count in (("win", summary.wins), ("draw", summary.draws), ("loss", summary.losses)):
                width = 772 * count / completed if completed else 0
                if width:
                    app.draw_rect(COLORS[outcome], (x, 260, width, 14))
                    x += width
            app.button("comparison_settings:baseline", "基準完整設定", (64, 289, 220, 36))
            app.button("comparison_settings:candidate", "候選完整設定", (300, 289, 220, 36))
            for row, index in enumerate(range(self.offset, min(len(summary.games), self.offset + self.PAGE_SIZE))):
                game = summary.games[index]
                y = 342 + row * 49
                reason = app.comparison_reason(game.termination)
                label = f"{game.game_id}　候選執{'白' if game.candidate_color == 'white' else '黑'}　{OUTCOMES[game.outcome]}　{game.elapsed_seconds:.3f}s　{reason}"
                if game.path is None:
                    label += "　棋譜缺漏"
                app.button(f"comparison_game:{index}", label, (64, y, 772, 43), enabled=game.path is not None)
            app.draw_label(app.small_font, self.message or "點選棋局回放。得分率僅計正常完成對局；小樣本不代表棋力提升。", (64, 610), MUTED, 772)
            app.button("comparison_back", "返回批次清單", (64, 672, 200, 40))
            total = len(summary.games)
        app.button("comparison_prev", "上一頁", (460, 672, 180, 40), enabled=self.offset > 0)
        app.button("comparison_next", "下一頁", (656, 672, 180, 40), enabled=self.offset + self.PAGE_SIZE < total)

    def _settings(self, app):
        side = self.settings_side
        app.text("候選完整設定" if side == "candidate" else "基準完整設定", 64, 125)
        # Wrap by rendered width so every saved value is reachable, including long strings.
        lines = []
        for line in json.dumps(self.summary.participants[side], ensure_ascii=False, indent=2).splitlines():
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
        app.button("comparison_back", "返回結果", (64, 672, 200, 40))
        app.button("comparison_prev", "上一頁", (460, 672, 180, 40), enabled=self.settings_offset > 0)
        app.button("comparison_next", "下一頁", (656, 672, 180, 40), enabled=self.settings_offset + 18 < len(lines))
