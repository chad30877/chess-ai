"""依實際啟用內容呈現評分設定檔。"""

import json

from engine.evaluation.config import EvaluationConfig
from ui.replay_evaluation_editor import GROUPS


def profile_name(path):
    if path is None:
        return "沒有設定檔"
    names = {
        "material": "純子力", "piece-square": "棋子位置", "pawn": "兵形",
        "mobility": "活動力", "king-safety": "王安全", "coordination": "協調",
    }
    if path.stem.startswith("learning-"):
        group = path.stem.removeprefix("learning-")
        if group in names:
            return "學習：" + names[group]
    return path.stem


def config_summary(config):
    payload = config.to_dict()
    labels = []
    for key, label, terms in GROUPS:
        if key == "phase":
            continue
        enabled = sum(payload["terms"][term]["enabled"] for term in terms)
        if enabled:
            labels.append(label + ("（部分）" if enabled < len(terms) else ""))
    return "＋".join(labels) or "無評分項"


def profile_summary(path):
    if path is None:
        return "沒有設定檔"
    try:
        config = EvaluationConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return config_summary(config) + "｜分階段" + ("開" if config.phase_enabled else "關")
    except (OSError, ValueError, TypeError, KeyError):
        return "設定檔無法讀取"


def profile_button(app, action, path, rect):
    """兩行呈現檔案身分及完整群組，長內容縮小至欄寬。"""
    from ui.controls import TEXT, ui_font

    app.button(action, "", rect)
    x, y, width, height = rect
    for index, text in enumerate((profile_name(path), profile_summary(path))):
        size = max(1, round(14 * app.scale))
        font = ui_font(size)
        available = max(1, round((width - 12) * app.scale))
        while size > 1 and font.size(text)[0] > available:
            size -= 1
            font = ui_font(size)
        app.draw_label(font, text, (x + 6, y + 2 + index * height / 2), TEXT)
