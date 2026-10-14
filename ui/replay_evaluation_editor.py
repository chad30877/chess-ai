"""可編輯回放評分草稿；不修改原棋譜或來源設定檔。"""

import math

from engine.evaluation.config import EvaluationConfig


GROUPS = (
    ("material", "子力", ("material",)),
    ("piece_square", "棋子位置", ("piece_square",)),
    ("phase", "分階段", ("phase",)),
    ("pawn", "兵形", ("isolated_pawns", "doubled_pawns", "passed_pawns")),
    ("mobility", "活動力", ("pawn_mobility", "knight_mobility", "bishop_mobility",
                              "rook_mobility", "queen_mobility", "king_mobility")),
    ("king_safety", "國王安全", ("king_pawn_shield", "king_zone_attacks", "king_file_exposure")),
    ("coordination", "協調", ("bishop_pair", "rook_open_file", "rook_half_open_file")),
)


TERM_LABELS = {
    "material": "子力", "piece_square": "位置",
    "isolated_pawns": "孤兵", "doubled_pawns": "疊兵", "passed_pawns": "通路兵",
    "pawn_mobility": "兵活動力", "knight_mobility": "馬活動力",
    "bishop_mobility": "象活動力", "rook_mobility": "車活動力",
    "queen_mobility": "后活動力", "king_mobility": "王活動力",
    "king_pawn_shield": "王兵盾", "king_zone_attacks": "王區攻擊",
    "king_file_exposure": "王線暴露", "bishop_pair": "雙象",
    "rook_open_file": "車開放線", "rook_half_open_file": "車半開放線",
}


class ReplayEvaluationEditor:
    """A mutable draft backed by the immutable EvaluationConfig value object."""

    def __init__(self, config: EvaluationConfig):
        self.config = EvaluationConfig.from_dict(config.to_dict())
        self.name = ""
        self.focus = None
        self.input_draft = ""
        self.scroll = 0
        self.message = ""
        payload = self.config.to_dict()
        self.expanded = {
            key: self._group_is_enabled(payload, terms)
            for key, _, terms in GROUPS
        }

    @staticmethod
    def _group_is_enabled(payload, terms):
        if terms == ("phase",):
            return payload["phase"]["enabled"]
        return any(payload["terms"][term]["enabled"] for term in terms)

    def fields(self):
        payload = self.config.to_dict()
        fields = []
        material = payload["terms"]["material"]
        fields.append(("material", "子力評分", "terms.material.enabled", material["enabled"], "toggle"))
        for symbol, label in (("P", "兵"), ("N", "馬"), ("B", "象"), ("R", "車"), ("Q", "后")):
            fields.append(("material", f"{label}價值", f"terms.material.piece_values.{symbol}",
                           material["piece_values"][symbol], "number"))

        position = payload["terms"]["piece_square"]
        for label, key in (("位置評分", "enabled"), ("中局倍率", "weight"),
                           ("殘局倍率", "endgame_weight")):
            kind = "toggle" if key == "enabled" else "number"
            fields.append(("piece_square", label, f"terms.piece_square.{key}", position[key], kind))
        fields.append(("phase", "中局／殘局混合", "phase.enabled", payload["phase"]["enabled"], "toggle"))

        term_groups = {term: group for group, _, terms in GROUPS for term in terms}
        for term, settings in payload["terms"].items():
            if term in ("material", "piece_square"):
                continue
            group = term_groups[term]
            fields.append((group, TERM_LABELS[term], f"terms.{term}.enabled", settings["enabled"], "toggle"))
            fields.append((group, "中局倍率", f"terms.{term}.weight", settings["weight"], "number"))
            fields.append((group, "殘局倍率", f"terms.{term}.endgame_weight",
                           settings["endgame_weight"], "number"))
        return fields

    def set_value(self, path: str, value):
        payload = self.config.to_dict()
        target = payload
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        self.config = EvaluationConfig.from_dict(payload)

    def toggle(self, path: str):
        fields = {field[2]: field[3] for field in self.fields()}
        self.set_value(path, not fields[path])
        self.message = ""

    def begin_edit(self, path: str):
        if path == "name":
            self.input_draft = self.name
        else:
            fields = {field[2]: field[3] for field in self.fields()}
            self.input_draft = str(fields[path])
        self.focus = path

    def commit_edit(self):
        if self.focus is None:
            return True
        path, raw = self.focus, self.input_draft.strip()
        try:
            if path == "name":
                self.name = raw
            else:
                value = float(raw)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
                self.set_value(path, value)
            self.focus = None
            self.message = ""
            return True
        except (ValueError, TypeError, KeyError):
            self.message = "請輸入有限的非負數值。"
            return False

    def cancel_edit(self):
        self.focus = None

    def visible_fields(self):
        return [field for field in self.fields() if self.expanded[field[0]]]
