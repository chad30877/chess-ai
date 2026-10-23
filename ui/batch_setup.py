"""批次設定中的評分比較欄位；啟動與進度交由共用批次入口。"""

import json
from pathlib import Path

import chess
import pygame

from engine.evaluation.config import EvaluationConfig
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

    def fingerprint(self):
        return (str(self.baseline), tuple(sorted(self.values.items())), self.weight_field)

    def options(self):
        self.commit()
        if self.generated:
            if self.preview is None or self.preview_key != self.fingerprint():
                raise ValueError("請重新預覽候選")
            if not self.preview.to_dict()['candidates']:
                raise ValueError("沒有有效候選")
            return self.preview.options(self.project / "data/batches")
        return self.file_options()

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
        return dict(baseline=ComparisonParticipant.alphabeta(self.baseline.stem, baseline_config, search=search),
                    candidates=[ComparisonParticipant.alphabeta(path.stem, config, search=search)
                                for path, config in zip(self.candidates, configs)],
                    initial_fens=tuple(fens), repetitions=repetitions, base_seed=seed,
                    batch_root=self.project / "data/batches", name=self.values["name"].strip() or None,
                    tags=[tag.strip() for tag in self.values["tags"].split(",") if tag.strip()],
                    max_plies=maximum, claim_draw=False)

    def action(self, action, app):
        if action == "comparison_generated":
            self.commit()
            self.generated = not self.generated
            self.preview = None
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
                self.preview = build_experiment(options, self.weight_field, self.values['weight_values'])
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
        elif action == "comparison_candidate_add":
            self.commit()
            available = [path for path in self.files if path != self.baseline and path not in self.candidates]
            if available and len(self.candidates) < 7:
                self.candidates.append(available[0])
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
        elif action.startswith("comparison_field:"):
            self.commit()
            self.focus = action.split(":")[1]
            self.draft = self.values[self.focus]
            pygame.key.start_text_input()

    def render(self, app):
        app.text("點選候選設定檔切換；文字欄位 Ctrl+A 清空，Enter 確認。", 64, 158, muted=True)
        fields = [("baseline", "基準"), ("openings", "開局集路徑"), ("depth", "搜尋深度（ply）"),
                  ("search_workers", "搜尋 worker"), ("transposition_capacity", "表項上限"),
                  ("repetitions", "每局面配對數"), ("seed", "種子"), ("max_plies", "手數上限"),
                  ("name", "批次名稱"), ("tags", "標籤")]
        for index, (key, label) in enumerate(fields):
            x, y = 64, 199 + 42 * index
            app.draw_label(app.small_font, label, (x, y + 8), width=122)
            if key == "baseline":
                path = getattr(self, key)
                value = path.name if path else "沒有設定檔"
                action = f"comparison_file:{key}"
            else:
                value = (self.draft + " |") if self.focus == key else (self.values[key] or "（留白）")
                action = f"comparison_field:{key}"
            app.button(action, value, (x + 128, y, 248, 38), primary=self.focus == key)
        app.button("comparison_generated", "權重實驗" if self.generated else "設定檔比較", (460, 158, 376, 32))
        if self.generated:
            app.button("comparison_weight", self.weight_field or "無已啟用權重", (460, 205, 376, 36))
            value = self.draft + " |" if self.focus == "weight_values" else self.values['weight_values']
            app.button("comparison_field:weight_values", value, (460, 247, 376, 36))
            app.button("comparison_preview", "預覽候選", (460, 289, 376, 36))
            if self.preview and self.preview_key == self.fingerprint():
                candidates = self.preview.to_dict()['candidates']
                for index, candidate in enumerate(candidates[:7]):
                    app.text(candidate['label'], 460, 335 + index * 30, width=376)
        else:
            app.draw_label(app.small_font, "候選評分設定檔（各自與基準交換黑白比較）", (460, 199), width=376)
            for index, path in enumerate(self.candidates[:7]):
                y = 226 + index * 38
                app.button(f"comparison_candidate_select:{index}", path.name, (460, y, 315, 32))
                app.button(f"comparison_candidate_remove:{index}", "移除", (780, y, 56, 32))
            app.button("comparison_candidate_add", "加入下一份不同設定檔",
                       (460, min(226 + len(self.candidates[:7]) * 38, 492), 376, 32),
                       enabled=len(self.candidates) < 7 and any(
                           path != self.baseline and path not in self.candidates for path in self.files))
        if self.message:
            app.text(self.message, 64, 642, muted=True, width=772)
        app.button("start", "開始生成", (460, 672, 376, 40), primary=True)
