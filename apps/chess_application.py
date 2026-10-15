"""Home, live-game and replay screens over the existing pygame board and move list."""

import json
import random
import re
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

import chess
import pygame

from apps.play_ui import build_move_items, create_session, get_replay_data
from engine.evaluation.config import EvaluationConfig
from engine.game import create_board
from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.storage.data_ids import TAIPEI, allocate_id, date_key, now_iso
from engine.sessions.batch_run import BatchSettings
from engine.sessions.batch_execution import start_batch
from ui.batch_setup import EvaluationFields
from engine.sessions.live_session import LiveSession, LiveSettings
from engine.search.transposition import DEFAULT_TRANSPOSITION_CAPACITY
from engine.replay.replay_loader import load_replay_json
from ui.board_view import BOARD_PIXELS, WINDOW_HEIGHT, BoardView
from ui.controls import ACCENT, BACKGROUND, BORDER, MUTED, PANEL, TEXT, Button, draw_text, ui_font
from ui.move_list_view import MOVE_LIST_WIDTH, MoveListView
from ui.records_view import RecordsView
from ui.replay_evaluation_editor import GROUPS, ReplayEvaluationEditor, TERM_LABELS

HEADER_HEIGHT = 56
LOGICAL_SIZE = (900, 768)
APP_SIZE = (1280, 960)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
END_STATES = {"completed", "stopped", "truncated", "failed"}
REASONS = {
    "checkmate": "將死", "stalemate": "逼和", "insufficient_material": "子力不足",
    "fivefold_repetition": "五次重複局面", "threefold_repetition": "申請三次重複和棋",
    "seventyfive_moves": "七十五步規則", "fifty_moves": "申請五十步和棋",
    "max_plies": "達到手數上限", "user_stop": "使用者停止", "ai_error": "AI 執行失敗",
}


