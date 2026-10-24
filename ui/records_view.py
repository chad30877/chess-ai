"""三種對局資料共用的清單、摘要、設定與回放導覽。"""

import json
from uuid import uuid4
from datetime import datetime
from engine.evaluation.config import EvaluationConfig

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
        self.candidate_index = None
        self.candidate_offset = 0
        self.sort_key = "wins"
        self.sort_reverse = False

    @property
    def candidates(self):
        rows = list(enumerate(self.summary.comparison.candidate_summaries))
        known = [(i, row) for i, row in rows if row.get(self.sort_key) is not None]
        unknown = [(i, row) for i, row in rows if row.get(self.sort_key) is None]
        return sorted(known, key=lambda item: item[1][self.sort_key], reverse=self.sort_reverse) + unknown

    @property
    def candidate(self):
        comparison = self.summary.comparison
        return comparison.participants.get("candidates", [comparison.participants["candidate"]])[self.candidate_index or 0]

    @property
    def summary(self):
        return self.catalog.get(self.selected)

    @property
    def options(self):
        if self.choosing_date:
            return [None] + self.catalog.dates
        games = self.summary.games_on(self.date) if self.summary else self.catalog.on_date(self.date)
        if self.summary and self.summary.comparison and self.candidate_index is not None:
            ids = {g.game_id for g in self.summary.comparison.games if g.candidate_index == self.candidate_index}
            return tuple(g for g in games if g.game_id in ids)
        return games

    def select(self, key):
        self.candidate_index = None
        self.candidate_offset = 0
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
        if action == 'records_learning_report' and self.summary:
            try:
                plan_id=self.summary.settings['experiment']['learning_source']['plan_id']
                app.learning.comparison.open_plan(self.catalog.root/'learning-comparisons'/plan_id)
                app.learning.page='comparison'; app.mode='learning'
            except (OSError,ValueError,KeyError,TypeError) as exc: self.message=str(exc)
            return
        if action.startswith("records_sort:"):
            key = action.split(":")[1]
            self.sort_reverse = not self.sort_reverse if key == self.sort_key else False
            self.sort_key = key
            self.candidate_offset = 0
        elif action.startswith("records_candidate:"):
            self.candidate_index = int(action.split(":")[1])
            self.offset = 0
        elif action.startswith("records_candidates_"):
            self.candidate_offset += 2 if action.endswith("next") else -2
            self.candidate_offset = max(0, min(self.candidate_offset, max(0, len(self.candidates) - 2)))
        elif action == "records_save_candidate":
            try:
                config = EvaluationConfig.from_dict({key: value for key, value in self.candidate["evaluator"].items() if key != "type"})
                directory = app.evaluation_fields.baseline.parent if app.evaluation_fields.baseline else app.live_evaluation_file.parent
                path = directory / f"candidate-{uuid4().hex[:12]}.json"
                with path.open("x", encoding="utf-8") as stream:
                    json.dump(config.to_dict(), stream, ensure_ascii=False, indent=2)
                app._refresh_evaluation_profiles()
                self.message = f"已另存：{path.stem}"
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.message = f"無法另存：{exc}"
            return
        elif action == "comparison_new":
            if app.batch and not app.batch.future.done():
                self.message = "請先返回批次並停止目前對戰，再設定新增比較。"
                return
            app.new_setup("auto")
            app.batch_mode = "evaluation"
        elif action == "records_resume" and self.summary:
            if app.batch and not app.batch.future.done():
                self.message = "請先停止目前對戰"
                return
            try:
                from engine.sessions.experiment_resume import resume_options
                from engine.sessions.comparison_run import ComparisonRun
                options = resume_options(self.catalog.root / "batches" / self.summary.batch_id)
                app.batch = ComparisonRun(options, app.executor)
                app.batch_mode = "evaluation"
                app.mode = "auto"
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.message = f"無法續跑：{exc}"
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
            baseline = comparison.participants["baseline"]
            app.text(f"基準：{baseline['label']} ({baseline['strategy']})　｜　固定一般深度：{comparison.budget['depth_plies']} ply", 64, 157, width=772)
            app.text(f"{present(STATES.get(summary.status, summary.status))}　｜　累積對局：{elapsed(comparison.elapsed_seconds)}　｜　實驗經過：{elapsed(comparison.experiment_elapsed_seconds)}", 64, 190, width=772)
            counts = dict(win=comparison.wins, draw=comparison.draws, loss=comparison.losses, unfinished=comparison.unfinished)
            columns = (("wins", "勝"), ("draws", "和"), ("losses", "敗"), ("paired_score_rate", "配對得分率"), ("completed_pairs", "完整配對"), ("unfinished", "未完成"), ("elapsed_seconds", "累積秒"))
            for column, (key, label) in enumerate(columns):
                app.button("records_sort:" + key, label, (254 + column * 70, 220, 68, 26))
            app.button("records_candidates_prev", "上一組", (64, 220, 88, 26), enabled=self.candidate_offset > 0)
            app.button("records_candidates_next", "下一組", (156, 220, 88, 26), enabled=self.candidate_offset + 2 < len(self.candidates))
            for row, (index, candidate) in enumerate(self.candidates[self.candidate_offset:self.candidate_offset + 2]):
                y = 250 + row * 34
                rate = "無資料" if candidate["paired_score_rate"] is None else f"{candidate['paired_score_rate']:.1%}"
                app.button(f"records_candidate:{index}", candidate["label"], (64, y, 182, 32), primary=index == self.candidate_index)
                values = (candidate["wins"], candidate["draws"], candidate["losses"], rate, candidate["completed_pairs"], candidate["unfinished"], f"{candidate['elapsed_seconds']:.2f}")
                for column, value in enumerate(values):
                    app.draw_label(app.small_font, str(value), (254 + column * 70, y), TEXT, 68)
                app.draw_label(app.small_font, f"不完整配對 {candidate['incomplete_pairs']}　{candidate['differences']}", (254, y + 16), MUTED, 570)
            for x, side, label in ((64, "baseline", "基準設定"), (218, "candidate", "候選設定"), (372, "diff", "設定差異"), (526, "all", "批次設定")):
                app.button("records_settings:" + side, label, (x, 322, 148, 36))
            app.button("records_save_candidate", "另存候選", (680, 322, 156, 36), enabled=self.candidate_index is not None and isinstance(self.candidate.get("evaluator"), dict))
            footer = "候選各自計算；得分率不含未完成配對。"
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
        if not comparison:
            completed = sum(counts[k] for k in ("win", "draw", "loss"))
            x = 64
            for kind in ("win", "draw", "loss"):
                width = 772 * counts[kind] / completed if completed else 0
                if width:
                    app.draw_rect(COLORS[kind], (x, 260, width, 14))
                    x += width
        games = self.options
        for row, index in enumerate(range(self.offset, min(len(games), self.offset + self.PAGE_SIZE))):
            self._game_row(app, games[index], index, (370 if comparison else 342) + row * 43, comparison)
        app.draw_label(app.small_font, footer + f"　｜　日期：{self.date or '全部'}　｜　本頁 {self.offset + 1 if games else 0}–{min(len(games), self.offset + self.PAGE_SIZE)} / {len(games)} 局", (64, 596), MUTED, 772)
        hint = "得分率僅計各候選的完整配對；結果不作最佳設定排名。點選棋局回放。" if comparison else "點選棋局回放；設定與統計均來自保存資料。"
        app.draw_label(app.small_font, self.message or summary.error or hint, (64, 625), MUTED, 772)
        app.button("records_back", "返回紀錄清單", (64, 672, 200, 40))
        if (summary.settings or {}).get("experiment"):
            app.button("records_resume", "續跑實驗", (280, 672, 180, 40),
                       enabled=app.batch is None or app.batch.future.done())
            if summary.settings['experiment'].get('learning_source'):
                app.button('records_learning_report','學習研究報告',(480,672,210,40))

    def _game_row(self, app, game, index, y, comparison):
        detail = (f"{game.candidate_label}執{'白' if game.candidate_color == 'white' else '黑'}　{OUTCOMES[game.outcome]}" if comparison
                  else f"{time_label(game.started_at)}　{present(game.white)}／{present(game.black)}　{RESULTS[game.result_kind]}")
        app.button(f"records_game:{index}", "", (64, y, 772, 43), enabled=game.path is not None,
                   primary=game.game_id == self.selected_game)
        if comparison and game.historical:
            detail = "中斷嘗試｜" + detail
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
            payload = differences(self.summary.comparison.participants["baseline"], self.candidate)
            payload = payload or {"說明": "雙方保存的設定相同（不比較名稱）"}
        elif side == "all":
            payload = self.summary.settings if self.summary.settings is not None else {"設定": "未記錄"}
        else:
            payload = self.candidate if side == "candidate" else self.summary.comparison.participants[side]
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
