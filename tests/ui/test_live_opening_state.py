"""真人事件中的開局政策、背景搜尋與批次開局步數。"""
import json
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import chess
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor


class LiveOpeningUiTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.addCleanup(pygame.quit)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        from engine.evaluation.config import EvaluationConfig
        profiles = self.root / 'configs/evaluation'
        profiles.mkdir(parents=True)
        (profiles / 'stable.json').write_text(json.dumps(EvaluationConfig().to_dict()), encoding='utf-8')
        self.now = 100
        self.executor = ManualExecutor()
        with patch('apps.chess_application.PROJECT_ROOT', self.root):
            self.app = ChessApplication(pygame.display.set_mode(APP_SIZE), executor=self.executor, now=lambda: self.now)
        self.addCleanup(self.app.close)

    def click(self, action):
        self.app.render()
        button = next(b for b in self.app.buttons if b.action == action)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))

    def square(self, name):
        square = chess.parse_square(name)
        view = self.app.board_view
        file, rank = chess.square_file(square), chess.square_rank(square)
        col, row = (7-file, rank) if self.app.flipped else (file, 7-rank)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
            pos=(view.origin_x+col*view.square_size+view.square_size//2,
                 view.origin_y+row*view.square_size+view.square_size//2)))

    def start_human(self, opponent='AlphaBeta', limit=2):
        self.click('mode:human')
        self.app.opponent = opponent
        self.app.opening_book = True
        self.app.opening_max_plies = limit
        self.app.live_search_depth = 1
        self.click('start')

    def test_book_move_then_wait_then_actual_search(self):
        self.start_human()
        game = self.app.live
        self.assertTrue(game.in_opening_book)
        self.assertTrue(game.human_turn)
        self.square('e2'); self.square('e4')
        self.assertFalse(game.thinking)
        self.now += 2
        self.app.tick()
        self.assertEqual(len(game.board.move_stack), 2)
        self.assertEqual(game.replay_payload()['metadata']['opening_book']['moves_uci'],
                         [move.uci() for move in game.board.move_stack])
        self.assertFalse(game.in_opening_book)
        self.assertFalse(game.thinking)
        self.square('g1'); self.square('f3')
        self.app.tick()
        self.assertFalse(game.thinking)
        self.now += 2
        self.app.tick()
        self.assertTrue(game.thinking)
        self.assertFalse(game.in_opening_book)
        self.executor.finish()
        self.app.tick()
        self.assertTrue(game.human_turn)
        self.assertFalse(game.thinking)

    def test_non_book_strategy_and_terminal_states(self):
        self.start_human(opponent='Random')
        game = self.app.live
        self.assertFalse(game.in_opening_book)
        self.square('e2'); self.square('e4')
        self.now += 2
        self.app.tick()
        self.assertTrue(game.thinking)
        game.pause()
        self.app.render()
        self.assertEqual(game.status, 'paused')
        game.resume()
        self.executor.jobs[-1][0].set_exception(RuntimeError('controlled worker failure'))
        self.app.tick()
        self.app.render()
        self.assertEqual(game.status, 'failed')
        self.assertFalse(game.thinking)
        self.assertFalse(game.in_opening_book)
        self.click('restart')
        self.click('confirm')
        self.app.opponent = 'AlphaBeta'
        self.app.opening_book = True
        self.click('start')
        self.click('stop')
        self.assertEqual(self.app.live.status, 'stopped')
        self.assertFalse(self.app.live.thinking)

    def test_general_batch_two_steps_are_two_saved_plies(self):
        self.click('mode:auto')
        self.app.white = self.app.black = 'AlphaBeta'
        self.app.batch_search_depth = 1
        self.app.game_count = self.app.batch_workers = 1
        self.click('opening_book')
        self.click('opening_limit')
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='2'))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
        self.click('start')
        self.app.batch.settings = replace(self.app.batch.settings, max_plies=3)
        self.executor.finish()
        self.app.render()
        state = self.app.batch.snapshot()
        self.assertEqual(state['status'], 'completed', state.get('error'))
        replay = json.loads(next((Path(state['path']) / 'replays').glob('*.json')).read_text(encoding='utf-8'))
        opening = replay['metadata']['opening_book']
        self.assertEqual(opening['max_plies'], 2)
        self.assertEqual(opening['moves_uci'], replay['moves_uci'][:2])
        self.assertEqual(opening['exit_ply'], 2)
        self.assertEqual(opening['exit_reason'], 'limit')
