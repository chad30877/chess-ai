"""搬移時維持研究結果、身分引用及部分完成比較的續跑契約。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from engine.learning.teacher import digest
from engine.sessions.experiment import stable_id, work_id
from scripts.relocate_project_data import Relocation, read_documents


class RelocationGraphTest(unittest.TestCase):
    def test_nested_seals_legacy_whole_object_digest_and_dictionary_keys(self):
        source, destination = r'C:\old\project', r'C:\new\project'
        label = dict(dataset_path=source + r'\data\one', teacher={'command': [source + r'\tools\teacher.exe']})
        label['identity'] = digest(label)
        inputs = dict(label_snapshot=label, positions=[])
        snapshot = dict(inputs_sha256=digest(inputs), label_identity=label['identity'])
        snapshot['identity'] = digest(snapshot)
        frozen = dict(snapshot_identity=snapshot['identity'], config={'weight': 2.5})
        report = dict(frozen_identity=digest(frozen), mae=1.25)
        record = dict(snapshot_identity=label['identity'], sample_id='position',
                      work_id=digest([label['identity'], 'position']), label={'white_cp': 37})
        original = dict(inputs=inputs, snapshot=snapshot, frozen=frozen, report=report, record=record,
                        names={source + r'\data\one': '保留名稱'}, unrelated=source + '-other')
        kept = deepcopy(original)
        result = Relocation(original, source, destination).plan()
        self.assertEqual(original, kept)
        self.assertEqual(result['snapshot']['inputs_sha256'], digest(result['inputs']))
        new_label = result['inputs']['label_snapshot']
        self.assertEqual(result['record']['work_id'], digest([new_label['identity'], 'position']))
        self.assertEqual(result['record']['label'], record['label'])
        self.assertEqual(result['report']['frozen_identity'], digest(result['frozen']))
        self.assertEqual(result['frozen']['config'], frozen['config'])
        self.assertEqual(result['names'], {destination + r'\data\one': '保留名稱'})
        self.assertEqual(result['unrelated'], original['unrelated'])
        self.assertEqual(Relocation(result, source, destination).plan(), result)

    def test_corrupt_source_seal_is_rejected_without_modifying_input(self):
        snapshot = dict(path='C:/old/data', value=1)
        snapshot['identity'] = digest(snapshot)
        snapshot['value'] = 2
        kept = deepcopy(snapshot)
        with self.assertRaisesRegex(ValueError, '原始內容身分不符'):
            Relocation({'snapshot': snapshot}, 'C:/old', 'C:/new')
        self.assertEqual(snapshot, kept)

    def test_dictionary_key_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '索引衝突'):
            Relocation({'names': {'C:/old/file': '甲', 'C:/new/file': '乙'}},
                       'C:/old', 'C:/new').plan()


class RelocationFlowTest(unittest.TestCase):
    def test_move_completed_learning_and_resume_partial_comparison_with_source_unavailable(self):
        from tests.test_weight_training import TrainingFlowTest
        from engine.learning.group_training import create_group_training, run_group_training, load_group_candidate
        from engine.learning.training import create_training, run_training, load_training
        from engine.learning.labeling import load_labeling
        from engine.learning.comparison import create_comparison, comparison_options, comparison_report, load_comparison_plan
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        TrainingFlowTest.setUp(self)
        groups = create_group_training(self.labels, ['pawn'])
        run_group_training(groups)
        candidate = load_group_candidate(groups, 'pawn')
        legacy = create_training(self.labels)
        run_training(legacy)
        before_legacy = load_training(legacy)
        lines = [dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1', moves_uci=[], name='短局', source={})]
        plan = create_comparison(self.root, candidate, roles=('learned',), opening_lines=lines, max_plies=1)
        states = []
        batch = run_evaluation_comparison(**comparison_options(plan, 'material'), progress=states.append,
                                         control=lambda: not states or states[-1]['saved_games'] < 1)
        before_report = comparison_report(plan)['baselines']['material']['candidates']
        documents = read_documents(self.root)
        with tempfile.TemporaryDirectory() as target:
            destination = Path(target) / 'moved'
            shutil.copytree(self.root, destination)
            transformed = Relocation(documents, self.root, destination).plan()
            for filename, content in transformed.items():
                (destination / filename).write_text(json.dumps(content, ensure_ascii=False), encoding='utf-8')
            hidden = self.root.with_name(self.root.name + '-unavailable')
            self.root.rename(hidden)
            try:
                new_labels = destination / self.labels.relative_to(self.root)
                self.assertTrue(load_labeling(new_labels)['ready'])
                new_group = destination / groups.relative_to(self.root)
                self.assertEqual(load_group_candidate(new_group, 'pawn')['config'], candidate['config'])
                new_legacy = load_training(destination / legacy.relative_to(self.root))
                self.assertEqual(new_legacy['report']['test'], before_legacy['report']['test'])
                new_plan = destination / plan.relative_to(self.root)
                after_report = comparison_report(new_plan)['baselines']['material']['candidates']
                self.assertEqual([r['pending_games'] for r in after_report], [r['pending_games'] for r in before_report])
                definition = load_comparison_plan(new_plan)['definitions']['material']
                moved_candidate = definition['candidates'][0]
                self.assertEqual(moved_candidate['id'], stable_id(dict(
                    source=digest(definition['learning_source']['source']),
                    role=moved_candidate['role'], config=moved_candidate['config'])))
                new_batch = destination / batch.path.relative_to(self.root)
                saved = {p.name: p.read_bytes() for p in (new_batch / 'replays').glob('*.json')}
                for content in saved.values():
                    execution = json.loads(content)['metadata']['execution']
                    self.assertIn(execution['work_id'], {work_id(definition, 0, 1, white) for white in (False, True)})
                run_evaluation_comparison(**comparison_options(new_plan, 'material'))
                self.assertTrue(all((new_batch / 'replays' / name).read_bytes() == value for name, value in saved.items()))
                final = comparison_report(new_plan)['baselines']['material']['candidates']
                self.assertEqual(final[0]['pending_games'], 0)
            finally:
                hidden.rename(self.root)


if __name__ == '__main__':
    unittest.main()
