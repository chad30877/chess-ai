"""批次設定中的評分比較欄位；啟動與進度交由共用批次入口。"""

import json
from pathlib import Path

import chess
import pygame

from engine.evaluation.config import EvaluationConfig
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, _normalized_positions


class EvaluationFields:
    def __init__(self, project):
        self.project = project
        self.files = sorted((project / "configs/evaluation").glob("*.json"))
        self.baseline = next((p for p in self.files if p.name == "stable.json"), self.files[0] if self.files else None)
        self.candidate = next((p for p in self.files if p.name == "example_tapered.json"), self.baseline)
        self.values = dict(openings="", depth="2", repetitions="1", seed="10000", max_plies="",
                           name="", tags="")
        self.focus = None
        self.draft = ""
        self.message = ""

    def commit(self):
        if self.focus:
            self.values[self.focus] = self.draft
        self.focus = None
        pygame.key.stop_text_input()

    def options(self):
        self.commit()
        if self.baseline is None or self.candidate is None:
            raise ValueError("請先在 configs/evaluation 放入基準與候選設定檔")
        configs = [EvaluationConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
                   for p in (self.baseline, self.candidate)]
        depth, repetitions, seed = [int(self.values[key]) for key in ("depth", "repetitions", "seed")]
        if repetitions < 1 or seed < 0:
            raise ValueError("每局面配對數需為正整數，種子需為非負整數")
        search = ComparisonSearchConfig(depth_plies=depth)
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
        return dict(baseline=ComparisonParticipant.alphabeta("baseline", configs[0], search=search),
                    candidate=ComparisonParticipant.alphabeta("candidate", configs[1], search=search),
                    initial_fens=tuple(fens), repetitions=repetitions, base_seed=seed,
                    batch_root=self.project / "data/batches", name=self.values["name"].strip() or None,
                    tags=[tag.strip() for tag in self.values["tags"].split(",") if tag.strip()],
                    max_plies=maximum, claim_draw=False)

    def action(self, action, app):
        if action.startswith("comparison_file:"):
            self.commit()
            side = action.split(":")[1]
            if self.files:
                current = getattr(self, side)
                setattr(self, side, self.files[(self.files.index(current) + 1) % len(self.files)])
        elif action.startswith("comparison_field:"):
            self.commit()
            self.focus = action.split(":")[1]
            self.draft = self.values[self.focus]
            pygame.key.start_text_input()

    def render(self, app):
        app.text("點選設定檔切換；文字欄位 Ctrl+A 清空，Enter 確認。", 64, 158, muted=True)
        fields = [("baseline", "基準設定檔"), ("candidate", "候選設定檔"),
                  ("openings", "開局集路徑（留白為標準開局）"), ("depth", "一般搜尋深度（ply）"),
                  ("repetitions", "每局面配對數（每對兩局）"), ("seed", "種子"),
                  ("max_plies", "手數上限（留白無上限）"), ("name", "批次名稱"), ("tags", "標籤（以逗號分隔）")]
        for index, (key, label) in enumerate(fields):
            x, y = 64 + 396 * (index % 2), 199 + 79 * (index // 2)
            app.draw_label(app.small_font, label, (x, y), width=376)
            if key in ("baseline", "candidate"):
                path = getattr(self, key)
                value = path.name if path else "沒有設定檔"
                action = f"comparison_file:{key}"
            else:
                value = (self.draft + " |") if self.focus == key else (self.values[key] or "（留白）")
                action = f"comparison_field:{key}"
            app.button(action, value, (x, y + 25, 376, 39), primary=self.focus == key)
        app.text(self.message or "雙方使用相同搜尋設定，交換黑白；和棋政策為不自動申請。", 64, 611, muted=True, width=772)
        app.button("start", "開始生成", (460, 672, 376, 40), primary=True)
