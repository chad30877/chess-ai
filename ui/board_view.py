"""Board rendering primitives for replay-oriented pygame UIs."""

from pathlib import Path
from io import BytesIO
from xml.etree import ElementTree as ET
import chess.svg

import chess
import pygame

BOARD_SIZE = 8
SQUARE_SIZE = 80
BOARD_PIXELS = BOARD_SIZE * SQUARE_SIZE
STATUS_HEIGHT = 72
WINDOW_WIDTH = BOARD_PIXELS
WINDOW_HEIGHT = BOARD_PIXELS + STATUS_HEIGHT

LIGHT_COLOR = (240, 217, 181)
DARK_COLOR = (181, 136, 99)
TEXT_COLOR = (245, 245, 245)
TEXT_BACKGROUND = (25, 25, 25)
COORD_LIGHT = (245, 245, 245)
COORD_DARK = (70, 70, 70)
HINT_COLOR = (210, 210, 210)


class BoardView:
    """Render a chess board, pieces, and a minimal replay status line."""

    def __init__(self, screen: pygame.Surface, origin_y: int = 0, *, origin_x: int = 0, square_size: int = SQUARE_SIZE) -> None:
        self.screen = screen
        self.origin_y = origin_y
        self.origin_x = origin_x
        self.square_size = square_size
        self.board_pixels = 8 * square_size
        self.scale = square_size / SQUARE_SIZE
        self.status_font = pygame.font.SysFont(None, round(28 * self.scale))
        self.hint_font = pygame.font.SysFont(None, round(22 * self.scale))
        self.coord_font = pygame.font.SysFont(None, round(20 * self.scale))
        self.piece_images = self._load_piece_images()

    def _load_piece_images(self) -> dict[str, pygame.Surface]:
        project_root = Path(__file__).resolve().parents[1]
        piece_dir = project_root / "assets" / "pieces"
        piece_names = ["wp", "wn", "wb", "wr", "wq", "wk", "bp", "bn", "bb", "br", "bq", "bk"]
        images: dict[str, pygame.Surface] = {}

        for name in piece_names:
            image_path = piece_dir / f"{name}.png"
            try:
                piece = chess.Piece.from_symbol(name[1].upper() if name[0] == "w" else name[1])
                svg = ET.fromstring(chess.svg.piece(piece, size=self.square_size))
                # SDL_image's SVG renderer does not scale this viewBox consistently.
                # Transform vector paths explicitly before rasterizing at native size.
                svg.set("viewBox", f"0 0 {self.square_size} {self.square_size}")
                group = ET.Element("{http://www.w3.org/2000/svg}g",
                                   {"transform": f"scale({self.square_size / 45})"})
                for child in list(svg):
                    svg.remove(child)
                    group.append(child)
                svg.append(group)
                image = pygame.image.load(BytesIO(ET.tostring(svg)), "piece.svg").convert_alpha()
            except pygame.error:
                image = pygame.image.load(str(image_path)).convert_alpha()
            images[name] = pygame.transform.smoothscale(image, (self.square_size, self.square_size))

        return images

    def _square_to_screen(self, square: chess.Square, is_flipped: bool) -> tuple[int, int]:
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)

        if is_flipped:
            col = BOARD_SIZE - 1 - file_index
            row = rank_index
        else:
            col = file_index
            row = BOARD_SIZE - 1 - rank_index

        return self.origin_x + col * self.square_size, self.origin_y + row * self.square_size

    def screen_to_square(self, pos: tuple[int, int], is_flipped: bool = False) -> chess.Square | None:
        x, y = pos[0] - self.origin_x, pos[1] - self.origin_y
        if not (0 <= x < self.board_pixels and 0 <= y < self.board_pixels):
            return None
        col, row = x // self.square_size, y // self.square_size
        return chess.square(7 - col, row) if is_flipped else chess.square(col, 7 - row)

    def draw_selection(self, selected: chess.Square | None, destinations: set[chess.Square],
                       is_flipped: bool) -> None:
        if selected is not None:
            x, y = self._square_to_screen(selected, is_flipped)
            pygame.draw.rect(self.screen, (230, 192, 65), (x, y, self.square_size, self.square_size), max(1, round(5 * self.scale)))
        for square in destinations:
            x, y = self._square_to_screen(square, is_flipped)
            pygame.draw.circle(self.screen, (65, 105, 60),
                               (x + self.square_size // 2, y + self.square_size // 2), round(12 * self.scale), max(1, round(4 * self.scale)))

    def draw_board(self) -> None:
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                color = LIGHT_COLOR if (row + col) % 2 == 0 else DARK_COLOR
                rect = pygame.Rect(self.origin_x + col * self.square_size, self.origin_y + row * self.square_size, self.square_size, self.square_size)
                pygame.draw.rect(self.screen, color, rect)

    def draw_coordinates(self, is_flipped: bool) -> None:
        files = list("abcdefgh")
        ranks = list("87654321")

        if is_flipped:
            files.reverse()
            ranks.reverse()

        for col, file_label in enumerate(files):
            row = BOARD_SIZE - 1
            text_color = COORD_DARK if (row + col) % 2 == 0 else COORD_LIGHT
            text_surface = self.coord_font.render(file_label, True, text_color)
            x = self.origin_x + col * self.square_size + self.square_size - round(14 * self.scale)
            y = self.origin_y + row * self.square_size + self.square_size - round(18 * self.scale)
            self.screen.blit(text_surface, (x, y))

        for row, rank_label in enumerate(ranks):
            col = 0
            text_color = COORD_DARK if (row + col) % 2 == 0 else COORD_LIGHT
            text_surface = self.coord_font.render(rank_label, True, text_color)
            x = self.origin_x + col * self.square_size + round(6 * self.scale)
            y = self.origin_y + row * self.square_size + round(4 * self.scale)
            self.screen.blit(text_surface, (x, y))

    def draw_pieces(self, board: chess.Board, is_flipped: bool) -> None:
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece is None:
                continue

            color_prefix = "w" if piece.color == chess.WHITE else "b"
            piece_key = f"{color_prefix}{piece.symbol().lower()}"
            x, y = self._square_to_screen(square, is_flipped)
            self.screen.blit(self.piece_images[piece_key], (x, y))

    def draw_status_text(self, current_ply: int, total_ply: int, is_flipped: bool) -> None:
        status_rect = pygame.Rect(self.origin_x, self.origin_y + self.board_pixels, self.board_pixels, STATUS_HEIGHT)
        pygame.draw.rect(self.screen, TEXT_BACKGROUND, status_rect)

        orientation = "Black bottom" if is_flipped else "White bottom"
        status_text = f"Ply: {current_ply} / {total_ply}   View: {orientation}"
        hint_text = "Keys: Left/Right prev-next   Home/End first-last   F flip"

        status_surface = self.status_font.render(status_text, True, TEXT_COLOR)
        hint_surface = self.hint_font.render(hint_text, True, HINT_COLOR)

        self.screen.blit(status_surface, (self.origin_x + 12, self.origin_y + self.board_pixels + 8))
        self.screen.blit(hint_surface, (self.origin_x + 12, self.origin_y + self.board_pixels + 38))

    def render(
        self,
        board: chess.Board,
        current_ply: int,
        total_ply: int,
        is_flipped: bool,
        selected: chess.Square | None = None,
        destinations: set[chess.Square] | None = None,
    ) -> None:
        self.screen.fill(TEXT_BACKGROUND)
        self.draw_board()
        self.draw_coordinates(is_flipped)
        self.draw_pieces(board, is_flipped)
        self.draw_selection(selected, destinations or set(), is_flipped)
        self.draw_status_text(current_ply, total_ply, is_flipped)
