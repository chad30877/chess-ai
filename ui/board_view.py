"""Board rendering primitives for replay-oriented pygame UIs."""

from pathlib import Path

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

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.status_font = pygame.font.SysFont(None, 28)
        self.hint_font = pygame.font.SysFont(None, 22)
        self.coord_font = pygame.font.SysFont(None, 20)
        self.piece_images = self._load_piece_images()

    def _load_piece_images(self) -> dict[str, pygame.Surface]:
        project_root = Path(__file__).resolve().parents[1]
        piece_dir = project_root / "assets" / "pieces"
        piece_names = ["wp", "wn", "wb", "wr", "wq", "wk", "bp", "bn", "bb", "br", "bq", "bk"]
        images: dict[str, pygame.Surface] = {}

        for name in piece_names:
            image_path = piece_dir / f"{name}.png"
            image = pygame.image.load(str(image_path)).convert_alpha()
            images[name] = pygame.transform.smoothscale(image, (SQUARE_SIZE, SQUARE_SIZE))

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

        return col * SQUARE_SIZE, row * SQUARE_SIZE

    def draw_board(self) -> None:
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                color = LIGHT_COLOR if (row + col) % 2 == 0 else DARK_COLOR
                rect = pygame.Rect(col * SQUARE_SIZE, row * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
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
            x = col * SQUARE_SIZE + SQUARE_SIZE - 14
            y = row * SQUARE_SIZE + SQUARE_SIZE - 18
            self.screen.blit(text_surface, (x, y))

        for row, rank_label in enumerate(ranks):
            col = 0
            text_color = COORD_DARK if (row + col) % 2 == 0 else COORD_LIGHT
            text_surface = self.coord_font.render(rank_label, True, text_color)
            x = col * SQUARE_SIZE + 6
            y = row * SQUARE_SIZE + 4
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
        status_rect = pygame.Rect(0, BOARD_PIXELS, WINDOW_WIDTH, STATUS_HEIGHT)
        pygame.draw.rect(self.screen, TEXT_BACKGROUND, status_rect)

        orientation = "Black bottom" if is_flipped else "White bottom"
        status_text = f"Ply: {current_ply} / {total_ply}   View: {orientation}"
        hint_text = "Keys: Left/Right prev-next   Home/End first-last   F flip"

        status_surface = self.status_font.render(status_text, True, TEXT_COLOR)
        hint_surface = self.hint_font.render(hint_text, True, HINT_COLOR)

        self.screen.blit(status_surface, (12, BOARD_PIXELS + 8))
        self.screen.blit(hint_surface, (12, BOARD_PIXELS + 38))

    def render(
        self,
        board: chess.Board,
        current_ply: int,
        total_ply: int,
        is_flipped: bool,
    ) -> None:
        self.screen.fill(TEXT_BACKGROUND)
        self.draw_board()
        self.draw_coordinates(is_flipped)
        self.draw_pieces(board, is_flipped)
        self.draw_status_text(current_ply, total_ply, is_flipped)
