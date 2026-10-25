"""以應用事件及棋盤輸出驗證最後一手標示。"""

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import chess
import pygame
from apps.chess_application import APP_SIZE, ChessApplication
from tests.helpers.executors import ManualExecutor


class LastMoveTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode(APP_SIZE)
        self.app = ChessApplication(self.screen, executor=ManualExecutor())
        self.addCleanup(pygame.quit)
        self.addCleanup(self.app.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def open_moves(self, moves, fen=chess.STARTING_FEN):
        path = Path(self.folder.name) / 'replay.json'
        path.write_text(json.dumps(dict(initial_fen=fen, moves_uci=moves)), encoding='utf-8')
        self.assertTrue(self.app.open_replay(path))

    def key(self, key):
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0))
        self.app.render()

    def highlighted(self):
        self.app.render()
        view = self.app.board_view
        found = set()
        for square in chess.SQUARES:
            file, rank = chess.square_file(square), chess.square_rank(square)
            col, row = (7-file, rank) if self.app.flipped else (file, 7-rank)
            color = self.app.screen.get_at((view.origin_x + col*view.square_size + view.square_size//5,
                                           view.origin_y + row*view.square_size + view.square_size//5))
            if color.g > color.r and color.g > color.b:
                found.add(chess.square_name(square))
        return found

    def test_replay_navigation_marks_current_last_move(self):
        self.open_moves(['e2e4', 'e7e5', 'g1f3'])
        self.assertEqual(self.highlighted(), set())
        self.key(pygame.K_END)
        self.assertEqual(self.highlighted(), {'g1', 'f3'})
        self.key(pygame.K_LEFT)
        self.assertEqual(self.highlighted(), {'e7', 'e5'})
        self.key(pygame.K_HOME)
        self.assertEqual(self.highlighted(), set())
        self.key(pygame.K_RIGHT)
        self.assertEqual(self.highlighted(), {'e2', 'e4'})

    def test_special_moves_flip_resize_and_history_free_positions(self):
        cases = [
            (['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1e2', 'g8f6', 'e1g1'], {'e1', 'f1', 'g1', 'h1'}),
            (['e2e4', 'a7a6', 'e4e5', 'd7d5', 'e5d6'], {'e5', 'd5', 'd6'}),
        ]
        for moves, squares in cases:
            with self.subTest(moves=moves):
                self.open_moves(moves)
                self.key(pygame.K_END)
                self.assertEqual(self.highlighted(), squares)
                self.key(pygame.K_f)
                self.assertEqual(self.highlighted(), squares)
                self.app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, size=(1350, 1152), w=1350, h=1152))
                self.assertEqual(self.highlighted(), squares)
                fen = self.app.replay.current_board().fen()
                self.open_moves([], fen)
                self.assertEqual(self.highlighted(), set())

    def test_human_move_and_selection_preserve_last_move(self):
        def click(action):
            self.app.render()
            button = next(b for b in self.app.buttons if b.action == action)
            self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center))
        def square(name):
            sq = chess.parse_square(name)
            view = self.app.board_view
            col, row = chess.square_file(sq), 7-chess.square_rank(sq)
            self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                pos=(int(view.origin_x+(col+.5)*view.square_size), int(view.origin_y+(row+.5)*view.square_size))))
            self.app.render()
        click('mode:human')
        click('start')
        self.assertEqual(self.highlighted(), set())
        square('e2')
        square('e4')
        self.assertEqual(self.app.live.board.peek().uci(), 'e2e4')
        self.assertEqual(self.highlighted(), {'e2', 'e4'})