class ChessApplication:
    def __init__(self, screen: pygame.Surface, replay_path: str | None = None, *, executor=None, now=monotonic):
        self.screen = screen
        self.now = now
        self._owns_executor = executor is None
        self.executor = executor if executor is not None else ThreadPoolExecutor(max_workers=1)
        self.resize(screen)
        self.mode = "home"
        self.live: LiveSession | None = None
        self.replay = None
        self.replay_data = None
        self.replay_items: list[dict] = []
        self.replay_source = ""
        self.replay_is_local_game = False
        self.white, self.black = "Random", "Greedy"
        self.human_color, self.opponent = chess.WHITE, "Greedy"
        self.live_evaluation_files = sorted((PROJECT_ROOT / "configs/evaluation").glob("*.json"))
        self.live_evaluation_file = next(
            (path for path in self.live_evaluation_files if path.name == "stable.json"),
            self.live_evaluation_files[0] if self.live_evaluation_files else None,
        )
        self.live_search_depth = 2
        self.live_search_workers = 1
        self.live_transposition_capacity = DEFAULT_TRANSPOSITION_CAPACITY
        self.interval = 1.0
        self.batch_interval = 0.0
        self.batch_workers = 4
        self.batch_search_depth = 2
        self.batch_search_workers = 1
        self.batch_transposition_capacity = self.live_transposition_capacity
        self.batch_evaluation_files = {side: self.live_evaluation_file for side in ("white", "black")}
        self.game_count = 20
        self.batch = None
        self.pending_leave = None
        self.numeric_focus = None
        self.numeric_text = ""
        self.saved_path = None
        self.selected: chess.Square | None = None
        self.promotions: list[chess.Move] = []
        self.flipped = False
        self.running = True
        self.buttons: list[Button] = []
        self.records_view: RecordsView | None = None
        self.replay_return = None
        self.replay_record = None
        self.replay_evaluator = None
        self.replay_evaluator_saved = False
        self._replay_breakdown = None
        self._replay_breakdown_ply = -1
        self.replay_editor: ReplayEvaluationEditor | None = None
        self.records_return_mode = None
        self.batch_mode = "general"
        self.evaluation_fields = EvaluationFields(PROJECT_ROOT)
        self.confirm_action: str | None = None
        self.confirm_was_running = False
        self.message = ""
        self.saved = False
        self._last_ply = -1
        if replay_path is not None:
            self.mode = "replay"
            self.open_replay(replay_path)

    def resize(self, screen):
        self.screen = screen
        # Quantize to whole board-square pixels, then render text and SVG at that size.
        self.scale = max(0.5, int(min(screen.get_width() / 900, screen.get_height() / 768) * 80) / 80)
        self.origin = ((screen.get_width() - round(900 * self.scale)) // 2,
                       (screen.get_height() - round(768 * self.scale)) // 2)
        old_scroll = self.move_view.scroll_offset if hasattr(self, "move_view") else 0
        self.board_view = BoardView(screen, self.point(0, HEADER_HEIGHT)[1],
                                    origin_x=self.origin[0], square_size=round(80 * self.scale))
        self.move_view = MoveListView(screen, *self.point(640, 392), round(376 * self.scale), self.scale)
        self.move_view.scroll_offset = old_scroll
        self.font, self.small_font, self.title_font, self.evaluation_font = [
            ui_font(round(n * self.scale)) for n in (18, 15, 28, 12)
        ]

    def point(self, x, y):
        return self.origin[0] + round(x * self.scale), self.origin[1] + round(y * self.scale)

    def rect(self, rect):
        x, y, w, h = rect
        return pygame.Rect(*self.point(x, y), round(w * self.scale), round(h * self.scale))

    def draw_rect(self, color, rect, width=0, border_radius=0):
        pygame.draw.rect(self.screen, color, self.rect(rect),
                         max(1, round(width * self.scale)) if width else 0,
                         border_radius=round(border_radius * self.scale))

    def draw_label(self, font, value, pos, color=TEXT, width=None):
        draw_text(self.screen, font, value, self.point(*pos), color,
                  round(width * self.scale) if width else None)

    def close(self):
        if self.batch:
            self.batch.stop()
            # Never cancel a queued batch: its worker must publish the final manifest.
            if self._owns_executor:
                self.batch.future.result()
        if self.live:
            self.live.cancel_pending()
        if self._owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)

    def new_setup(self, mode: str):
        if self.live:
            self.live.stop()
        self.mode = mode
        self.live = self.replay = self.replay_data = None
        self.batch = None
        self.batch_mode = "general"
        self.evaluation_fields = EvaluationFields(PROJECT_ROOT)
        self.saved_path = None
        self.numeric_focus = None
        self.records_view = RecordsView(PROJECT_ROOT / "data") if mode == "records" else None
        self.replay_return = None
        self.replay_record = None
        self.records_return_mode = None
        self.replay_items = []
        self.replay_is_local_game = False
        self.selected, self.promotions = None, []
        self.message = ""
        self.saved = False
        self.flipped = mode == "human" and self.human_color == chess.BLACK
        self.move_view.scroll_offset = 0
        self._last_ply = -1

    def _set_move_view_layout(self):
        origin_y = 566 if self.mode == "replay" else (490 if self.mode == "human" and self.live is None else 392)
        self.move_view.origin_y = self.point(640, origin_y)[1]
        self.move_view.height = round((768 - origin_y) * self.scale)
        self.move_view.panel_rect = pygame.Rect(
            self.move_view.origin_x, self.move_view.origin_y,
            round(MOVE_LIST_WIDTH * self.scale), self.move_view.height,
        )

    def start_game(self):
        if not self._commit_number():
            return
        if self.mode == "auto":
            if self.batch is None:
                try:
                    settings = (self.evaluation_fields.options() if self.batch_mode == "evaluation"
                                else BatchSettings(white=self.white, black=self.black,
                                                   games=self.game_count, interval=self.batch_interval, workers=self.batch_workers,
                                                   search_depth=self.batch_search_depth, search_workers=self.batch_search_workers,
                                                   transposition_capacity=self.batch_transposition_capacity,
                                                   **{side + "_evaluation": self._batch_evaluation(side)
                                                      for side in ("white", "black")}))
                    if self.batch_mode == "evaluation":
                        settings["workers"] = self.batch_workers
                    self.batch = start_batch(self.batch_mode, settings, PROJECT_ROOT / "data/batches", self.executor)
                    self.message = ""
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    self.message = f"無法開始批次：{exc}"
            return
        if self.mode not in ("auto", "human") or self.live is not None:
            return
        white, black = self.white, self.black
        if self.mode == "human":
            white, black = ("Human", self.opponent) if self.human_color else (self.opponent, "Human")
        evaluation = None
        if self.mode == "human" and self.opponent in ("Greedy", "AlphaBeta"):
            try:
                if self.live_evaluation_file is None:
                    raise ValueError("找不到 configs/evaluation 評分設定檔")
                evaluation = EvaluationConfig.from_dict(
                    json.loads(self.live_evaluation_file.read_text(encoding="utf-8")),
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.message = f"無法載入評分設定檔：{exc}"
                return
        white_evaluation = evaluation if white in ("Greedy", "AlphaBeta") else None
        black_evaluation = evaluation if black in ("Greedy", "AlphaBeta") else None
        self.live = LiveSession(LiveSettings(
            white=white,
            black=black,
            seed=random.SystemRandom().randrange(2**63),
            interval=self.interval,
            white_evaluation=white_evaluation,
            black_evaluation=black_evaluation,
            search_depth=self.live_search_depth,
            search_workers=self.live_search_workers,
            transposition_capacity=self.live_transposition_capacity,
        ))
        self.live.start(self.now())
        self.saved = False
        self.message = ""

    def _set_replay(self, data: dict, source: str, *, local_game: bool = False):
        # Validate everything before replacing the currently usable replay.
        items = build_move_items(data["initial_fen"], data["moves_uci"])
        session, _ = create_session(data)
        self.replay, self.replay_data, self.replay_items = session, data, items
        self.replay_evaluator, self.replay_evaluator_saved = self._replay_static_evaluator(data)
        self.replay_editor = None
        self._replay_breakdown = None
        self._replay_breakdown_ply = -1
        self.replay_source, self.replay_is_local_game = source, local_game
        self.replay_record = None
        self.replay_return = None
        self.mode = "replay"
        self.selected, self.promotions = None, []
        self.move_view.scroll_offset = 0
        self.message = ""
        self._last_ply = -1

    @staticmethod
    def _replay_static_evaluator(data):
        metadata = data.get("metadata", {})
        strategies = metadata.get("strategies", {}) if isinstance(metadata, dict) else {}
        if not isinstance(strategies, dict) or not strategies:
            batch_id = metadata.get("batch_id") if isinstance(metadata, dict) else None
            if isinstance(batch_id, str) and batch_id and Path(batch_id).name == batch_id:
                batches = (PROJECT_ROOT / "data/batches").resolve()
                manifest_path = (batches / batch_id / "manifest.json").resolve()
                if manifest_path.is_relative_to(batches) and manifest_path.is_file():
                    try:
                        settings = json.loads(manifest_path.read_text(encoding="utf-8")).get("settings", {})
                        strategies = settings.get("strategies", {})
                        comparison = settings.get("comparison", {})
                        participants = comparison.get("participants", {})
                        if isinstance(participants, dict) and participants:
                            white_player = metadata.get("white_player")
                            black_player = metadata.get("black_player")
                            strategies = {
                                "white": next((p for p in participants.values()
                                               if p.get("label") == white_player), {}),
                                "black": next((p for p in participants.values()
                                               if p.get("label") == black_player), {}),
                            }
                    except (OSError, ValueError, TypeError, AttributeError):
                        strategies = {}
        colors = ("white", "black")
        if isinstance(metadata, dict) and metadata.get("white_player"):
            white_name = metadata["white_player"]
            white_strategy = strategies.get("white", {}) if isinstance(strategies, dict) else {}
            black_strategy = strategies.get("black", {}) if isinstance(strategies, dict) else {}
            white_strategy = white_strategy if isinstance(white_strategy, dict) else {}
            black_strategy = black_strategy if isinstance(black_strategy, dict) else {}
            if white_strategy.get("strategy") in (None, "Random") and black_strategy.get("evaluator"):
                colors = ("black", "white")
        for color in colors:
            strategy = strategies.get(color, {}) if isinstance(strategies, dict) else {}
            settings = strategy.get("evaluator") if isinstance(strategy, dict) else None
            if not isinstance(settings, dict):
                continue
            evaluator_type = settings.get("type")
            config_data = {key: value for key, value in settings.items() if key != "type"}
            try:
                config = EvaluationConfig.from_dict(config_data)
                if evaluator_type == "material":
                    return MaterialEvaluator(config.piece_values), True
                if evaluator_type == "handcrafted":
                    return HandcraftedEvaluator(config=config), True
            except (TypeError, ValueError):
                continue
        return HandcraftedEvaluator(), False

    def _current_replay_breakdown(self):
        evaluator = (HandcraftedEvaluator(config=self.replay_editor.config)
                     if self.replay_editor is not None else self.replay_evaluator)
        if self.replay is None or evaluator is None:
            return None
        if self._replay_breakdown_ply != self.replay.current_ply:
            self._replay_breakdown = evaluator.evaluate_breakdown(
                self.replay.current_board(),
            )
            self._replay_breakdown_ply = self.replay.current_ply
        return self._replay_breakdown

    def open_replay(self, path: str | Path, *, return_to=None, record=None) -> bool:
        try:
            self._set_replay(load_replay_json(str(path)), str(path))
            self.replay_return = return_to
            self.replay_record = record
            return True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.message = f"無法開啟棋譜：{exc}"
            return False

    def export_game(self) -> Path | None:
        data = self.replay_data if self.replay_is_local_game else (self.live.replay_payload() if self.live else None)
        if data is None:
            return None
        try:
            root = PROJECT_ROOT / "data/replays"
            root.mkdir(parents=True, exist_ok=True)
            if self.saved_path is not None:
                self.message = "本局已保存"
                return self.saved_path
            game_id = allocate_id(root.parent, "game", data["metadata"].get("started_at") or now_iso())
            data["metadata"]["game_id"] = game_id
            path = root / f"{game_id}.json"
            with path.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            self.saved = True
            self.saved_path = path
            self.message = f"已保存對局：{game_id}"
            return path
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.message = f"匯出失敗：{exc}"
            return None

    def needs_confirmation(self) -> bool:
        if self.batch and not self.batch.future.done():
            return True
        return self.live is not None and (self.live.active or (bool(self.live.move_items) and not self.saved))

    def request_leave(self, action: str):
        if self.confirm_action:
            return
        if self.needs_confirmation():
            self.confirm_action = action
            self.confirm_was_running = False
            if self.batch:
                self.confirm_was_running = self.batch.can_pause and self.batch.snapshot()["status"] == "running"
                if self.confirm_was_running:
                    self.batch.pause()
            elif self.live:
                self.confirm_was_running = self.live.status == "running"
                self.live.pause()
            self.move_view.handle_mouse_up()
        else:
            self._leave(action)

    def _leave(self, action: str):
        if self.batch and not self.batch.future.done():
            self.batch.stop()
            self.pending_leave = action
            return
        if self.live:
            self.live.stop()
        if action == "quit":
            self.running = False
        else:
            mode = self.mode if action == "restart" else "home"
            if mode == "replay":
                mode = "home"
            batch_mode = self.batch_mode
            self.new_setup(mode)
            if action == "restart" and mode == "auto":
                self.batch_mode = batch_mode

    def click_square(self, square: chess.Square | None):
        if self.live is None or not self.live.human_turn or self.promotions:
            return
        if square is None:
            self.selected = None
            return
        candidates = [] if self.selected is None else [m for m in self.live.legal_from(self.selected)
                                                       if m.to_square == square]
        if candidates:
            if len(candidates) > 1:
                self.promotions = candidates
            else:
                self.live.play_human(candidates[0], self.now())
                self.selected = None
            return
        self.selected = square if self.live.legal_from(square) else None

    def tick(self):
        worker = self.batch
        if self.pending_leave and worker and worker.future.done():
            action, self.pending_leave = self.pending_leave, None
            self._leave(action)
        if self.live and self.mode in ("auto", "human") and not self.confirm_action and not self.promotions:
            self.live.tick(self.now(), self.executor)
        items, ply = self.current_moves()
        if ply != self._last_ply:
            self.move_view.ensure_ply_visible(items, ply)
            self._last_ply = ply

    def current_moves(self) -> tuple[list[dict], int]:
        if self.mode == "replay" and self.replay:
            return self.replay_items, self.replay.current_ply
        if self.mode in ("auto", "human") and self.live:
            return self.live.move_items, len(self.live.move_items)
        return [], 0

    def dispatch(self, action: str):
        if self.replay_editor is not None and action.startswith("editor_"):
            editor = self.replay_editor
            if editor.focus is not None and action not in ("editor_discard",):
                if not editor.commit_edit():
                    return
                self._replay_breakdown_ply = -1
                pygame.key.stop_text_input()
            if action == "editor_discard":
                editor.cancel_edit()
                self.replay_editor = None
                self._replay_breakdown_ply = -1
                pygame.key.stop_text_input()
            elif action == "editor_save":
                self._save_replay_evaluation()
            elif action.startswith("editor_group:"):
                group = action.split(":", 1)[1]
                editor.expanded[group] = not editor.expanded[group]
            elif action.startswith("editor_toggle:"):
                editor.toggle(action.split(":", 1)[1])
                self._replay_breakdown_ply = -1
            elif action.startswith("editor_field:"):
                editor.begin_edit(action.split(":", 1)[1])
                pygame.key.start_text_input()
            return
        if self.replay_editor is not None and action == "replay_edit":
            if self.replay_evaluator is not None and self.replay_evaluator_saved:
                self.replay_editor = ReplayEvaluationEditor(self.replay_evaluator.config)
                self._replay_breakdown_ply = -1
            return
        if self.confirm_action:
            if action == "confirm":
                pending = self.confirm_action
                self.confirm_action = None
                self._leave(pending)
            elif action == "cancel":
                self.confirm_action = None
                if self.confirm_was_running:
                    (self.batch or self.live).resume()
            return
        if self.promotions:
            if action.startswith("promote:"):
                piece_type = int(action.split(":")[1])
                move = next(m for m in self.promotions if m.promotion == piece_type)
                self.live.play_human(move, self.now())
                self.promotions, self.selected = [], None
            elif action == "cancel_promotion":
                self.promotions, self.selected = [], None
            return
        if action == "batch_progress" and self.batch:
            self.mode = "auto"
            return
        if action == "batch_watch" and self.batch:
            path = self.batch.snapshot()["last_replay"]
            if path:
                self.open_replay(path, return_to="batch")
            return
        if action in ("batch_results", "view_batch") and self.batch and self.batch.future.done():
            self.show_records(batch_id=self.batch.snapshot()["batch_id"])
            return
        if action == "records_results" and self.records_view:
            self.mode = "records"
            return
        if self.mode == "records" and (action.startswith("records_") or action == "comparison_new"):
            self.records_view.action(action, self)
            return
        if self.mode == "auto" and self.batch is None:
            if action.startswith("batch_mode:"):
                if self._commit_number():
                    self.evaluation_fields.commit()
                    self.batch_mode = action.split(":")[1]
                    self.message = ""
                return
            if self.batch_mode == "evaluation" and action.startswith("comparison_"):
                if self._commit_number():
                    self.evaluation_fields.action(action, self)
                return
        if self.batch and action in ("pause", "stop"):
            if action == "stop":
                self.batch.stop()
            elif self.batch.snapshot()["status"] == "paused":
                self.batch.resume()
            else:
                self.batch.pause()
            return
        if self.mode == "auto" and self.batch is None and action.startswith("batch_"):
            if action in ("batch_depth", "batch_search_workers", "batch_capacity"):
                if self._commit_number():
                    attr = {"batch_depth": "batch_search_depth", "batch_search_workers": "batch_search_workers",
                            "batch_capacity": "batch_transposition_capacity"}[action]
                    self.numeric_focus = action
                    self.numeric_text = str(getattr(self, attr))
                    pygame.key.start_text_input()
                return
            if action in ("batch_evaluation_white", "batch_evaluation_black"):
                side = action.rsplit("_", 1)[1]
                files = sorted((PROJECT_ROOT / "configs/evaluation").glob("*.json"))
                if files:
                    current = self.batch_evaluation_files[side]
                    self.batch_evaluation_files[side] = files[(files.index(current) + 1) % len(files)] if current in files else files[0]
                return
        if self.mode == "auto" and action in ("interval", "count", "workers") and self.batch is None:
            self.evaluation_fields.commit()
            if self._commit_number():
                self.numeric_focus = action
                self.numeric_text = (str(self.batch_workers) if action == "workers" else
                                     str(self.game_count) if action == "count" else f"{self.batch_interval:g}")
                pygame.key.start_text_input()
            return
        if action.startswith("mode:"):
            self.new_setup(action.split(":")[1])
        elif action in ("home", "restart", "quit"):
            self.request_leave(action)
        elif action == "start":
            self.start_game()
        elif action == "flip":
            self.flipped = not self.flipped
        elif action in ("white", "black", "opponent") and self.live is None:
            if action == "opponent":
                options = ("Random", "Greedy", "AlphaBeta")
                self.opponent = options[(options.index(self.opponent) + 1) % len(options)]
            else:
                options = ("Random", "Greedy", "AlphaBeta")
                setattr(self, action, options[(options.index(getattr(self, action)) + 1) % len(options)])
        elif action == "live_evaluation" and self.live is None:
            self._refresh_evaluation_profiles()
            if not self.live_evaluation_files:
                return
            current = self.live_evaluation_files.index(self.live_evaluation_file)
            self.live_evaluation_file = self.live_evaluation_files[(current + 1) % len(self.live_evaluation_files)]
        elif action == "live_depth" and self.live is None:
            depths = (1, 2, 3, 4, 5)
            self.live_search_depth = depths[(depths.index(self.live_search_depth) + 1) % len(depths)]
        elif action in ("live_workers", "live_capacity") and self.live is None:
            if self._commit_number():
                self.numeric_focus = action
                self.numeric_text = str(self.live_search_workers if action == "live_workers" else self.live_transposition_capacity)
                pygame.key.start_text_input()
        elif action == "color" and self.live is None:
            self.human_color = not self.human_color
            self.flipped = not self.human_color
        elif action == "interval" and self.live is None:
            values = [0.5, 1.0, 2.0]
            self.interval = values[(values.index(self.interval) + 1) % len(values)]
        elif action == "pause" and self.live:
            if self.live.status == "paused":
                self.live.resume()
            else:
                self.live.pause()
        elif action == "step" and self.live:
            self.live.request_step()
        elif action == "stop" and self.live:
            self.live.stop()
            self.selected, self.promotions = None, []
        elif action == "review" and self.live and self.live.status in END_STATES:
            payload = self.live.replay_payload()
            if self.saved_path:
                payload["metadata"]["game_id"] = self.saved_path.stem
            self._set_replay(payload, "本局棋譜（記憶體）", local_game=True)
        elif action == "export":
            self.export_game()
        elif action == "open":
            # A finished local game stays available until it has been saved or left explicitly.
            if self.replay_is_local_game and not self.saved:
                self.message = "請先匯出本局，或返回首頁後再開啟其他棋譜。"
            else:
                self.show_records()
        elif action == "sample":
            self._set_replay(get_replay_data(None), "內建範例（6 手）")
            self.replay_return = None
            self.replay_record = None
        elif self.replay and action in ("first", "prev", "next", "last"):
            getattr(self.replay, action)()

    def _batch_evaluation(self, side):
        if getattr(self, side) == "Random":
            return None
        profile = self.batch_evaluation_files[side]
        return EvaluationConfig.from_dict(json.loads(profile.read_text(encoding="utf-8"))) if profile else EvaluationConfig()

    def _commit_number(self):
        if self.numeric_focus is None:
            return True
        try:
            value = int(self.numeric_text) if self.numeric_focus in ("count", "workers", "live_workers", "live_capacity", "batch_depth", "batch_search_workers", "batch_capacity") else float(self.numeric_text)
            import math
            if not math.isfinite(value) or (value < 1 if self.numeric_focus in ("count", "workers", "live_workers", "live_capacity", "batch_depth", "batch_search_workers", "batch_capacity") else value < 0):
                raise ValueError()
            if self.numeric_focus in ("batch_depth", "batch_search_workers", "batch_capacity"):
                attr = {"batch_depth": "batch_search_depth", "batch_search_workers": "batch_search_workers",
                        "batch_capacity": "batch_transposition_capacity"}[self.numeric_focus]
                setattr(self, attr, value)
            elif self.numeric_focus == "live_workers":
                self.live_search_workers = value
            elif self.numeric_focus == "live_capacity":
                self.live_transposition_capacity = value
            elif self.numeric_focus == "workers":
                self.batch_workers = value
            elif self.numeric_focus == "count":
                self.game_count = value
            else:
                self.batch_interval = value
        except (ValueError, OverflowError):
            self.message = ("搜尋 worker 與表項上限需為正整數。"
                            if self.numeric_focus in ("live_workers", "live_capacity")
                            else "場次與同時對戰場數需為正整數；場間間隔需為非負秒數。")
            return False
        self.numeric_focus = None
        pygame.key.stop_text_input()
        self.message = ""
        return True

    def show_records(self, *, batch_id=None):
        # 查找不替換執行中的批次或目前回放；返回來源時沿用原狀態。
        self.records_return_mode = "auto" if self.batch else (self.mode if self.mode == "replay" else None)
        if self.records_view is None or batch_id is not None:
            self.records_view = RecordsView(PROJECT_ROOT / "data")
        if batch_id is not None:
            entry = next((item for item in self.records_view.catalog.entries if item.batch_id == batch_id), None)
            if entry:
                self.records_view.select(entry.key)
        self.mode = "records"

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.request_leave("quit")
            return
        if event.type == pygame.VIDEORESIZE:
            self.resize(pygame.display.set_mode((max(900, event.w), max(768, event.h)), pygame.RESIZABLE))
            return
        if self.replay_editor is not None:
            editor = self.replay_editor
            if editor.focus is not None and event.type == pygame.TEXTINPUT:
                editor.input_draft += event.text
                return
            if editor.focus is not None and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_BACKSPACE:
                    editor.input_draft = editor.input_draft[:-1]
                elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                    editor.input_draft = ""
                elif event.key == pygame.K_RETURN:
                    if editor.commit_edit():
                        pygame.key.stop_text_input()
                        self._replay_breakdown_ply = -1
                elif event.key == pygame.K_ESCAPE:
                    editor.cancel_edit()
                    pygame.key.stop_text_input()
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.dispatch("editor_discard")
                return
            if event.type == pygame.MOUSEWHEEL:
                editor.scroll = max(0, min(editor.scroll + (3 if event.y < 0 else -3),
                                           max(0, len(self._replay_editor_rows()) - 14)))
                return
            if event.type not in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                return
        if self.numeric_focus and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            if event.type == pygame.TEXTINPUT:
                self.numeric_text += event.text
            elif event.key == pygame.K_BACKSPACE:
                self.numeric_text = self.numeric_text[:-1]
            elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                self.numeric_text = ""
            elif event.key == pygame.K_RETURN:
                self._commit_number()
            elif event.key == pygame.K_ESCAPE:
                self.numeric_focus = None
                pygame.key.stop_text_input()
            return
        setup = self.evaluation_fields if self.mode == "auto" and self.batch is None and self.batch_mode == "evaluation" else None
        if setup and setup.focus and not self.confirm_action and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            if event.type == pygame.TEXTINPUT:
                setup.draft += event.text
            elif event.key == pygame.K_BACKSPACE:
                setup.draft = setup.draft[:-1]
            elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                setup.draft = ""
            elif event.key == pygame.K_RETURN:
                setup.commit()
                pygame.key.stop_text_input()
            elif event.key == pygame.K_ESCAPE:
                setup.focus = None
                pygame.key.stop_text_input()
            return
        if self.mode == "records" and not self.confirm_action and event.type in (pygame.KEYDOWN, pygame.MOUSEWHEEL):
            if event.type == pygame.MOUSEWHEEL:
                if self.records_view.settings_side:
                    self.dispatch("records_prev" if event.y > 0 else "records_next")
                else:
                    self.records_view.scroll(-event.y)
            elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.dispatch("records_back")
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                self.dispatch("records_prev" if event.key == pygame.K_LEFT else "records_next")
            return
        if event.type == pygame.KEYDOWN:
            if self.confirm_action:
                if event.key == pygame.K_ESCAPE:
                    self.dispatch("cancel")
                return
            if self.promotions:
                if event.key == pygame.K_ESCAPE:
                    self.dispatch("cancel_promotion")
                return
            if event.key == pygame.K_ESCAPE:
                if self.mode == "replay" and self.replay_return == "records":
                    self.dispatch("records_results")
                else:
                    self.request_leave("home")
            elif event.key == pygame.K_f:
                self.flipped = not self.flipped
            elif self.mode == "replay" and self.replay:
                actions = {pygame.K_LEFT: "prev", pygame.K_RIGHT: "next",
                           pygame.K_HOME: "first", pygame.K_END: "last"}
                if event.key in actions:
                    self.dispatch(actions[event.key])
            elif self.mode == "auto" and event.key == pygame.K_SPACE:
                self.dispatch("pause")
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for button in reversed(self.buttons):
                if button.enabled and button.rect.collidepoint(event.pos):
                    self.dispatch(button.action)
                    return
            if self.replay_editor is not None:
                return
            if self.confirm_action or self.promotions:
                return
            if self.mode == "records":
                return
            if self.mode == "human":
                self.click_square(self.board_view.screen_to_square(event.pos, self.flipped))
            if self.mode != "home":
                items, _ = self.current_moves()
                if not self.move_view.handle_mouse_down(event.pos, items) and self.mode == "replay" and self.replay:
                    ply = self.move_view.handle_click(event.pos)
                    if ply is not None:
                        self.replay.goto_ply(ply)
        if self.confirm_action or self.promotions:
            return
        items, _ = self.current_moves()
        if event.type == pygame.MOUSEBUTTONUP:
            self.move_view.handle_mouse_up()
        elif event.type == pygame.MOUSEMOTION:
            self.move_view.handle_mouse_motion(event.pos, items)
        elif event.type == pygame.MOUSEWHEEL:
            self.move_view.handle_wheel(pygame.mouse.get_pos(), event.y, items)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            self.move_view.handle_wheel(event.pos, 1 if event.button == 4 else -1, items)

    def button(self, action, label, rect, *, enabled=True, primary=False):
        button = Button(action, label, self.rect(rect), enabled, primary)
        self.buttons.append(button)
        button.draw(self.screen, self.font)

    def text(self, value, x, y, *, muted=False, width=None, large=False):
        self.draw_label(self.title_font if large else self.font, value, (x, y),
                  MUTED if muted else TEXT, width)

    def render(self):
        self.buttons = []
        self.screen.fill(BACKGROUND)
        if self.mode == "home":
            self.text("開始一盤棋", 64, 160, large=True)
            self.text("選擇模式，再設定對手或查找對局。", 64, 207, muted=True)
            for i, (mode, title, subtitle) in enumerate([
                ("auto", "批次自動對戰", "設定雙方 AI 與生成場次"),
                ("human", "真人下棋", "選擇執白或執黑，挑戰 AI"),
                ("records", "對局紀錄", "查找比較、一般批次與非批次棋譜"),
            ]):
                x, y = 64 + 396 * (i % 2), 260 + 184 * (i // 2)
                self.draw_rect(PANEL, (x, y, 376, 160), border_radius=10)
                self.text(subtitle, x + 16, y + 28, muted=True, width=344)
                self.button("mode:" + mode, title, (x + 16, y + 88, 344, 48), primary=mode == "auto")
            self.text("棋譜回放也可使用 --replay 直接開啟指定檔案。", 64, 660, muted=True)
        elif self.mode == "auto":
            self._render_batch()
        elif self.mode == "records":
            self.records_view.render(self)
        else:
            self._render_game()
        self.draw_rect(PANEL, (0, 0, LOGICAL_SIZE[0], HEADER_HEIGHT))
        self.text("Chess AI", 18, 10, large=True)
        if self.mode != "home":
            if self.mode not in ("auto", "records"):
                self.button("flip", "翻轉 F", (664, 10, 104, 36))
            self.button("home", "回首頁", (780, 10, 104, 36))
        if self.confirm_action:
            self._render_confirmation()
        elif self.promotions:
            self._render_promotion()

    def _render_game(self):
        self._set_move_view_layout()
        items, ply = self.current_moves()
        board = self.replay.current_board() if self.mode == "replay" and self.replay else (
            self.live.board if self.live and self.mode != "replay" else create_board())
        destinations = {m.to_square for m in self.live.legal_from(self.selected)} if self.live and self.selected is not None else set()
        self.board_view.render(board, ply, len(items), self.flipped,
                               selected=self.selected, destinations=destinations)
        panel_height = 510 if self.mode == "replay" else (434 if self.mode == "human" and self.live is None else 336)
        self.draw_rect(PANEL, (BOARD_PIXELS, HEADER_HEIGHT, MOVE_LIST_WIDTH, panel_height))
        x = BOARD_PIXELS + 14
        title = {"auto": "自動對戰", "human": "真人對 AI", "replay": "棋譜回放"}[self.mode]
        self.text(title, x, 70, large=True)
        if self.mode == "replay":
            self._render_replay_panel(x)
        elif self.live is None:
            self._render_setup(x)
        else:
            self._render_live_panel(x)
        self.move_view.render(items, ply)
        # The footer is mode-specific; playback key hints do not apply to live play.
        self.draw_rect(BACKGROUND, (0, 696, BOARD_PIXELS, 72))
        turn = "白方" if board.turn else "黑方"
        status = self._status_text()
        self.text(f"{status}　｜　{ply} 手　｜　輪到{turn}", 14, 702, width=610)
        hint = "← → 前後一步　Home / End 起終點　F 翻轉" if self.mode == "replay" else (
            "點選棋子與目的格；Esc 回首頁，F 翻轉" if self.mode == "human" else "Space 暫停／繼續　F 翻轉　Esc 回首頁")
        self.draw_label(self.small_font, self.message or hint, (14, 737), MUTED, 610)
        if self.mode == "replay" and self.replay_editor is not None:
            self._render_replay_editor()

    def _status_text(self):
        if self.mode == "replay":
            return "回放中" if self.replay else "尚未載入棋譜"
        if self.live is None:
            return "尚未開始"
        session = self.live
        if session.status == "running":
            return "等待你落子" if session.human_turn else "AI 思考中" if session.thinking else "等待 AI 落子"
        return {"paused": "已暫停", "completed": "對局結束", "stopped": "已停止（未完成）",
                "truncated": "達到執行上限", "failed": "AI 執行失敗"}.get(session.status, session.status)

    def _render_setup(self, x):
        if self.mode == "auto":
            fields = [("white", "白方", self.white), ("black", "黑方", self.black)]
        else:
            opponent_name = "Alpha-Beta" if self.opponent == "AlphaBeta" else self.opponent
            fields = [("color", "我執", "白方" if self.human_color else "黑方"),
                      ("opponent", "對手", opponent_name),
                      ("live_evaluation", "評分設定", self.live_evaluation_file.name
                       if self.live_evaluation_file else "沒有設定檔")]
            if self.opponent == "AlphaBeta":
                fields.append(("live_depth", "搜尋深度", str(self.live_search_depth)))
                fields.append(("live_workers", "Workers", str(self.live_search_workers)))
                fields.append(("live_capacity", "表項上限", str(self.live_transposition_capacity)))
            fields.append(("interval", "間隔", f"{self.interval:g} 秒"))
        for i, (action, label, value) in enumerate(fields):
            y = 112 + i * 42 if self.mode == "human" else 119 + i * 46
            self.text(label, x, y + 7)
            if self.numeric_focus == action:
                value = self.numeric_text + " |"
            self.button(action, value, (x + 70, y, 162, 36) if self.mode == "human" else (x + 56, y, 176, 36))
        start_y = 406 if self.mode == "human" else 270
        self.button("start", "開始對戰", (x, start_y, 232, 42), primary=True)
        if self.mode == "human":
            self.draw_label(self.small_font, "點選設定切換；深度選項為 1–5", (x, 457), MUTED, 232)
        else:
            self.text("點選設定可切換選項", x, start_y + 51, muted=True)
            self.draw_label(self.small_font, "和棋政策：不自動申請", (x, start_y + 79), MUTED)

    def _render_live_panel(self, x):
        session = self.live
        player_name = lambda name: {"Human": "真人", "AlphaBeta": "Alpha-Beta"}.get(name, name)
        self.text("白方：" + player_name(session.settings.white), x, 114)
        self.text("黑方：" + player_name(session.settings.black), x, 144)
        self.text(self._status_text(), x, 178, width=232)
        if session.status in END_STATES:
            self.text(f"結果：{session.result}", x, 211)
            self.draw_label(self.small_font, REASONS.get(session.termination, session.termination), (x, 240), MUTED, 232)
            self.button("review", "回放本局", (x, 270, 111, 38))
            self.button("export", "匯出棋譜", (x + 121, 270, 111, 38))
            self.button("restart", "重新設定", (x, 322, 232, 38))
            if session.error:
                self.message = session.error
        else:
            if self.mode == "auto":
                self.button("pause", "繼續" if session.status == "paused" else "暫停", (x, 222, 111, 38))
                self.button("step", "走一步", (x + 121, 222, 111, 38), enabled=session.status == "paused")
            self.button("stop", "停止對局", (x, 274, 232, 38))
            self.button("restart", "重新開始", (x, 326, 232, 38))

    def _render_replay_panel(self, x):
        timestamp = self.replay_data.get("metadata", {}).get("started_at", "") if self.replay_data else ""
        label = datetime.fromisoformat(timestamp).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S") if date_key(timestamp) != "日期不詳" else "日期時間不詳"
        self.draw_label(self.small_font, label if self.replay_data else "尚未選擇對局", (x, 113), MUTED, 230)
        if self.replay_data:
            self.button("replay_edit", "調整評分", (x + 118, 68, 114, 32),
                        enabled=self.replay_evaluator_saved)
            metadata = self.replay_data.get("metadata", {})
            info = {key: metadata.get(key) or "未記錄" for key in ("white_player", "black_player", "game_id")}
            result = self.replay_record.result if self.replay_record is not None else self.replay_data.get("result")
            info["result"] = result or "未記錄"
            for i, (label, key) in enumerate([("白方", "white_player"), ("黑方", "black_player"),
                                              ("結果", "result"), ("編號", "game_id")]):
                self.draw_label(self.small_font, f"{label}：{info[key]}", (x, 137 + i * 19), TEXT, 230)
            reason = self.replay_data.get("metadata", {}).get("termination", "")
            self.draw_label(self.small_font, REASONS.get(reason, reason), (x, 215), MUTED, 230)
            self._render_replay_evaluation(x)
        for i, (action, label) in enumerate([("first", "起點"), ("prev", "上步"), ("next", "下步"), ("last", "終點")]):
            enabled = self.replay is not None and (self.replay.current_ply > 0 if i < 2 else self.replay.current_ply < self.replay.total_ply())
            self.button(action, label, (x + i * 59, 480, 55, 34), enabled=enabled)
        self.button("open", "選擇對局", (x, 526, 111, 34), primary=self.replay is None)
        if self.replay_is_local_game:
            self.button("export", "匯出本局", (x + 121, 526, 111, 34))
        else:
            if self.replay_return == "records" and self.records_view:
                self.button("records_results", "返回紀錄", (x + 121, 526, 111, 34))
            elif self.replay_return == "batch" and self.batch:
                self.button("batch_progress", "返回批次", (x + 121, 526, 111, 34))
            else:
                self.button("sample", "範例棋譜", (x + 121, 526, 111, 34))

    def _replay_editor_rows(self):
        editor = self.replay_editor
        if editor is None:
            return []
        rows = []
        fields = editor.fields()
        for key, label, terms in GROUPS:
            rows.append(("group", key, label, None, None))
            if editor.expanded[key]:
                rows.extend(("field", field[2], field[1], field[3], field[4])
                            for field in fields if field[0] == key)
        return rows

    def _refresh_evaluation_profiles(self):
        current = self.live_evaluation_file
        files = sorted((PROJECT_ROOT / "configs/evaluation").glob("*.json"))
        self.live_evaluation_files = files
        if current in files:
            self.live_evaluation_file = current
        else:
            self.live_evaluation_file = next(
                (path for path in files if path.name == "stable.json"), files[0] if files else None,
            )
        self.evaluation_fields.files = files

    def _save_replay_evaluation(self):
        editor = self.replay_editor
        if editor is None:
            return
        if not editor.commit_edit():
            return
        name = editor.name.strip()
        if name.lower().endswith(".json"):
            name = name[:-5]
        if not name or not re.fullmatch(r"[\w.-]+", name, flags=re.UNICODE) or name in (".", ".."):
            editor.message = "請輸入不含路徑的設定檔名稱。"
            return
        path = PROJECT_ROOT / "configs/evaluation" / f"{name}.json"
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(editor.config.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except FileExistsError:
            editor.message = "同名設定檔已存在，請更換名稱。"
            return
        except OSError as exc:
            editor.message = f"無法保存設定檔：{exc}"
            return
        self.replay_editor = None
        self.replay_evaluator = HandcraftedEvaluator(config=editor.config)
        self._refresh_evaluation_profiles()
        self._replay_breakdown_ply = -1
        self.message = f"已另存評分設定：{name}.json"

    def _render_replay_editor(self):
        editor = self.replay_editor
        if editor is None:
            return
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        self.screen.blit(overlay, (0, 0))
        self.draw_rect(PANEL, (24, 64, 852, 640), border_radius=10)
        self.draw_rect(BORDER, (24, 64, 852, 640), 1, border_radius=10)
        self.buttons = []
        self.text("調整回放評分", 48, 79, large=True)
        self.draw_label(self.small_font, "設定名稱", (48, 125), MUTED)
        name_value = (editor.input_draft + " |" if editor.focus == "name" else editor.name or "點此輸入新設定檔名稱")
        self.button("editor_field:name", name_value, (48, 148, 360, 38), primary=editor.focus == "name")
        self.draw_label(self.small_font, "即時局面靜態評分（白方／兵）", (48, 202), MUTED, 370)
        breakdown = self._current_replay_breakdown()
        if breakdown is not None:
            self.draw_label(self.title_font, f"總分：{breakdown.total_score!r}", (48, 230), TEXT, 360)
            terms = [(key, term) for key, term in breakdown.terms.items() if term.enabled]
            maximum = max((abs(term.contribution) for _, term in terms), default=1.0) or 1.0
            center_x = self.point(246, 0)[0]
            half = round(54 * self.scale)
            for index, (key, term) in enumerate(terms):
                y = 278 + index * 21
                self.draw_label(self.evaluation_font, TERM_LABELS.get(key, key), (48, y), TEXT, 82)
                row_y = self.point(246, y + 7)[1]
                pygame.draw.line(self.screen, BORDER, (center_x, row_y - 5), (center_x, row_y + 5), 1)
                width = round(half * min(1.0, abs(term.contribution) / maximum))
                if width:
                    color = (110, 203, 146) if term.contribution > 0 else (231, 119, 119)
                    left = center_x if term.contribution > 0 else center_x - width
                    pygame.draw.rect(self.screen, color, pygame.Rect(left, row_y - 2, width, 5))
                self.draw_label(self.evaluation_font, f"{term.contribution:+}" if term.contribution else "0.0",
                                (310, y), TEXT, 88)

        self.draw_label(self.small_font, "現有評分項；點選數值修改，滾輪瀏覽。", (455, 122), MUTED, 398)
        rows = self._replay_editor_rows()
        start, visible = 158, 15
        for row_index, row in enumerate(rows[editor.scroll:editor.scroll + visible]):
            kind, key, label, value, field_kind = row
            y = start + row_index * 30
            if kind == "group":
                marker = "▼" if editor.expanded[key] else "▶"
                self.button(f"editor_group:{key}", f"{marker} {label}", (455, y, 398, 27))
            else:
                self.draw_label(self.small_font, label, (468, y + 5), TEXT, 182)
                if field_kind == "toggle":
                    display = "開啟" if value else "關閉"
                    action = f"editor_toggle:{key}"
                else:
                    display = editor.input_draft + " |" if editor.focus == key else repr(value)
                    action = f"editor_field:{key}"
                self.button(action, display, (654, y, 199, 27), primary=editor.focus == key)
        if editor.message:
            self.draw_label(self.small_font, editor.message, (48, 650), (239, 184, 89), 390)
        self.button("editor_discard", "放棄草稿", (568, 650, 136, 36))
        self.button("editor_save", "另存設定檔", (716, 650, 137, 36), primary=True)

    def _render_replay_evaluation(self, x):
        breakdown = self._current_replay_breakdown()
        self.draw_label(self.small_font, "局面靜態評分（白方／兵）", (x, 237), MUTED, 232)
        if breakdown is None:
            self.draw_label(self.small_font, "無法計算評分拆解", (x, 255), MUTED, 232)
            return

        total_text = f"總分：{breakdown.total_score!r}"
        self.draw_label(self.font, total_text, (x, 256), TEXT, 232)
        self.draw_label(self.small_font, "已啟用評分項　｜　貢獻值", (x, 279), MUTED, 232)
        labels = {
            "material": "子力", "piece_square": "位置",
            "isolated_pawns": "孤兵", "doubled_pawns": "疊兵", "passed_pawns": "通路兵",
            "pawn_mobility": "兵活動", "knight_mobility": "馬活動", "bishop_mobility": "象活動",
            "rook_mobility": "車活動", "queen_mobility": "后活動", "king_mobility": "王活動",
            "king_pawn_shield": "王盾", "king_zone_attacks": "王區攻擊",
            "king_file_exposure": "王線暴露", "bishop_pair": "雙象",
            "rook_open_file": "車開放線", "rook_half_open_file": "車半開放線",
        }
        terms = [(name, term) for name, term in breakdown.terms.items() if term.enabled]
        if not terms:
            self.draw_label(self.small_font, "目前沒有啟用的評分項", (x, 300), MUTED, 232)
            return

        max_contribution = max(abs(term.contribution) for _, term in terms) or 1.0
        center_x = self.point(x + 121, 0)[0]
        bar_half_width = round(41 * self.scale)
        row_height = 10
        for index, (name, term) in enumerate(terms):
            y = 294 + index * row_height
            self.draw_label(self.evaluation_font, labels.get(name, name), (x, y), TEXT, 65)
            row_y = self.point(x, y + 5)[1]
            pygame.draw.line(self.screen, BORDER, (center_x, row_y - 3), (center_x, row_y + 4), 1)
            length = round(bar_half_width * min(1.0, abs(term.contribution) / max_contribution))
            if length:
                color = (110, 203, 146) if term.contribution > 0 else (231, 119, 119)
                rect = pygame.Rect(center_x if term.contribution > 0 else center_x - length,
                                   row_y - 2, length, max(2, round(5 * self.scale)))
                pygame.draw.rect(self.screen, color, rect)
            value = f"{term.contribution:+}" if term.contribution else "0.0"
            self.draw_label(self.evaluation_font, value, (x + 167, y), TEXT, 64)

    @staticmethod
    def comparison_reason(reason):
        return REASONS.get(reason, reason)

    def _modal(self, rect):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        self.draw_rect(PANEL, rect, border_radius=10)
        self.draw_rect(BORDER, rect, 1, border_radius=10)
        self.buttons = []

    def _render_confirmation(self):
        self._modal((210, 260, 480, 230))
        self.text("離開目前對局？", 238, 287, large=True)
        self.text("停止後將保留已保存對局與本局走法。" if self.batch else "未保存的棋譜將不會保留。", 238, 340)
        self.text("確認後等待停止與保存完成。" if self.batch else "取消後可繼續，或先停止並保存棋譜。", 238, 373, muted=True)
        self.button("cancel", "取消", (238, 428, 196, 40), primary=True)
        self.button("confirm", "確認離開", (454, 428, 208, 40))

    def _render_promotion(self):
        self._modal((210, 260, 480, 220))
        self.text("選擇升變棋子", 238, 286, large=True)
        names = {chess.QUEEN: "后", chess.ROOK: "車", chess.BISHOP: "象", chess.KNIGHT: "馬"}
        for i, piece in enumerate((chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)):
            self.button(f"promote:{piece}", names[piece], (238 + i * 110, 345, 94, 42))
        self.button("cancel_promotion", "取消", (238, 410, 424, 40))

    def _render_batch(self):
        self.text("批次自動對戰", 64, 80, large=True)
        if self.batch is None:
            for index, (mode, title) in enumerate((("general", "一般對戰"), ("evaluation", "評分比較"))):
                self.button("batch_mode:" + mode, title, (64 + index * 396, 125, 376, 32),
                            primary=self.batch_mode == mode)
            if self.batch_mode == "evaluation":
                self.evaluation_fields.render(self)
            else:
                fields = [("white", "白方", self.white), ("black", "黑方", self.black),
                          ("batch_evaluation_white", "白方評分", self.batch_evaluation_files["white"].stem if self.batch_evaluation_files["white"] else "預設"),
                          ("batch_evaluation_black", "黑方評分", self.batch_evaluation_files["black"].stem if self.batch_evaluation_files["black"] else "預設"),
                          ("interval", "場間秒數", f"{self.batch_interval:g}"), ("count", "場次", str(self.game_count)),
                          ("batch_depth", "搜尋深度", str(self.batch_search_depth)),
                          ("batch_search_workers", "搜尋 worker", str(self.batch_search_workers)),
                          ("batch_capacity", "表項上限", str(self.batch_transposition_capacity))]
                for index, (action, label, value) in enumerate(fields):
                    column, row = index % 2, index // 2
                    x, y = 64 + column * 396, 185 + row * 70
                    self.draw_label(self.small_font, label, (x, y))
                    if self.numeric_focus == action:
                        value = self.numeric_text + " |"
                    self.button(action, value, (x, y + 23, 376, 38), primary=self.numeric_focus == action)
                self.button("start", "開始生成", (148, 568, 600, 48), primary=True)
            if self.batch_mode == "evaluation":
                self.draw_label(self.small_font, "同時對戰場數（每個程序執行一組配對）", (460, 570), width=376)
                worker_rect = (460, 595, 376, 39)
            else:
                self.draw_label(self.small_font, "同時對戰場數", (460, 465))
                worker_rect = (460, 488, 376, 38)
            value = self.numeric_text + " |" if self.numeric_focus == "workers" else str(self.batch_workers)
            self.button("workers", value, worker_rect, primary=self.numeric_focus == "workers")
            self.text(self.message, 64, 642, width=772, muted=True)
            return
        state = self.batch.snapshot()
        status = state["status"]
        labels = {"running": "生成中（暫時結果）", "paused": "已暫停", "stopping": "正在停止並保存",
                  "completed": "批次完成", "stopped": "已停止", "failed": "生成失敗"}
        comparison = self.batch.mode == "evaluation"
        self.text(("評分比較　｜　" if comparison else "一般對戰　｜　") + labels[status], 64, 139, large=True)
        self.text(state["batch_id"] or "準備建立批次…", 64, 187, muted=True)
        self.text(f"已派發至第 {state['current_game']} / {state['requested_games']} 局　｜　已保存 {state['saved_games']} 局", 64, 241)
        self.draw_rect(BORDER, (64, 282, 772, 16), border_radius=6)
        width = round(772 * state["saved_games"] / state["requested_games"])
        if width:
            self.draw_rect(ACCENT, (64, 282, width, 16), border_radius=6)
        self.draw_label(self.small_font, f"要求 {state['requested_workers']} ／ 實際 {state['actual_workers']} 個程序", (64, 211), MUTED)
        unit = "組配對" if comparison else "局"
        self.text(f"等待 {state['waiting_work']}　｜　執行中 {state['running_work']}　｜　已結束 {state['finished_work']} {unit}", 64, 320)
        self.text(f"已回報 {state['finished_games']} 局　｜　正常完成 {state['completed_games']}　｜　未完成 {state['unfinished']}", 64, 350)
        if comparison:
            self.text(f"完整配對 {state['completed_pairs']}　｜　不完整配對 {state['incomplete_pairs']}　｜　預定 {state['requested_pairs']} 對", 64, 386)
            rate = "無資料" if state["paired_score_rate"] is None else f"{state['paired_score_rate']:.1%}"
            self.text(f"候選累積得分率：{rate}（僅含兩局正常完成的配對）", 64, 424, width=772)
        self.text("評分比較支援停止，不提供暫停；停止保留當盤已落子的走法。" if comparison else
                  "一般對戰暫停所有席位；每席位保存後等待場間間隔再派發。", 64, 469, muted=True, width=772)
        self.text(state["error"], 64, 505, width=772)
        active = not self.batch.future.done()
        if active:
            if self.batch.can_pause:
                self.button("pause", "繼續" if status == "paused" else "暫停", (64, 562, 240, 44), enabled=status != "stopping")
            self.button("stop", "停止並保存", (596, 562, 240, 44), enabled=status in ("running", "paused"))
        else:
            self.button("batch_results" if comparison else "view_batch", "查看本批次結果" if comparison else "查看本批次紀錄",
                        (460, 562, 376, 44), enabled=bool(state["path"]) if comparison else state["saved_games"] > 0, primary=True)
            self.button("restart", "設定下一批", (64, 672, 376, 40))
        self.button("batch_watch", "回放最近保存棋局", (64 if not active else 320, 562, 376 if not active else 260, 44),
                    enabled=bool(state["last_replay"]))
