"""比較用途預覽及以既有研究契約凍結多個候選。"""
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from dataclasses import asdict
from engine.sessions.evaluation_comparison import ComparisonSearchConfig
from engine.evaluation.config import EvaluationConfig
from engine.learning.candidate_inventory import validate_candidate_row
from engine.learning.comparison import load_comparison_plan, comparison_report
from engine.learning.final_comparison import freeze_final_comparison, load_final_comparison
from engine.learning.screening import create_screening, screening_report, load_screening
from engine.learning.teacher import digest
from engine.opening_book import OpeningBook
from engine.opening_lines import common_opening_lines
from engine.storage.batch_storage import write_json_atomic


def verify_selection(root, rows):
    if not rows: raise ValueError('請選擇候選')
    selected = []
    for row in rows:
        try:
            from engine.learning.config_catalog import project_root
            allowed = [Path(root).resolve()]
            if row['origin'] == 'catalog': allowed.append((project_root(root) / 'configs/evaluation').resolve())
            if not any(Path(row['path']).resolve().is_relative_to(folder) for folder in allowed):
                raise ValueError('候選不屬於目前資料範圍')
            selected.append(validate_candidate_row(row))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ValueError('候選來源已失效：' + row['path']) from exc
    if len({digest(item['stable']) for item in selected}) != 1:
        raise ValueError('候選的 stable 基準不同，無法使用共同對戰條件')
    return selected


def screening_passed(root, source):
    expected_lines = common_opening_lines(OpeningBook(), count=40)[32:]
    for entry in (Path(root) / 'data/learning-screening').glob('*/snapshot.json'):
        try:
            plan = load_screening(entry.parent)
            definition = plan['definitions']['stable']
            if digest(plan['source']) != digest(source) or plan['roles'] != ['learned'] or plan['id'] != entry.parent.name:
                continue
            learned_source = definition.get('learning_source', {})
            if (learned_source.get('source') != source or learned_source.get('baseline') != 'stable' or
                    learned_source.get('roles') != ['learned'] or learned_source.get('plan_id') != plan['id']):
                continue
            expected_search = asdict(ComparisonSearchConfig(depth_plies=3, quiescence_depth=4,
                                                          search_workers=1, transposition_capacity=4096))
            if (definition['opening_lines'] != expected_lines or definition['planned_games'] != 16 or
                definition['search'] != expected_search or definition['workers'] != 4 or
                definition['base_seed'] != 10000 or definition['repetitions'] != 1 or
                definition['claim_draw'] or definition['max_plies'] is not None or
                definition['baseline']['config'] != EvaluationConfig.from_dict(source['stable']).to_dict() or
                len(definition['candidates']) != 1 or definition['candidates'][0].get('role') != 'learned' or
                definition['candidates'][0]['config'] != EvaluationConfig.from_dict(source['config']).to_dict()):
                continue
            report = screening_report(entry.parent)
            if report['complete'] and report['eliminated'] is False:
                return True
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue
    return False


def preview_setup(root, data_root, rows, purpose):
    sources = verify_selection(data_root, rows)
    if purpose not in ('screening', 'final'): raise ValueError('比較用途不符')
    passed = [screening_passed(root, source) for source in sources] if purpose == 'final' else []
    if purpose == 'final' and (len(sources) > 5 or len({digest(s['config']) for s in sources}) != len(sources)):
        raise ValueError('完整比較需選擇一至五個不同設定')
    return dict(sources=deepcopy(sources), purpose=purpose, passed=passed,
                planned_games=len(sources) * (16 if purpose == 'screening' else 128),
                baselines=['stable'] if purpose == 'screening' else ['material', 'stable'])


def freeze_setup(root, data_root, rows, purpose):
    preview = preview_setup(root, data_root, rows, purpose)
    sources = preview['sources']
    if purpose == 'final' and not all(preview['passed']):
        raise ValueError('請先完成並通過快速篩選')
    work = []
    if purpose == 'screening':
        for source in sources:
            path = create_screening(root, source)
            work.append(dict(path=str(path), baseline='stable'))
    else:
        final_path = freeze_final_comparison(root, sources, learned_only=True)
        final = load_final_comparison(final_path)
        for entry in final['candidates']:
            work.extend(dict(path=entry['path'], baseline=baseline) for baseline in ('material', 'stable'))
    planned = sum(load_comparison_plan(item['path'])['definitions'][item['baseline']]['planned_games'] for item in work)
    if planned != preview['planned_games']: raise ValueError('凍結比較計畫與預覽局數不一致')
    path = Path(root) / 'data/learning-setup' / uuid4().hex
    path.mkdir(parents=True)
    snapshot = dict(format_version=1, purpose=purpose, sources=sources, work=work, planned_games=planned)
    snapshot['identity'] = digest(snapshot)
    write_json_atomic(path / 'snapshot.json', snapshot)
    return dict(**snapshot, path=str(path))

