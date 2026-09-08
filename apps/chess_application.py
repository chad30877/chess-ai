"""Home, live-game and replay screens over the existing pygame board and move list."""

import json
import random
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

import chess
import pygame

from apps.play_ui import build_move_items, build_replay_info, create_session, get_replay_data
from engine.game import create_board
from engine.data_ids import TAIPEI, allocate_id, date_key, now_iso
from engine.batch_run import BatchRun, BatchSettings
from engine.replay_catalog import ReplayCatalog, result_badges
from engine.live_session import LiveSession, LiveSettings
from engine.replay_loader import load_replay_json
from ui.board_view import BOARD_PIXELS, WINDOW_HEIGHT, BoardView
from ui.controls import ACCENT, BACKGROUND, BORDER, MUTED, PANEL, TEXT, Button, draw_text, ui_font
from ui.move_list_view import MOVE_LIST_WIDTH, MoveListView

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
        self.interval = 1.0
        self.batch_interval = 0.0
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
        self.browser: ReplayCatalog | None = None
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
        self.font, self.small_font, self.title_font = [ui_font(round(n * self.scale)) for n in (18, 15, 28)]

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
        self.saved_path = None
        self.numeric_focus = None
        self.browser = ReplayCatalog(PROJECT_ROOT / "data") if mode == "replay" else None
        self.replay_items = []
        self.replay_is_local_game = False
        self.selected, self.promotions = None, []
        self.message = ""
        self.saved = False
        self.flipped = mode == "human" and self.human_color == chess.BLACK
        self.move_view.scroll_offset = 0
        self._last_ply = -1

    def start_game(self):
        if not self._commit_number():
            return
        if self.mode == "auto":
            if self.batch is None:
                self.batch = BatchRun(BatchSettings(white=self.white, black=self.black,
                                                   games=self.game_count, interval=self.batch_interval),
                                      PROJECT_ROOT / "data/batches", self.executor)
                self.message = ""
            return
        if self.mode not in ("auto", "human") or self.live is not None:
            return
        white, black = self.white, self.black
        if self.mode == "human":
            white, black = ("Human", self.opponent) if self.human_color else (self.opponent, "Human")
        self.live = LiveSession(LiveSettings(white=white, black=black,
                                            seed=random.SystemRandom().randrange(2**63), interval=self.interval))
        self.live.start(self.now())
        self.saved = False
        self.message = ""

    def _set_replay(self, data: dict, source: str, *, local_game: bool = False):
        # Validate everything before replacing the currently usable replay.
        items = build_move_items(data["initial_fen"], data["moves_uci"])
        session, _ = create_session(data)
        self.replay, self.replay_data, self.replay_items = session, data, items
        self.replay_source, self.replay_is_local_game = source, local_game
        self.mode = "replay"
        self.selected, self.promotions = None, []
        self.move_view.scroll_offset = 0
        self.message = ""
        self._last_ply = -1

    def open_replay(self, path: str | Path) -> bool:
        try:
            self._set_replay(load_replay_json(str(path)), str(path))
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
        if self.batch and self.batch.snapshot()["status"] in ("running", "paused", "stopping"):
            return True
        return self.live is not None and (self.live.active or (bool(self.live.move_items) and not self.saved))

    def request_leave(self, action: str):
        if self.confirm_action:
            return
        if self.needs_confirmation():
            self.confirm_action = action
            self.confirm_was_running = (self.batch.snapshot()["status"] if self.batch else self.live.status) == "running"
            (self.batch or self.live).pause()
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
            self.new_setup(mode)

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
        if self.pending_leave and self.batch and self.batch.future.done():
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
        if self.browser:
            self._browser_action(action)
            return
        if action == "view_batch" and self.batch:
            batch_id = self.batch.snapshot()["batch_id"]
            self.browser = ReplayCatalog(PROJECT_ROOT / "data")
            entries = [e for e in self.browser.entries if e.group == batch_id]
            if entries:
                self.browser.date, self.browser.group = entries[0].date, batch_id
            return
        if self.batch and action in ("pause", "stop"):
            if action == "stop":
                self.batch.stop()
            elif self.batch.snapshot()["status"] == "paused":
                self.batch.resume()
            else:
                self.batch.pause()
            return
        if self.mode == "auto" and action in ("interval", "count") and self.batch is None:
            if self._commit_number():
                self.numeric_focus = action
                self.numeric_text = str(self.game_count) if action == "count" else f"{self.batch_interval:g}"
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
            setattr(self, action, "Greedy" if getattr(self, action) == "Random" else "Random")
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
                self.browser = ReplayCatalog(PROJECT_ROOT / "data")
        elif action == "sample":
            self._set_replay(get_replay_data(None), "內建範例（6 手）")
        elif self.replay and action in ("first", "prev", "next", "last"):
            getattr(self.replay, action)()

    def _commit_number(self):
        if self.numeric_focus is None:
            return True
        try:
            value = int(self.numeric_text) if self.numeric_focus == "count" else float(self.numeric_text)
            import math
            if not math.isfinite(value) or (value < 1 if self.numeric_focus == "count" else value < 0):
                raise ValueError()
            if self.numeric_focus == "count":
                self.game_count = value
            else:
                self.batch_interval = value
        except (ValueError, OverflowError):
            self.message = "場次需為正整數；場間間隔需為非負秒數。"
            return False
        self.numeric_focus = None
        pygame.key.stop_text_input()
        self.message = ""
        return True

    def _browser_action(self, action: str):
        browser = self.browser
        if action == "browser_cancel":
            self.browser = None
        elif action == "browser_up":
            browser.back()
        elif action == "browser_refresh":
            browser.refresh()
        elif action == "browser_open":
            entry = browser.selected_entry()
            if entry:
                if self.open_replay(entry.path):
                    self.browser = None
                else:
                    browser.error = "此對局無法播放，請選擇其他對局。"
        elif action.startswith("entry:"):
            browser.choose(int(action.split(":")[1]))

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.request_leave("quit")
            return
        if event.type == pygame.VIDEORESIZE:
            self.resize(pygame.display.set_mode((max(900, event.w), max(768, event.h)), pygame.RESIZABLE))
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
        if self.browser and event.type in (pygame.KEYDOWN, pygame.MOUSEWHEEL):
            if event.type == pygame.MOUSEWHEEL:
                self.browser.scroll(-event.y)
            elif event.key == pygame.K_ESCAPE:
                self.browser = None
            elif event.key == pygame.K_BACKSPACE:
                self.browser.back()
            elif event.key == pygame.K_RETURN:
                self._browser_action("browser_open")
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
            if self.browser or self.confirm_action or self.promotions:
                return
            if self.mode == "human":
                self.click_square(self.board_view.screen_to_square(event.pos, self.flipped))
            if self.mode != "home":
                items, _ = self.current_moves()
                if not self.move_view.handle_mouse_down(event.pos, items) and self.mode == "replay" and self.replay:
                    ply = self.move_view.handle_click(event.pos)
                    if ply is not None:
                        self.replay.goto_ply(ply)
        if self.browser or self.confirm_action or self.promotions:
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
                ("replay", "棋譜回放", "依日期、批次選擇對局"),
            ]):
                x = 64 + 260 * i
                self.draw_rect(PANEL, (x, 288, 244, 176), border_radius=10)
                self.text(subtitle, x + 12, 322, muted=True, width=220)
                self.button("mode:" + mode, title, (x + 12, 392, 220, 48), primary=mode == "auto")
            self.text("棋譜回放也可使用 --replay 直接開啟指定檔案。", 64, 522, muted=True)
        elif self.mode == "auto":
            self._render_batch()
        else:
            self._render_game()
        self.draw_rect(PANEL, (0, 0, LOGICAL_SIZE[0], HEADER_HEIGHT))
        self.text("Chess AI", 18, 10, large=True)
        if self.mode != "home":
            if self.mode != "auto":
                self.button("flip", "翻轉 F", (664, 10, 104, 36))
            self.button("home", "回首頁", (780, 10, 104, 36))
        if self.confirm_action:
            self._render_confirmation()
        elif self.promotions:
            self._render_promotion()
        elif self.browser:
            self._render_browser()

    def _render_game(self):
        items, ply = self.current_moves()
        board = self.replay.current_board() if self.mode == "replay" and self.replay else (
            self.live.board if self.live and self.mode != "replay" else create_board())
        destinations = {m.to_square for m in self.live.legal_from(self.selected)} if self.live and self.selected is not None else set()
        self.board_view.render(board, ply, len(items), self.flipped,
                               selected=self.selected, destinations=destinations)
        self.draw_rect(PANEL, (BOARD_PIXELS, HEADER_HEIGHT, MOVE_LIST_WIDTH, 336))
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
            fields = [("color", "我執", "白方" if self.human_color else "黑方"),
                      ("opponent", "對手", self.opponent)]
        fields.append(("interval", "間隔", f"{self.interval:g} 秒"))
        for i, (action, label, value) in enumerate(fields):
            y = 119 + i * 46
            self.text(label, x, y + 7)
            self.button(action, value, (x + 56, y, 176, 36))
        self.button("start", "開始對戰", (x, 270, 232, 42), primary=True)
        self.text("點選設定可切換選項", x, 324, muted=True)
        self.draw_label(self.small_font, "和棋政策：不自動申請", (x, 352), MUTED)

    def _render_live_panel(self, x):
        session = self.live
        player_name = lambda name: "真人" if name == "Human" else name
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
            info = build_replay_info(self.replay_data)
            for i, (label, key) in enumerate([("白方", "white_player"), ("黑方", "black_player"),
                                              ("結果", "result"), ("編號", "game_id")]):
                self.draw_label(self.small_font, f"{label}：{info[key]}", (x, 141 + i * 24), TEXT, 230)
            reason = self.replay_data.get("metadata", {}).get("termination", "")
            self.draw_label(self.small_font, REASONS.get(reason, reason), (x, 238), MUTED, 230)
        for i, (action, label) in enumerate([("first", "起點"), ("prev", "上步"), ("next", "下步"), ("last", "終點")]):
            enabled = self.replay is not None and (self.replay.current_ply > 0 if i < 2 else self.replay.current_ply < self.replay.total_ply())
            self.button(action, label, (x + i * 59, 270, 55, 36), enabled=enabled)
        self.button("open", "選擇對局", (x, 320, 111, 38), primary=self.replay is None)
        if self.replay_is_local_game:
            self.button("export", "匯出本局", (x + 121, 320, 111, 38))
        else:
            self.button("sample", "範例棋譜", (x + 121, 320, 111, 38))

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
        self.text("確認後等待目前落子與保存完成。" if self.batch else "取消後可繼續，或先停止並保存棋譜。", 238, 373, muted=True)
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
        self.text("批次自動對戰", 100, 120, large=True)
        if self.batch is None:
            self.text("固定白黑方配置；間隔是兩場之間的等待秒數。", 100, 166, muted=True)
            fields = [("white", "白方", self.white), ("black", "黑方", self.black),
                      ("interval", "場間間隔（秒）", f"{self.batch_interval:g}"),
                      ("count", "場次", str(self.game_count))]
            for index, (action, label, value) in enumerate(fields):
                y = 225 + index * 64
                self.text(label, 100, y + 9)
                if self.numeric_focus == action:
                    value = self.numeric_text + " |"
                self.button(action, value, (340, y, 360, 44), primary=self.numeric_focus == action)
            self.text("數字欄位可輸入，Ctrl+A 全選，Enter 確認。", 100, 510, muted=True)
            self.button("start", "開始生成", (100, 564, 600, 48), primary=True)
        else:
            state = self.batch.snapshot()
            status = state["status"]
            labels = {"running": "生成中", "paused": "已暫停", "stopping": "正在停止並保存",
                      "completed": "批次完成", "stopped": "已停止", "failed": "生成失敗"}
            self.text(labels.get(status, status), 100, 202, large=True)
            self.text(f"目前第 {state['current_game']} / {state['requested_games']} 場", 100, 280)
            self.draw_rect(BORDER, (100, 330, 700, 22), border_radius=8)
            width = round(700 * state["saved_games"] / state["requested_games"])
            if width:
                self.draw_rect(ACCENT, (100, 330, width, 22), border_radius=8)
            self.text(f"已保存 {state['saved_games']} / {state['requested_games']} 場", 100, 380, muted=True)
            self.text(state["batch_id"], 100, 418, muted=True)
            if status in ("running", "paused", "stopping"):
                self.button("pause", "繼續" if status == "paused" else "暫停", (100, 500, 330, 44), enabled=status != "stopping")
                self.button("stop", "停止並保存", (470, 500, 330, 44), enabled=status != "stopping")
            else:
                self.button("view_batch", "查看本批次", (100, 500, 330, 44), primary=True, enabled=state["saved_games"] > 0)
                self.button("restart", "重新設定", (470, 500, 330, 44))
            if state["error"]:
                self.text(state["error"], 100, 565, width=700)
        self.text(self.message, 100, 642, width=700, muted=True)

    def _render_browser(self):
        browser = self.browser
        self._modal((70, 90, 760, 630))
        self.text("選擇回放對局", 94, 111, large=True)
        group_label = "非批次" if browser.group == "standalone" else browser.group
        breadcrumb = "日期" + ("  ›  " + browser.date if browser.date else "") + ("  ›  " + group_label if group_label else "")
        self.text(breadcrumb, 94, 160, muted=True, width=710)
        options = browser.options()
        for row, index in enumerate(range(browser.offset, min(len(options), browser.offset + browser.PAGE_SIZE))):
            option = options[index]
            y = 208 + row * 72
            if browser.level != "game":
                label = option if browser.level == "date" else option[1]
                self.button(f"entry:{index}", label, (94, y, 712, 62))
            else:
                self.button(f"entry:{index}", "", (94, y, 712, 62))
                if browser.selected == index:
                    self.draw_rect((48, 63, 80), (94, y, 712, 62), border_radius=6)
                    self.draw_rect((140, 174, 205), (94, y, 712, 62), 2, border_radius=6)
                self.draw_label(self.small_font, f"{option.time_label} · {option.game_id}", (108, y + 5), MUTED, 675)
                white_badge, black_badge = result_badges(option.result)
                for x, side, player, badge in [(108, "白方", option.white, white_badge), (452, "黑方", option.black, black_badge)]:
                    self.draw_label(self.font, f"{side} · {'真人' if player == 'Human' else player}", (x, y + 30), TEXT, 232)
                    self.draw_label(self.font, badge[0], (x + 242, y + 30), badge[1], 95)
        if not options:
            self.text("目前沒有可選擇的對局。", 108, 238, muted=True)
        detail = browser.error or (f"已略過 {browser.skipped} 筆無法讀取的資料。" if browser.skipped else "依日期、批次或非批次選擇對局，再按播放。")
        self.draw_label(self.small_font, detail, (94, 582), MUTED, 712)
        self.draw_label(self.small_font, f"{len(options)} 個項目 · 滾輪捲動", (94, 610), MUTED)
        self.button("browser_up", "上一層", (94, 658, 152, 38), enabled=browser.level != "date")
        self.button("browser_refresh", "重新整理", (258, 658, 152, 38))
        self.button("browser_cancel", "關閉", (422, 658, 152, 38))
        self.button("browser_open", "播放", (586, 658, 220, 38), primary=True, enabled=browser.selected_entry() is not None)
