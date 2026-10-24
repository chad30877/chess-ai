"""學習實驗的資料來源、背景處理與保存預覽。"""

import json
from pathlib import Path

import pygame

from engine.learning.dataset import DatasetRun, SOURCE_URL, load_dataset
from ui.teacher_view import TeacherView
from ui.label_view import LabelView
from ui.training_view import TrainingView
from ui.group_training_view import GroupTrainingView
from ui.combination_view import CombinationView

SPLIT_LABELS = {'train': '訓練', 'validation': '驗證', 'test': '測試'}
STAGE_LABELS = {'opening': '開局', 'middlegame': '中局', 'endgame': '殘局'}
EXCLUSION_LABELS = {'first_8_plies': '前八手', 'terminal': '終局', 'in_check': '受將',
                    'not_sampled': '抽樣上限', 'cross_split_duplicate': '跨組重複',
                    'within_split_duplicate': '同組重複'}


class LearningView:
    def __init__(self, root):
        self.root = Path(root) / 'data/learning'
        self.source = 'lichess'
        self.local_path = ''
        self.seed = '2026'
        self.focus = None
        self.draft = ''
        self.run = None
        self._loaded_run = None
        self.data = None
        self.path = None
        self.message = ''
        self.sample_index = 0
        self.recent_page = 0
        self.page = 'data'
        self.teacher = TeacherView()
        self.labels = LabelView()
        self.training = TrainingView(root)
        self.group_training = GroupTrainingView(root)
        self.combination = CombinationView(root)

    def active(self):
        return (self.run is not None and not self.run.future.done()) or self.teacher.active() or self.labels.active() or self.training.active() or self.group_training.active() or self.combination.active()

    def close(self, wait=False):
        for run in (self.run, self.teacher.run, self.labels.run, self.training.run, self.group_training.run, self.combination.run):
            if run and not run.future.done():
                run.stop()
                if wait:
                    run.future.result()

    def commit(self):
        if self.focus == 'path':
            self.local_path = self.draft.strip().strip('"')
        elif self.focus == 'seed':
            try:
                int(self.draft)
            except ValueError:
                self.message = '種子須為整數'
                return False
            self.seed = self.draft
        self.focus = None
        pygame.key.stop_text_input()
        return True

    def input(self, event):
        if self.page == 'teacher':
            return self.teacher.input(event)
        if self.focus is None or event.type not in (pygame.TEXTINPUT, pygame.KEYDOWN):
            return False
        if event.type == pygame.TEXTINPUT:
            self.draft += event.text
        elif event.key == pygame.K_BACKSPACE:
            self.draft = self.draft[:-1]
        elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
            self.draft = ''
        elif event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
            try:
                pygame.scrap.init()
                clipboard = pygame.scrap.get(pygame.SCRAP_TEXT)
                if clipboard:
                    self.draft += clipboard.decode('utf-8').rstrip('\x00')
            except (pygame.error, UnicodeError):
                self.message = '無法貼上，請輸入路徑'
        elif event.key == pygame.K_RETURN:
            self.commit()
        elif event.key == pygame.K_ESCAPE:
            self.focus = None
            pygame.key.stop_text_input()
        return True

    def entries(self):
        return sorted(self.root.glob('*/status.json'), key=lambda p: p.stat().st_mtime, reverse=True)

    def open(self, path):
        self.data = load_dataset(path)
        self.path = Path(path)
        self.sample_index = 0
        self.message = ''
        self.teacher.open(path)

    def action(self, action, app):
        if action == 'learning_combinations' and not self.active() and self.group_training.path:
            try:
                self.combination.open(self.group_training.path)
                self.page = 'combination'
            except (OSError,ValueError,KeyError) as exc: self.group_training.message = str(exc)
            return
        if action == 'learning_groups' and not self.active() and self.labels.path:
            try:
                self.group_training.open(self.labels.path)
                self.page = 'groups'
            except (OSError,ValueError,KeyError) as exc: self.labels.message = str(exc)
            return
        if action == 'learning_training' and not self.active() and self.labels.path:
            try:
                self.training.open(self.labels.path)
                self.page = 'training'
            except (OSError, ValueError, KeyError) as exc:
                self.labels.message = str(exc)
            return
        if action == 'learning_data' and not self.active():
            self.teacher.commit()
            self.page = 'data'
            return
        if action == 'learning_labels' and not self.active() and self.teacher.path:
            try:
                self.labels.open(self.path, self.teacher.path)
                self.page = 'labeling'
            except (OSError, ValueError, KeyError) as exc:
                self.teacher.message = str(exc)
            return
        if action == 'learning_teacher' and self.page == 'labeling' and not self.active():
            self.page = 'teacher'
            return
        if self.page == 'combination':
            self.combination.action(action,app)
            return
        if self.page == 'groups':
            self.group_training.action(action,app)
            return
        if self.page == 'training':
            self.training.action(action, app)
            return
        if self.page == 'labeling':
            self.labels.action(action, app)
            return
        if self.page == 'teacher':
            self.teacher.action(action, app)
            return
        if not self.commit():
            return
        try:
            if action == 'learning_stop' and self.active():
                self.run.stop()
                return
            if self.active():
                return
            if action == 'learning_source':
                self.source = 'local' if self.source == 'lichess' else 'lichess'
            elif action.startswith('learning_field:'):
                self.focus = action.split(':')[1]
                self.draft = self.local_path if self.focus == 'path' else self.seed
                pygame.key.start_text_input()
            elif action == 'learning_create':
                source = SOURCE_URL if self.source == 'lichess' else self.local_path
                if not source:
                    raise ValueError('請輸入本機 PGN 路徑')
                self.run = DatasetRun(self.root, source, int(self.seed), app.executor)
                self.data = None
                self.message = ''
            elif action == 'learning_teacher' and self.path:
                self.page = 'teacher'
            elif action.startswith('learning_open:'):
                path = self.entries()[int(action.split(':')[1])].parent
                if (path / 'dataset.json').exists():
                    self.open(path)
                else:
                    saved = json.loads((path / 'status.json').read_text(encoding='utf-8'))
                    self.data = None
                    self.run = None
                    self.message = saved.get('error', '資料尚未完成；請建立新實驗重試')
            elif action in ('learning_prev', 'learning_next') and self.data:
                self.sample_index = (self.sample_index + (1 if action.endswith('next') else -1)) % max(1, len(self.data['positions']))
            elif action in ('learning_recent_prev', 'learning_recent_next'):
                self.recent_page = max(0, self.recent_page + (1 if action.endswith('next') else -1))
            elif action == 'learning_sample' and self.data and self.data['positions']:
                sample = self.data['positions'][self.sample_index]
                app._set_replay(dict(initial_fen=sample['initial_fen'], moves_uci=sample['moves_uci'],
                                     result='*', metadata={'name': '學習局面', 'game_id': sample['game_id']}), '學習資料預覽')
                app.replay.goto_ply(len(sample['moves_uci']))
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            self.message = f'無法開啟資料：{exc}'

    def render(self, app):
        if self.page == 'combination':
            self.combination.render(app)
            return
        if self.page == 'groups':
            self.group_training.render(app)
            return
        if self.page == 'training':
            self.training.render(app)
            return
        if self.page == 'labeling':
            self.labels.render(app)
            return
        if self.page == 'teacher':
            self.teacher.render(app)
            return
        active = self.active()
        app.text('學習實驗 · 資料準備', 50, 78, large=True)
        app.button('learning_teacher', '教師先導', (650, 74, 190, 36), enabled=self.data is not None and not active)
        app.button('learning_source', 'Lichess 2013-01 · CC0' if self.source == 'lichess' else '本機棋譜（授權自查）',
                   (50, 125, 470, 36), enabled=not active)
        if self.source == 'local':
            value = self.draft + ' |' if self.focus == 'path' else self.local_path or '輸入／貼上 .pgn、.zst、.gz、.bz2 路徑'
            app.button('learning_field:path', value, (50, 172, 790, 36), enabled=not active)
        else:
            app.text('database.lichess.org · 下載壓縮來源後串流抽樣', 50, 178, muted=True, width=790)
        app.button('learning_field:seed', '種子：' + (self.draft + ' |' if self.focus == 'seed' else self.seed),
                   (50, 220, 270, 36), enabled=not active)
        app.button('learning_create', '建立新實驗', (340, 220, 220, 36), enabled=not active, primary=True)
        app.button('learning_stop', '停止', (580, 220, 110, 36), enabled=active)
        state = self.run.snapshot() if self.run else {}
        if state.get('status') == 'completed' and self._loaded_run is not self.run:
            try:
                self.open(self.run.path)
                self._loaded_run = self.run
            except (OSError, ValueError, KeyError) as exc:
                self.message = str(exc)
        stages = {'acquiring': '取得來源', 'reading': '串流讀取棋譜', 'sampling': '抽樣及排除重複', 'completed': '資料已保存'}
        statuses = {'queued': '排隊', 'running': '處理中', 'completed': '完成', 'stopped': '已停止', 'failed': '失敗'}
        if state:
            app.text(f'{statuses.get(state["status"], state["status"])} · {stages.get(state["stage"], state["stage"])}'
                     f' · {state.get("bytes", 0) / 1048576:.1f} MB · {state.get("source_games", 0)} 盤 · {state.get("elapsed_seconds", 0):.1f} 秒', 50, 276, width=790)
        if self.message or state.get('error'):
            app.text(self.message or state['error'], 50, 310, width=790)
        if self.data:
            data = self.data
            summary = data['summary']
            app.text(f'{summary["selected_games"]}/500 盤 · {summary["positions"]}/6000 局面 · 來源不足 {summary["shortfall_games"]} 盤 · 重複棋譜 {summary["duplicate_games"]}', 50, 310, width=790)
            for index, (split, title) in enumerate(SPLIT_LABELS.items()):
                group = summary['splits'][split]
                phases = ' / '.join(f'{label} {group["stages"].get(stage, 0)}' for stage, label in STAGE_LABELS.items())
                app.text(f'{title}：{group["games"]} 盤 / {group["positions"]} 局面　{phases}', 50, 348 + index * 30, width=790)
            excluded = summary['excluded']
            for row, keys in enumerate((('first_8_plies', 'terminal', 'in_check'), ('not_sampled', 'cross_split_duplicate', 'within_split_duplicate'))):
                app.text(' · '.join(f'{EXCLUSION_LABELS[k]} {excluded.get(k, 0)}' for k in keys), 50, 445 + row * 27, muted=True, width=790)
            source = data['source']
            app.text(f'{source["license"]} · 種子 {data["seed"]} · 處理 v{data["processing_version"]} · SHA256 {source["sha256"][:16]}…', 50, 505, muted=True, width=790)
            if data['positions']:
                sample = data['positions'][self.sample_index]
                app.text(f'局面 {self.sample_index + 1}/{len(data["positions"])} · {SPLIT_LABELS[sample["split"]]} · {STAGE_LABELS[sample["stage"]]} · 第 {sample["ply"]} 手', 50, 537, width=790)
                app.button('learning_prev', '上一局面', (50, 573, 170, 34))
                app.button('learning_next', '下一局面', (235, 573, 170, 34))
                app.button('learning_sample', '棋盤與完整歷史', (420, 573, 270, 34))
        entries = self.entries()
        pages = max(1, (len(entries) + 2) // 3)
        self.recent_page = min(self.recent_page, pages - 1)
        app.text(f'已保存實驗 {self.recent_page + 1}/{pages}', 50, 620)
        app.button('learning_recent_prev', '上頁', (570, 617, 120, 32), enabled=self.recent_page > 0 and not active)
        app.button('learning_recent_next', '下頁', (705, 617, 120, 32), enabled=self.recent_page < pages - 1 and not active)
        for row, entry in enumerate(entries[self.recent_page * 3:self.recent_page * 3 + 3]):
            try:
                saved = json.loads(entry.read_text(encoding='utf-8'))
                status = 'completed' if (entry.parent / 'dataset.json').exists() else saved['status']
                label = statuses.get(status, '未完成')
                if status in ('running', 'queued'):
                    label = '未完成，請重建'
                label = f'{entry.parent.name[:12]} · {label} · 種子 {saved["seed"]}'
            except (OSError, ValueError, KeyError):
                label, status = '紀錄損壞', 'failed'
            app.button(f'learning_open:{self.recent_page * 3 + row}', label,
                       (50, 658 + row * 30, 775, 28), enabled=not active)