def load_saved_setup(path):
    path = Path(path)
    data = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    content = dict(data); identity = content.pop("identity", None)
    if data.get("format_version") != 1 or data.get("purpose") not in ("screening", "final") or digest(content) != identity:
        raise ValueError("比較紀錄身份或版本不符")
    work = data["work"]; seen = set(); planned = 0; reports = []
    expected = {(digest(source), baseline) for source in data["sources"] for baseline in (["stable"] if data["purpose"] == "screening" else ["material", "stable"])}
    if len(expected) != len(data["sources"]) * (1 if data["purpose"] == "screening" else 2): raise ValueError("比較候選重複")
    actual = set()
    root = path.parents[2]
    for item in work:
        source_path = Path(item["path"])
        if not source_path.resolve().is_relative_to((root / "data").resolve()): raise ValueError("比較計畫路徑不符")
        key = (str(source_path.resolve()), item["baseline"])
        if key in seen: raise ValueError("比較計畫重複")
        seen.add(key)
        report = comparison_report(source_path); plan = report["plan"]
        source_key = (digest(plan["source"]), item["baseline"])
        if source_key not in expected or source_key in actual or plan["roles"] != ["learned"]: raise ValueError("比較來源或用途不符")
        if data["purpose"] == "screening" and set(plan["definitions"]) != {"stable"}: raise ValueError("快速篩選基準不符")
        actual.add(source_key)
        planned += plan["definitions"][item["baseline"]]["planned_games"]
        reports.append(report["baselines"][item["baseline"]])
    if not work or actual != expected or planned != data["planned_games"]: raise ValueError("比較工作量不符")
    return data, reports

class ComparisonBundleRun:
    """以單一背景工作依序執行已凍結計畫；每份仍用既有保存契約。"""
    mode = 'evaluation'
    can_pause = False

    def __init__(self, work, planned_games, executor, *, data_root=None, rows=None, project_root=None, purpose=None, bundle_path=None):
        self._worker = _BundleExecution(work, planned_games, executor, data_root=data_root, rows=rows,
                                        project_root=project_root, purpose=purpose, bundle_path=bundle_path)
        self.future = self._worker.future

    def snapshot(self): return self._worker.snapshot()
    def stop(self): self._worker.stop()


from engine.sessions.batch_execution import BatchExecution


class _BundleExecution(BatchExecution):
    mode = 'evaluation'
    can_pause = False

    def __init__(self, work, planned_games, executor, *, data_root=None, rows=None, project_root=None, purpose=None, bundle_path=None):
        self.bundle_path = bundle_path
        self.project_root = project_root
        self.purpose = purpose
        self.data_root = data_root
        self.rows = deepcopy(rows)
        self.work = deepcopy(work)
        self.planned_games = planned_games
        super().__init__(executor, requested_games=planned_games, requested_pairs=planned_games // 2,
                         requested_workers=4, actual_workers=4, completed_pairs=0,
                         incomplete_pairs=0, saved_pairs=0, paired_score_rate=None)

    def _execute(self):
        from engine.learning.comparison import comparison_options
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        if self.bundle_path is not None:
            data, _ = load_saved_setup(self.bundle_path)
            if data["work"] != self.work or data["planned_games"] != self.planned_games:
                raise ValueError("比較紀錄已變更")
        if self.rows is not None:
            if self.purpose == 'final':
                preview = preview_setup(self.project_root, self.data_root, self.rows, 'final')
                if not all(preview['passed']): raise ValueError('請先完成並通過快速篩選')
            else:
                verify_selection(self.data_root, self.rows)
        totals = {key: 0 for key in ('saved_games', 'completed_games', 'unfinished', 'finished_games',
                                      'completed_pairs', 'incomplete_pairs', 'saved_pairs', 'finished_work')}
        last = {}
        for item in self.work:
            if not self._control(): break
            options = comparison_options(item['path'], item['baseline'])
            def progress(state):
                nonlocal last
                last = dict(state)
                merged = dict(state)
                for key, value in totals.items(): merged[key] = value + state.get(key, 0)
                merged.update(requested_games=self.planned_games, requested_pairs=self.planned_games // 2,
                              current_game=totals['finished_games'] + state.get('current_game', 0),
                              paired_score_rate=None)
                if state.get('status') == 'completed': merged['status'] = 'running'
                self._progress(merged)
            run_evaluation_comparison(**options, control=self._control, progress=progress,
                                      _bind_process_control=self._bind_process_control)
            for key in totals: totals[key] += last.get(key, 0)
            if last.get('status') == 'failed': return
            if last.get('status') == 'stopped' or not self._control(): break
        final_status = 'stopped' if not self._control() or last.get('status') == 'stopped' else 'completed'
        self._progress(dict(**totals, status=final_status, running_work=0, active_games={},
                            requested_games=self.planned_games, requested_pairs=self.planned_games // 2))
