"""R01 真實選檔短流程：隔離資料，保留結果供驗收。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import json
import tempfile
from time import monotonic
import pygame
import apps.chess_application as application
from engine.learning.dataset import create_dataset
from tests.test_learning_dataset import pgn_games

root = Path(tempfile.mkdtemp(prefix='chess-r01-'))
source = root / 'games.pgn'
source.write_text(pgn_games(2), encoding='utf-8')
create_dataset(root / 'data/learning', source)
evidence = Path(__file__).parent
(evidence / 'r01-runtime-root.txt').write_text(str(root), encoding='utf-8')
application.PROJECT_ROOT = root
pygame.init()
app = application.ChessApplication(pygame.display.set_mode(application.APP_SIZE, pygame.RESIZABLE))
pygame.display.set_caption('Chess AI - R01 原生選檔驗收')
for action in ('mode:learning', 'learning_open:0', 'learning_teacher'):
    app.render()
    button = next(b for b in app.buttons if b.action == action)
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
clock = pygame.time.Clock()
started = monotonic()
saved = None
try:
    while app.running and monotonic() - started < 600:
        for event in pygame.event.get():
            app.handle_event(event)
        app.tick()
        app.render()
        pygame.display.flip()
        state = app.learning.teacher.state
        if state.get('status') == 'completed' and saved != state.get('path'):
            saved = state.get('path')
            (evidence / 'r01-real-pilot.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            pygame.image.save(app.screen, str(evidence / 'r01-real-pilot.png'))
        clock.tick(30)
finally:
    app.close()
    pygame.quit()
