"""Replay metadata panel for replay-oriented pygame UIs."""

import pygame

from ui.move_list_view import MOVE_LIST_WIDTH, PANEL_BACKGROUND, PANEL_BORDER

INFO_PANEL_HEIGHT = 130
INFO_PADDING = 12
LINE_HEIGHT = 24
TITLE_COLOR = (245, 245, 245)
LABEL_COLOR = (180, 180, 180)
VALUE_COLOR = (235, 235, 235)


class ReplayInfoView:
    """Render basic replay metadata without interaction."""

    def __init__(self, screen: pygame.Surface, origin_x: int, origin_y: int = 0) -> None:
        self.screen = screen
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.width = MOVE_LIST_WIDTH
        self.height = INFO_PANEL_HEIGHT
        self.panel_rect = pygame.Rect(self.origin_x, self.origin_y, self.width, self.height)
        self.title_font = pygame.font.SysFont(None, 28)
        self.label_font = pygame.font.SysFont(None, 22)

    def render(self, replay_info: dict[str, str]) -> None:
        pygame.draw.rect(self.screen, PANEL_BACKGROUND, self.panel_rect)
        pygame.draw.line(
            self.screen,
            PANEL_BORDER,
            (self.origin_x, self.origin_y + self.height),
            (self.origin_x + self.width, self.origin_y + self.height),
            width=1,
        )

        title_surface = self.title_font.render("Replay Info", True, TITLE_COLOR)
        self.screen.blit(title_surface, (self.origin_x + INFO_PADDING, self.origin_y + INFO_PADDING))

        lines = [
            ("White", replay_info["white_player"]),
            ("Black", replay_info["black_player"]),
            ("Result", replay_info["result"]),
            ("Game ID", replay_info["game_id"]),
        ]

        start_y = self.origin_y + INFO_PADDING + 30
        for index, (label, value) in enumerate(lines):
            y = start_y + index * LINE_HEIGHT
            label_surface = self.label_font.render(f"{label}:", True, LABEL_COLOR)
            value_surface = self.label_font.render(str(value), True, VALUE_COLOR)
            self.screen.blit(label_surface, (self.origin_x + INFO_PADDING, y))
            self.screen.blit(value_surface, (self.origin_x + 88, y))
