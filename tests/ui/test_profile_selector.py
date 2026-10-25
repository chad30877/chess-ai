"""透過應用程式事件查找、選取並實際套用評分設定。"""

import json
import unittest

import pygame

from engine.evaluation.config import EvaluationConfig
from tests.ui import test_chess_application as application_tests


class ProfileSelectorTest(unittest.TestCase):
    setUpClass = classmethod(application_tests.ChessApplicationTest.setUpClass.__func__)
    tearDownClass = classmethod(application_tests.ChessApplicationTest.tearDownClass.__func__)
    setUp = application_tests.ChessApplicationTest.setUp
    click = application_tests.ChessApplicationTest.click
    enter_comparison_field = application_tests.ChessApplicationTest.enter_comparison_field

    def save_profile(self, name, config):
        path = self.project / 'configs/evaluation' / (name + '.json')
        path.write_text(json.dumps(config.to_dict()), encoding='utf-8')
        return path

    def search(self, text):
        self.click('profile_search')
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL))
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text=text))

    def test_live_search_confirm_applies_config_and_cancel_preserves_selection(self):
        config = EvaluationConfig.material_only()
        target = self.save_profile('中文純子力', config)
        self.click('mode:human')
        original = self.app.live_evaluation_file
        self.click('live_evaluation')
        self.search('中文')
        self.click('profile_row:0')
        self.click('profile_cancel')
        self.assertEqual(self.app.live_evaluation_file, original)
        self.click('live_evaluation')
        self.search('中文')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, target)
        self.click('start')
        self.assertEqual(self.app.live.settings.black_evaluation, config)

    def test_group_filter_uses_enabled_terms_and_exact_combination(self):
        payload = EvaluationConfig.material_only().to_dict()
        payload['terms']['pawn_mobility']['enabled'] = True
        payload['terms']['king_pawn_shield']['enabled'] = True
        payload['phase']['enabled'] = True
        pair = EvaluationConfig.from_dict(payload)
        exact = self.save_profile('研究兩組', pair)
        payload['terms']['bishop_pair']['enabled'] = True
        extra = self.save_profile('研究三組', EvaluationConfig.from_dict(payload))
        self.save_profile('研究mobility-king-safety', EvaluationConfig.material_only())
        self.click('mode:human')
        self.click('live_evaluation')
        self.search('研究')
        self.click('profile_group:mobility')
        self.click('profile_group:king_safety')
        self.click('profile_row:1')
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, exact)
        self.click('live_evaluation')
        self.search('研究')
        self.click('profile_group:mobility')
        self.click('profile_group:king_safety')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, extra)
        self.click('live_evaluation')
        self.search('研究')
        self.click('profile_group:mobility')
        self.click('profile_group:king_safety')
        self.click('profile_exact')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, exact)

    def test_scrolling_reaches_more_than_one_page(self):
        for i in range(18):
            target = self.save_profile(f'測試設定{i:02}', EvaluationConfig(pst_weight=i + 1))
        self.click('mode:human')
        self.click('live_evaluation')
        self.search('測試設定')
        self.app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-100, x=0))
        self.click('profile_row:17')
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, target)

    def test_general_batch_both_sides_use_selected_configs(self):
        config = EvaluationConfig.material_only()
        self.save_profile('指定子力', config)
        self.click('mode:auto')
        self.click('white')
        for side in ('white', 'black'):
            self.click('batch_evaluation_' + side)
            self.search('指定')
            self.click('profile_row:0')
            self.click('profile_confirm')
        self.click('start')
        self.assertEqual(self.app.batch.settings.white_evaluation, config)
        self.assertEqual(self.app.batch.settings.black_evaluation, config)

    def test_replay_select_save_and_reopen_finds_new_profile(self):
        config = EvaluationConfig.material_only()
        self.save_profile('原始子力', config)
        self.app.open_replay('data/replays/sample_replay.json')
        self.click('replay_edit')
        self.click('editor_profile')
        self.search('原始')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.replay_editor.config, config)
        self.click('editor_field:name')
        self.app.handle_event(pygame.event.Event(pygame.TEXTINPUT, text='另存子力'))
        self.click('editor_save')
        self.click('replay_edit')
        self.click('editor_profile')
        self.search('另存')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.replay_editor.config, config)
        self.assertEqual(self.app.replay_editor.profile_path.stem, '另存子力')

    def test_comparison_multiselect_excludes_baseline_and_cancel_is_transactional(self):
        base = self.save_profile('基準', EvaluationConfig.material_only())
        first = self.save_profile('候選甲', EvaluationConfig(pst_weight=2))
        second = self.save_profile('候選乙', EvaluationConfig(pst_weight=3))
        self.click('mode:auto')
        self.click('batch_mode:evaluation')
        self.click('comparison_file:baseline')
        self.search('基準')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertEqual(self.app.evaluation_fields.baseline, base)
        before = list(self.app.evaluation_fields.candidates)
        self.click('comparison_candidate_add')
        self.search('候選')
        self.click('profile_row:0')
        self.click('profile_row:1')
        self.click('profile_cancel')
        self.assertEqual(self.app.evaluation_fields.candidates, before)
        self.click('comparison_candidate_add')
        self.search('基準')
        self.app.render()
        self.assertFalse(any(b.action.startswith('profile_row:') for b in self.app.buttons))
        self.search('候選')
        self.click('profile_row:0')
        self.click('profile_row:1')
        self.click('profile_confirm')
        self.assertEqual(set(self.app.evaluation_fields.candidates), set(before) | {first, second})
        self.click('comparison_candidate_add')
        self.click('profile_confirm')
        options = self.app.evaluation_fields.options()
        participants = options['candidates']
        self.assertEqual(len(participants), len({p.label for p in participants}))
        self.assertNotIn(base.stem, {p.label for p in participants})
        self.assertEqual({first.stem, second.stem}, {p.label for p in participants} - {p.stem for p in before})
        self.enter_comparison_field('max_plies', '0')
        self.enter_comparison_field('depth', '1')
        self.click('start')
        self.executor.finish()
        self.assertEqual(self.app.batch.snapshot()['saved_games'], 2 * len(participants))

    def test_unreadable_and_removed_profiles_do_not_replace_current_selection(self):
        folder = self.project / 'configs/evaluation'
        (folder / '損壞.json').write_text('[]', encoding='utf-8')
        removed = self.save_profile('稍後移除', EvaluationConfig.material_only())
        self.click('mode:human')
        before = self.app.live_evaluation_file
        self.click('live_evaluation')
        self.search('損壞')
        self.app.render()
        invalid = next(b for b in self.app.buttons if b.action == 'profile_row:0')
        self.assertFalse(invalid.enabled)
        self.click('profile_row:0')
        self.click('profile_cancel')
        self.assertEqual(self.app.live_evaluation_file, before)
        self.click('live_evaluation')
        self.search('稍後移除')
        self.click('profile_row:0')
        removed.unlink()
        self.click('profile_confirm')
        self.assertEqual(self.app.live_evaluation_file, before)
        self.assertIsNotNone(self.app.profile_selector)
        self.assertTrue(self.app.profile_selector.message)
        self.search('stable')
        self.click('profile_row:0')
        self.click('profile_confirm')
        self.assertIsNone(self.app.profile_selector)
        self.click('start')
        self.assertEqual(self.app.live.settings.black_evaluation, EvaluationConfig())
