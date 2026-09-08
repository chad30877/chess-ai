"""Small pygame controls shared by the demo screens."""

from dataclasses import dataclass
from pathlib import Path

import pygame

BACKGROUND = (25, 27, 24)
PANEL = (35, 38, 32)
TEXT = (240, 242, 235)
MUTED = (180, 187, 171)
ACCENT = (82, 116, 66)
BORDER = (76, 82, 69)


def ui_font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("microsoftjhenghei,notosanscjktc,notosanscjk,wenquanyizenhei,arial", size)


def draw_text(screen, font, text, pos, color=TEXT, width=None):
    text = str(text)
    if width is not None and font.size(text)[0] > width:
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        text += "…"
    screen.blit(font.render(text, True, color), pos)


@dataclass
class Button:
    action: str
    label: str
    rect: pygame.Rect
    enabled: bool = True
    primary: bool = False

    def draw(self, screen, font):
        pygame.draw.rect(screen, ACCENT if self.primary else PANEL, self.rect, border_radius=6)
        pygame.draw.rect(screen, BORDER, self.rect, 1, border_radius=6)
        color = TEXT if self.enabled else (113, 120, 107)
        text = self.label
        if font.size(text)[0] > self.rect.width - 16:
            while text and font.size(text + "…")[0] > self.rect.width - 16:
                text = text[:-1]
            text += "…"
        label = font.render(text, True, color)
        screen.blit(label, label.get_rect(center=self.rect.center))


class ReplayBrowser:
    """Local JSON picker, with no tkinter or additional runtime dependency."""

    PAGE_SIZE = 9

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.entries: list[Path] = []
        self.selected: int | None = None
        self.offset = 0
        self.error = ""
        self.path_text = str(self.directory)
        self.path_focused = False
        self.refresh()

    def refresh(self):
        try:
            self.entries = sorted((p for p in self.directory.iterdir()
                                   if p.is_dir() or p.suffix.lower() == ".json"),
                                  key=lambda p: (not p.is_dir(), p.name.lower()))
            self.error = ""
        except OSError as exc:
            self.entries = []
            self.error = str(exc)
        self.offset = 0
        self.selected = None
        self.path_text = str(self.directory)

    def open_path(self, path: Path) -> Path | None:
        try:
            path = path.expanduser().resolve()
            if path.is_dir():
                self.directory = path
                self.refresh()
            elif path.is_file() and path.suffix.lower() == ".json":
                return path
            else:
                self.error = "請選擇資料夾或存在的 JSON 棋譜。"
        except (OSError, ValueError) as exc:
            self.error = str(exc)
        return None

    def scroll(self, amount: int):
        self.offset = max(0, min(self.offset + amount, max(0, len(self.entries) - self.PAGE_SIZE)))

    def selected_path(self) -> Path | None:
        return self.entries[self.selected] if self.selected is not None else None
