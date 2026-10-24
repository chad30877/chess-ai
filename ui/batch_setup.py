"""批次設定中的評分比較欄位；啟動與進度交由共用批次入口。"""

import json
from pathlib import Path

import chess
import pygame

from engine.evaluation.config import EvaluationConfig
from ui.evaluation_profiles import profile_button
from engine.search.transposition import DEFAULT_TRANSPOSITION_CAPACITY
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, _normalized_positions


class EvaluationFields:
    def __init__(self, project):
        self.project = project
        self.files = sorted((project / "configs/evaluation").glob("*.json"))
        self.baseline = next((p for p in self.files if p.name == "stable.json"), self.files[0] if self.files else None)
        first_candidate = next((p for p in self.files if p.name == "example_tapered.json"), self.baseline)
        self.candidates = [first_candidate] if first_candidate else []
        self.values = dict(openings="", depth="2", repetitions="1", seed="10000", max_plies="",
                           name="", tags="", search_workers="1",
                           transposition_capacity=str(DEFAULT_TRANSPOSITION_CAPACITY))
        self.opening_lines = None
        self.opening_page = 0
        self.show_openings = False
        self.converted = None
        self.rules = []
        self.weight_mode = "actual"
        self.file_page = 0
        self.preview_page = 0
        self.generated = False
        self.preview = None
        self.preview_key = None
        self.weight_field = "piece_square.weight"
        self.values["weight_values"] = "0.5, 1, 1.5"
        self.focus = None
        self.draft = ""
        self.message = ""

    def commit(self):
        if self.focus:
            self.values[self.focus] = self.draft
        self.focus = None
        pygame.key.stop_text_input()

    def current_rule(self):
        rule = dict(field=self.weight_field, mode=self.weight_mode, values=self.values['weight_values'])
        if self.converted and self.converted[0] == (str(self.baseline), self.weight_field, self.weight_mode, self.values['weight_values']):
            rule['actual_values'] = self.converted[1]
        return rule

    def fingerprint(self):
        return (str(self.baseline), tuple(map(str, self.candidates)), json.dumps(self.opening_lines, sort_keys=True), tuple(sorted(self.values.items())), self.weight_field, self.weight_mode, json.dumps(self.rules, sort_keys=True))

    def options(self):
        self.commit()
        if self.generated:
            if self.preview is None or self.preview_key != self.fingerprint():
                raise ValueError("請重新預覽候選")
            if not self.preview.to_dict()['candidates']:
                raise ValueError("沒有有效候選")
            return self.preview.options(self.project / "data/batches")
        options = self.file_options()
        if self.opening_lines is not None:
            from engine.sessions.experiment import freeze_comparison
            return freeze_comparison(options).options(self.project / "data/batches")
        return options

    def file_options(self):
        self.commit()
        if self.baseline is None or (not self.generated and not self.candidates):
            raise ValueError("請先選擇一份基準與至少一份候選評分設定檔")
        if not self.generated and self.baseline in self.candidates:
            raise ValueError("同一份評分設定檔不能同時作為基準與候選")
        configs = [EvaluationConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
                   for p in ([] if self.generated else self.candidates)]
        baseline_config = EvaluationConfig.from_dict(json.loads(self.baseline.read_text(encoding="utf-8")))
        depth, repetitions, seed = [int(self.values[key]) for key in ("depth", "repetitions", "seed")]
        if repetitions < 1 or seed < 0:
            raise ValueError("每局面配對數需為正整數，種子需為非負整數")
        search = ComparisonSearchConfig(depth_plies=depth, search_workers=int(self.values["search_workers"]),
                                        transposition_capacity=int(self.values["transposition_capacity"]))
        fens = [chess.STARTING_FEN]
        if self.values["openings"].strip():
            path = Path(self.values["openings"].strip())
            if not path.is_absolute():
                path = self.project / path
            fens = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        fens = _normalized_positions(fens)
        maximum = int(self.values["max_plies"]) if self.values["max_plies"].strip() else None
        if maximum is not None and maximum < 0:
            raise ValueError("手數上限需為非負整數或留白")
        if self.opening_lines is not None:
            if self.values['openings'].strip():
                raise ValueError('請先切回 FEN 開局集，或清空路徑使用共同開局線')
            if repetitions != 1:
                raise ValueError('共同開局線每線固定交換黑白一次，配對數請設為 1')
            fens = [line['initial_fen'] for line in self.opening_lines]
        options = dict(baseline=ComparisonParticipant.alphabeta(self.baseline.stem, baseline_config, search=search),
                    candidates=[ComparisonParticipant.alphabeta(path.stem, config, search=search)
                                for path, config in zip(self.candidates, configs)],
                    initial_fens=tuple(fens), repetitions=repetitions, base_seed=seed,
                    batch_root=self.project / "data/batches", name=self.values["name"].strip() or None,
                    tags=[tag.strip() for tag in self.values["tags"].split(",") if tag.strip()],
                    max_plies=maximum, claim_draw=False)
        if self.opening_lines is not None:
            options['opening_lines'] = self.opening_lines
        return options

    def action(self, action, app):
        if action == "comparison_openings_generate":
            from engine.opening_book import OpeningBook
            from engine.opening_lines import common_opening_lines
            self.commit()
            try:
                self.opening_lines = common_opening_lines(OpeningBook())
                self.values.update(openings='', repetitions='1')
                self.opening_page = 0
                self.show_openings = True
                self.preview = None
                self.message = '已凍結 32 條共同開局線；每候選 64 局'
            except (ValueError, OSError) as exc:
                self.message = str(exc)
        elif action == "comparison_openings_view":
            self.show_openings = not self.show_openings
        elif action == "comparison_openings_clear":
            self.opening_lines = None
            self.show_openings = False
            self.preview = None
            self.message = ''
        elif action == "comparison_openings_next":
            self.opening_page = (self.opening_page + 1) % max(1, (len(self.opening_lines or []) + 6) // 7)
        elif action == "comparison_generated":
            self.commit()
            self.generated = not self.generated
            self.preview = None
        elif action == "comparison_rule_add":
            self.commit()
            self.rules = [r for r in self.rules if r['field'] != self.weight_field]
            self.rules.append(self.current_rule())
        elif action == "comparison_rule_clear":
            self.rules = []
        elif action == "comparison_preview_next":
            if self.preview:
                pages = max(1, (len(self.preview.to_dict()['candidates']) + 6) // 7)
                self.preview_page = (self.preview_page + 1) % pages
        elif action == "comparison_weight_mode":
            from engine.sessions.experiment import rule_values
            self.commit()
            try:
                config = EvaluationConfig.from_dict(json.loads(self.baseline.read_text(encoding="utf-8")))
                values = rule_values(config, self.current_rule())
                term, weight = self.weight_field.split('.')
                base = config.to_dict()['terms'][term][weight]
                if self.weight_mode == 'actual' and base == 0:
                    raise ValueError('零基準請使用實際值')
                self.weight_mode = 'percent' if self.weight_mode == 'actual' else 'actual'
                self.values['weight_values'] = ', '.join(repr(value * 100 / base if self.weight_mode == 'percent' else value) for value in values)
                self.converted = ((str(self.baseline), self.weight_field, self.weight_mode, self.values['weight_values']), values)
            except (ValueError, OSError) as exc:
                self.message = str(exc)
        elif action == "comparison_weight":
            from engine.sessions.experiment import enabled_weight_fields
            self.commit()
            config = EvaluationConfig.from_dict(json.loads(self.baseline.read_text(encoding="utf-8")))
            fields = enabled_weight_fields(config)
            self.weight_field = fields[(fields.index(self.weight_field) + 1) % len(fields)] if self.weight_field in fields else (fields[0] if fields else "")
        elif action == "comparison_preview":
            from engine.sessions.experiment import build_experiment
            self.preview = None
            try:
                options = self.file_options()
                rules = [r for r in self.rules if r['field'] != self.weight_field]
                rules.append(self.current_rule())
                self.preview = build_experiment(options, rules=rules)
                self.preview_page = 0
                self.preview_key = self.fingerprint()
                data = self.preview.to_dict()
                self.message = f"候選 {len(data['candidates'])}／對局 {data['planned_games']}／重複 {data['duplicate_count']}／同基準 {data['baseline_count']}"
            except (ValueError, OSError) as exc:
                self.message = str(exc)
        elif action.startswith("comparison_file:"):
            self.commit()
            side = action.split(":")[1]
            if self.files:
                current = getattr(self, side)
                setattr(self, side, self.files[(self.files.index(current) + 1) % len(self.files)])
        elif action == "comparison_files_next":
            self.file_page = (self.file_page + 1) % max(1, (len(self.candidates) + 6) // 7)
        elif action == "comparison_files_prev":
            self.file_page = max(0, self.file_page - 1)
        elif action == "comparison_candidate_add":
            self.commit()
            available = [path for path in self.files if path != self.baseline and path not in self.candidates]
            if available:
                self.candidates.append(available[0])
                self.file_page = (len(self.candidates) - 1) // 7
        elif action.startswith("comparison_candidate_select:"):
            index = int(action.split(":")[1])
            if 0 <= index < len(self.candidates):
                current = self.candidates[index]
                available = [path for path in self.files
                             if path != self.baseline and (path == current or path not in self.candidates)]
                if available:
                    current_index = available.index(current) if current in available else -1
                    self.candidates[index] = available[(current_index + 1) % len(available)]
        elif action.startswith("comparison_candidate_remove:"):
            index = int(action.split(":")[1])
            if 0 <= index < len(self.candidates) and len(self.candidates) > 1:
                self.candidates.pop(index)
                self.file_page = min(self.file_page, (len(self.candidates) - 1) // 7)
        elif action.startswith("comparison_field:"):
            self.commit()
            self.focus = action.split(":")[1]
            self.draft = self.values[self.focus]
            pygame.key.start_text_input()

    def render(self, app):
        app.text("Ctrl+A 清空，Enter 確認。", 64, 158, muted=True)
        fields = [("baseline", "基準"), ("openings", "開局集路徑"), ("depth", "搜尋深度（ply）"),
                  ("search_workers", "搜尋 worker"), ("transposition_capacity", "表項上限"),
                  ("repetitions", "每局面配對數"), ("seed", "種子"), ("max_plies", "手數上限"),
                  ("name", "批次名稱"), ("tags", "標籤")]
        for index, (key, label) in enumerate(fields):
            x, y = 64, 199 + 42 * index
            app.draw_label(app.small_font, label, (x, y + 8), width=122)
            if key == "baseline":
                path = getattr(self, key)
                value = ""
                action = f"comparison_file:{key}"
            else:
                value = (self.draft + " |") if self.focus == key else (self.values[key] or "（留白）")
                action = f"comparison_field:{key}"
            if key == "baseline":
                profile_button(app, action, path, (x + 128, y, 248, 38))
            else:
                app.button(action, value, (x + 128, y, 248, 38), primary=self.focus == key)
        app.button("comparison_generated", "權重實驗" if self.generated else "設定檔比較", (460, 158, 376, 32))
        if self.show_openings:
            lines = self.opening_lines or []
            app.text(f'共同開局線 {len(lines)} 條／每候選 {len(lines)*2} 局', 460, 201, width=376)
            for index, line in enumerate(lines[self.opening_page*7:(self.opening_page+1)*7]):
                app.text(f"{self.opening_page*7+index+1}. {line['eco']} {line['name']}", 460, 236+index*40, width=376)
                app.draw_label(app.small_font, ' '.join(line['moves_uci']), (460, 258+index*40), width=376)
            app.button('comparison_openings_next', '下一頁', (460, 540, 180, 32), enabled=len(lines)>7)
            app.button('comparison_openings_clear', '改用 FEN 開局集', (650, 540, 186, 32))
        elif self.generated:
            app.button("comparison_weight", self.weight_field or "無已啟用權重", (460, 205, 376, 36))
            value = self.draft + " |" if self.focus == "weight_values" else self.values['weight_values']
            app.button("comparison_field:weight_values", value, (460, 247, 376, 36))
            app.button("comparison_weight_mode", "實際值" if self.weight_mode == 'actual' else "基準百分比", (460, 289, 120, 32))
            app.button("comparison_rule_add", f"加入權重（{len(self.rules)}）", (586, 289, 150, 32))
            app.button("comparison_rule_clear", "清除", (742, 289, 94, 32))
            app.text("清單：1,2,3　範圍：起點:終點:間隔", 460, 325, width=376, muted=True)
            app.button("comparison_preview", "預覽候選", (460, 355, 240, 32))
            app.button("comparison_preview_next", "下一頁", (710, 355, 126, 32))
            if self.preview and self.preview_key == self.fingerprint():
                candidates = self.preview.to_dict()['candidates']
                for index, candidate in enumerate(candidates[self.preview_page * 7:(self.preview_page + 1) * 7]):
                    app.text(candidate['label'], 460, 396 + index * 30, width=376)
        else:
            app.draw_label(app.small_font, "候選評分設定檔（各自與基準交換黑白比較）", (460, 199), width=376)
            offset = self.file_page * 7
            for index, path in enumerate(self.candidates[offset:offset + 7], offset):
                y = 226 + (index - offset) * 38
                profile_button(app, f"comparison_candidate_select:{index}", path, (460, y, 315, 32))
                app.button(f"comparison_candidate_remove:{index}", "移除", (780, y, 56, 32))
            app.button("comparison_candidate_add", "加入下一份不同設定檔",
                       (460, 500, 376, 32),
                       enabled=any(
                           path != self.baseline and path not in self.candidates for path in self.files))
            app.button("comparison_files_prev", "上一頁", (460, 540, 180, 32), enabled=self.file_page > 0)
            app.button("comparison_files_next", "下一頁", (650, 540, 186, 32), enabled=(self.file_page + 1) * 7 < len(self.candidates))
        app.button('comparison_openings_generate', '產生 32 條共同開局線', (64, 672, 240, 40))
        app.button('comparison_openings_view', '返回設定' if self.show_openings else '查看開局',
                   (314, 672, 126, 40), enabled=self.opening_lines is not None)
        if self.message:
            app.text(self.message, 64, 642, muted=True, width=772)
        app.button("start", "開始生成", (460, 672, 376, 40), primary=True)
