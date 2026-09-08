"""Right-side move list rendering for replay UIs."""

import pygame

MOVE_LIST_WIDTH = 260
PANEL_PADDING = 12
HEADER_HEIGHT = 32
ROW_HEIGHT = 28
SCROLL_STEP = 3
SCROLLBAR_WIDTH = 10
SCROLLBAR_MARGIN = 10
MIN_THUMB_HEIGHT = 32

PANEL_BACKGROUND = (34, 34, 34)
PANEL_BORDER = (60, 60, 60)
HEADER_COLOR = (245, 245, 245)
MOVE_NUMBER_COLOR = (170, 170, 170)
MOVE_TEXT_COLOR = (225, 225, 225)
CURRENT_MOVE_BACKGROUND = (88, 120, 76)
CURRENT_MOVE_TEXT = (255, 255, 255)
SCROLLBAR_TRACK = (55, 55, 55)
SCROLLBAR_THUMB = (140, 140, 140)


class MoveListView:
    """Render move history and map mouse clicks back to plies."""

    def __init__(self, screen: pygame.Surface, origin_x: int, origin_y: int, height: int, scale: float = 1.0) -> None:
        self.screen = screen
        self.scale = scale
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.height = height
        self.panel_rect = pygame.Rect(self.origin_x, self.origin_y, round(MOVE_LIST_WIDTH * self.scale), self.height)
        self.header_font = pygame.font.SysFont(None, round(28 * self.scale))
        self.move_font = pygame.font.SysFont(None, round(24 * self.scale))
        self.scroll_offset = 0
        self.click_targets: list[tuple[pygame.Rect, int]] = []
        self.is_dragging_thumb = False
        self.thumb_drag_offset_y = 0

    @property
    def visible_count(self) -> int:
        available_height = self.height - round(PANEL_PADDING * self.scale)
        return max(1, available_height // round(ROW_HEIGHT * self.scale) - 2) # 不知為何但最後'-2'才是正確的

    def _group_rows(self, move_items: list[dict]) -> list[tuple[int, dict | None, dict | None]]:
        rows: list[tuple[int, dict | None, dict | None]] = []

        for item in move_items:
            if item["side"] == "w":
                rows.append((item["move_no"], item, None))
                continue

            if rows and rows[-1][0] == item["move_no"] and rows[-1][2] is None:
                move_no, white_item, _ = rows[-1]
                rows[-1] = (move_no, white_item, item)
            else:
                rows.append((item["move_no"], None, item))

        return rows

    def _max_scroll(self, total_rows: int) -> int:
        return max(0, total_rows - self.visible_count)

    def _clamp_scroll(self, total_rows: int) -> None:
        self.scroll_offset = max(0, min(self.scroll_offset, self._max_scroll(total_rows)))

    def _get_start_y(self) -> int:
        return self.origin_y + round(PANEL_PADDING * self.scale) + round(HEADER_HEIGHT * self.scale)

    def _get_row_y(self, visible_row_index: int) -> int:
        return self._get_start_y() + visible_row_index * round(ROW_HEIGHT * self.scale)

    def _get_item_rect(self, side: str, y: int) -> pygame.Rect:
        if side == "w":
            return pygame.Rect(self.origin_x + round(48 * self.scale), y, round(78 * self.scale), round(ROW_HEIGHT * self.scale) - 2)
        return pygame.Rect(self.origin_x + round(138 * self.scale), y, round(78 * self.scale), round(ROW_HEIGHT * self.scale) - 2)

    def _get_visible_rows(
        self,
        rows: list[tuple[int, dict | None, dict | None]],
    ) -> list[tuple[int, dict | None, dict | None]]:
        return rows[self.scroll_offset : self.scroll_offset + self.visible_count]

    def _find_row_index_for_ply(
        self,
        rows: list[tuple[int, dict | None, dict | None]],
        current_ply: int,
    ) -> int | None:
        if current_ply <= 0:
            return None

        for row_index, (_, white_item, black_item) in enumerate(rows):
            if white_item is not None and white_item["ply"] == current_ply:
                return row_index
            if black_item is not None and black_item["ply"] == current_ply:
                return row_index
        return None

    def _get_scrollbar_track_rect(self) -> pygame.Rect:
        track_height = self.height - 2 * round(PANEL_PADDING * self.scale)
        track_x = self.origin_x + round(MOVE_LIST_WIDTH * self.scale) - round(SCROLLBAR_MARGIN * self.scale) - round(SCROLLBAR_WIDTH * self.scale)
        return pygame.Rect(track_x, self.origin_y + round(PANEL_PADDING * self.scale), round(SCROLLBAR_WIDTH * self.scale), track_height)

    def _get_scrollbar_thumb_rect(self, total_rows: int) -> pygame.Rect:
        track_rect = self._get_scrollbar_track_rect()

        if total_rows <= 0:
            return track_rect.copy()

        max_scroll = self._max_scroll(total_rows)
        visible_ratio = min(1.0, self.visible_count / total_rows)
        thumb_height = max(round(MIN_THUMB_HEIGHT * self.scale), int(track_rect.height * visible_ratio))
        thumb_height = min(track_rect.height, thumb_height)

        if max_scroll == 0:
            thumb_y = track_rect.y
        else:
            travel = track_rect.height - thumb_height
            thumb_y = track_rect.y + int(travel * (self.scroll_offset / max_scroll))

        return pygame.Rect(track_rect.x, thumb_y, round(SCROLLBAR_WIDTH * self.scale), thumb_height)

    def _set_scroll_from_thumb_top(self, thumb_top: int, total_rows: int) -> None:
        track_rect = self._get_scrollbar_track_rect()
        thumb_rect = self._get_scrollbar_thumb_rect(total_rows)
        max_scroll = self._max_scroll(total_rows)

        if max_scroll == 0:
            self.scroll_offset = 0
            return

        travel = track_rect.height - thumb_rect.height
        if travel <= 0:
            self.scroll_offset = 0
            return

        clamped_thumb_top = max(track_rect.y, min(thumb_top, track_rect.bottom - thumb_rect.height))
        relative = (clamped_thumb_top - track_rect.y) / travel
        self.scroll_offset = round(relative * max_scroll)
        self._clamp_scroll(total_rows)

    def _draw_move_item(self, item: dict, rect: pygame.Rect, is_current: bool) -> None:
        if is_current:
            pygame.draw.rect(self.screen, CURRENT_MOVE_BACKGROUND, rect, border_radius=4)
            text_color = CURRENT_MOVE_TEXT
        else:
            text_color = MOVE_TEXT_COLOR

        text_surface = self.move_font.render(item["san"], True, text_color)
        self.screen.blit(text_surface, (rect.x + 6, rect.y + 4))
        self.click_targets.append((rect, item["ply"]))

    def _draw_scrollbar(self, total_rows: int) -> None:
        track_rect = self._get_scrollbar_track_rect()
        pygame.draw.rect(self.screen, SCROLLBAR_TRACK, track_rect, border_radius=4)
        thumb_rect = self._get_scrollbar_thumb_rect(total_rows)
        pygame.draw.rect(self.screen, SCROLLBAR_THUMB, thumb_rect, border_radius=4)

    def ensure_ply_visible(self, move_items: list[dict], current_ply: int) -> None:
        rows = self._group_rows(move_items)
        total_rows = len(rows)
        self._clamp_scroll(total_rows)

        if current_ply <= 0:
            self.scroll_offset = 0
            return

        target_row_index = self._find_row_index_for_ply(rows, current_ply)
        if target_row_index is None:
            return

        first_visible = self.scroll_offset
        last_visible = self.scroll_offset + self.visible_count - 1

        if target_row_index < first_visible:
            self.scroll_offset = target_row_index
        elif target_row_index > last_visible:
            self.scroll_offset = target_row_index - self.visible_count + 1

        self._clamp_scroll(total_rows)

    def render(self, move_items: list[dict], current_ply: int) -> None:
        rows = self._group_rows(move_items)
        total_rows = len(rows)
        self._clamp_scroll(total_rows)

        pygame.draw.rect(self.screen, PANEL_BACKGROUND, self.panel_rect)
        pygame.draw.line(
            self.screen,
            PANEL_BORDER,
            (self.origin_x, self.origin_y),
            (self.origin_x, self.origin_y + self.height),
            width=1,
        )

        title_surface = self.header_font.render("Moves", True, HEADER_COLOR)
        self.screen.blit(title_surface, (self.origin_x + round(PANEL_PADDING * self.scale), self.origin_y + round(PANEL_PADDING * self.scale)))

        self.click_targets = []
        visible_rows = self._get_visible_rows(rows)

        for row_index, (move_no, white_item, black_item) in enumerate(visible_rows):
            y = self._get_row_y(row_index)
            if y + round(ROW_HEIGHT * self.scale) > self.origin_y + self.height - round(PANEL_PADDING * self.scale):
                break

            move_no_surface = self.move_font.render(f"{move_no}.", True, MOVE_NUMBER_COLOR)
            self.screen.blit(move_no_surface, (self.origin_x + round(PANEL_PADDING * self.scale), y + 4))

            if white_item is not None:
                white_rect = self._get_item_rect("w", y)
                self._draw_move_item(white_item, white_rect, current_ply == white_item["ply"])

            if black_item is not None:
                black_rect = self._get_item_rect("b", y)
                self._draw_move_item(black_item, black_rect, current_ply == black_item["ply"])

        self._draw_scrollbar(total_rows)

    def handle_click(self, mouse_pos: tuple[int, int]) -> int | None:
        for rect, ply in self.click_targets:
            if rect.collidepoint(mouse_pos):
                return ply
        return None

    def handle_mouse_down(self, mouse_pos: tuple[int, int], move_items: list[dict]) -> bool:
        total_rows = len(self._group_rows(move_items))
        if total_rows <= self.visible_count:
            return False

        thumb_rect = self._get_scrollbar_thumb_rect(total_rows)
        if not thumb_rect.collidepoint(mouse_pos):
            return False

        self.is_dragging_thumb = True
        self.thumb_drag_offset_y = mouse_pos[1] - thumb_rect.y
        return True

    def handle_mouse_motion(self, mouse_pos: tuple[int, int], move_items: list[dict]) -> None:
        if not self.is_dragging_thumb:
            return

        total_rows = len(self._group_rows(move_items))
        if total_rows <= self.visible_count:
            self.is_dragging_thumb = False
            return

        thumb_top = mouse_pos[1] - self.thumb_drag_offset_y
        self._set_scroll_from_thumb_top(thumb_top, total_rows)

    def handle_mouse_up(self) -> None:
        self.is_dragging_thumb = False

    def handle_wheel(self, mouse_pos: tuple[int, int], wheel_y: int, move_items: list[dict]) -> None:
        if not self.panel_rect.collidepoint(mouse_pos):
            return

        total_rows = len(self._group_rows(move_items))
        if total_rows <= self.visible_count or wheel_y == 0:
            return

        self.scroll_offset -= wheel_y * SCROLL_STEP
        self._clamp_scroll(total_rows)
