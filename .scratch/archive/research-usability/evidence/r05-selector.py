"""重現 R05 事件操作與畫面證據；使用暫存評分設定，不碰研究資料。"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import pygame
from tests.ui.test_profile_selector import ProfileSelectorTest
from engine.evaluation.config import EvaluationConfig

case = ProfileSelectorTest()
case.setUpClass()
case.setUp()
try:
    payload = EvaluationConfig.material_only().to_dict()
    payload['terms']['pawn_mobility']['enabled'] = True
    payload['terms']['king_pawn_shield']['enabled'] = True
    for i in range(23):
        case.save_profile(f'研究候選{i:02}－活動力與王安全－較長的設定名稱用來檢查清單顯示與查找', EvaluationConfig.from_dict(payload))
    payload['terms']['bishop_pair']['enabled'] = True
    case.save_profile('研究候選加協調', EvaluationConfig.from_dict(payload))
    case.click('mode:auto')
    case.click('batch_mode:evaluation')
    case.click('comparison_candidate_add')
    case.search('研究候選')
    case.click('profile_group:mobility')
    case.click('profile_group:king_safety')
    case.click('profile_row:0')
    case.click('profile_row:1')
    case.app.render()
    folder = Path('.scratch/research-usability/evidence')
    pygame.image.save(case.app.screen, str(folder / 'r05-selector-many.png'))
    case.click('profile_exact')
    case.app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-100, x=0))
    case.click('profile_row:22')
    case.app.resize(pygame.Surface((900, 768)))
    case.app.render()
    pygame.image.save(case.app.screen, str(folder / 'r05-selector-scrolled.png'))
    case.click('profile_confirm')
    assert len(case.app.evaluation_fields.candidates) == 3
finally:
    case.doCleanups()
    case.tearDownClass()
