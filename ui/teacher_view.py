"""教師先導與固定預算選擇的簡短 UI。"""
from pathlib import Path
import pygame
from engine.learning.teacher import PilotRun, choose_budget, load_pilot, default_teacher_workers, validate_workers


class TeacherView:
    def __init__(self, root=None):
        self.dataset = None
        self.workers = default_teacher_workers()
        self.project_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.default_command = str(self.project_root / 'tools/stockfish/stockfish-windows-x86-64-universal.exe')
        self.command = self.default_command
        self.focus = False
        self.draft = ''
        self.run = None
        self.state = {}
        self.path = None
        self.message = ''
        self.advanced = False
        self.index = 0
        self._loaded_run = None

    def active(self):
        return self.run is not None and not self.run.future.done()

    def entries(self):
        if not self.dataset: return []
        return sorted((self.dataset / 'teacher-pilots').glob('*/status.json'),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def open(self, dataset):
        self.dataset = Path(dataset)
        self.run, self._loaded_run = None, None
        self.state, self.path, self.message, self.index = {}, None, '', 0
        self.workers = default_teacher_workers()
        self.command = self.default_command
        entries = self.entries()
        if entries: self.load(entries[0].parent)

    def load(self, path):
        self.state = load_pilot(path)
        self.path = Path(path)
        snapshot = self.state.get('snapshot')
        if snapshot:
            self.workers = snapshot.get('workers', 1)
            command = snapshot['teacher']['command']
            self.command = command[0] if len(command) == 1 else command

    def input(self, event):
        if not self.focus or event.type not in (pygame.TEXTINPUT, pygame.KEYDOWN): return False
        if event.type == pygame.TEXTINPUT: self.draft += event.text
        elif event.key == pygame.K_BACKSPACE: self.draft = self.draft[:-1]
        elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL: self.draft = ''
        elif event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
            try:
                pygame.scrap.init()
                value = pygame.scrap.get(pygame.SCRAP_TEXT)
                if value: self.draft += value.decode('utf-8').rstrip('\x00')
            except (pygame.error, UnicodeError): self.message = '無法貼上，請輸入路徑'
        elif event.key == pygame.K_RETURN:
            try: self.commit()
            except ValueError as exc: self.message = str(exc)
        elif event.key == pygame.K_ESCAPE:
            self.focus = False
            pygame.key.stop_text_input()
        return True

    def commit(self):
        if self.focus:
            if self.focus == 'workers':
                try: workers = int(self.draft.strip())
                except ValueError: raise ValueError('同時分析局面數必須是正整數') from None
                self.workers = validate_workers(workers)
            else:
                self.command = self.draft.strip().strip('"')
            self.focus = False
            pygame.key.stop_text_input()

    def action(self, action, app):
        try:
            # 無效輸入仍能重新取得焦點修正。
            if action != 'learning_teacher_workers' or self.focus != 'workers': self.commit()
            if action == 'learning_pilot_stop' and self.active():
                self.run.stop()
                return
            if self.active(): return
            if action == 'learning_engine':
                self.focus = 'engine'
                self.draft = str(self.command)
                pygame.key.start_text_input()
            elif action == 'learning_teacher_workers':
                self.focus = 'workers'
                self.draft = str(self.workers)
                pygame.key.start_text_input()
            elif action == 'learning_engine_pick':
                self.pick_engine()
            elif action == 'learning_pilot_start':
                self.run = PilotRun(self.dataset, self.command, app.executor, workers=self.workers)
                self.index = 0
                self.message = ''
            elif action.startswith('learning_budget:'):
                choose_budget(self.path, int(action.split(':')[1]))
                self.load(self.path)
            elif action == 'learning_teacher_advanced': self.advanced = not self.advanced
            elif action in ('learning_pilot_prev', 'learning_pilot_next'):
                entries = self.entries()
                self.index = (self.index + (1 if action.endswith('next') else -1)) % len(entries)
                self.load(entries[self.index].parent)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.message = str(exc)

    def pick_engine(self):
        import tkinter
        from tkinter import filedialog
        window = None
        try:
            window = tkinter.Tk()
            window.withdraw()
            window.attributes('-topmost', True)
            current = Path(self.command) if isinstance(self.command, str) else self.project_root
            chosen = filedialog.askopenfilename(parent=window, title='選取 Stockfish 執行檔',
                initialdir=str(current.parent if current.parent.is_dir() else self.project_root),
                filetypes=[('執行檔', '*.exe'), ('所有檔案', '*')])
            if chosen:
                self.command = chosen
                self.message = ''
        except (tkinter.TclError, OSError) as exc:
            self.message = f'無法開啟檔案選擇器：{exc}'
        finally:
            if window is not None:
                window.destroy()

    def render(self, app):
        active = self.active()
        if self.run:
            if not self.run.future.done(): self.state = self.run.snapshot()
            elif self._loaded_run is not self.run:
                try:
                    self.load(self.run.path)
                    # 儲存媒體失敗時，仍顯示背景工作保存的具體原因。
                    runtime = self.run.snapshot()
                    if runtime.get('status') == 'failed':
                        self.state.update(runtime)
                    self._loaded_run = self.run
                except (OSError, ValueError) as exc:
                    self.state = self.run.snapshot()
                    self.message = str(exc)
        state = self.state
        app.text('學習實驗 · 教師先導', 50, 78, large=True)
        app.button('learning_data', '資料', (50, 122, 130, 34), enabled=not active)
        app.button('learning_labels', '教師標記', (195, 122, 190, 34), enabled=bool(state.get('choice')) and not active)
        app.button('learning_engine', self.draft + ' |' if self.focus == 'engine' else str(self.command or '輸入／貼上 Stockfish 19 執行檔路徑'),
                   (50, 174, 630, 38), enabled=not active)
        app.button('learning_engine_pick', '選取檔案', (695, 174, 145, 38), enabled=not active)
        app.button('learning_pilot_start', '建立新先導', (50, 230, 235, 36), enabled=not active, primary=True)
        app.button('learning_pilot_stop', '停止', (310, 230, 130, 36), enabled=active)
        workers = self.draft + ' |' if self.focus == 'workers' else str(self.workers)
        app.button('learning_teacher_workers', f'同時分析局面數：{workers}', (455, 230, 385, 36), enabled=not active)
        status = {'queued': '排隊', 'running': '量測中', 'completed': '量測完成', 'stopped': '已停止', 'failed': '失敗',
                  'interrupted': '未完成，請建立新先導'}
        if state:
            display_status = 'interrupted' if state['status'] in ('running', 'queued') and not active else state['status']
            app.text(f'{status.get(display_status, "未完成")} · {state.get("completed", 0)}/{state.get("total", 0)}'
                     f' · {state.get("elapsed_seconds", 0):.1f} 秒', 50, 285, width=790)
        if self.message or state.get('error'):
            app.text(self.message or state['error'], 50, 321, width=790)
        summary = state.get('summary')
        if summary:
            for index, nodes in enumerate((50000, 200000)):
                group = summary['budgets'][str(nodes)]
                app.text(f'{nodes:,} 節點：{group["elapsed_seconds"]:.2f} 秒 · 已完成 {group["completed"]} · 將篩除 {group["excluded"]}',
                         50, 365 + index * 32, width=790)
            difference = summary['mean_absolute_difference_cp']
            text = f'{difference:.2f} cp' if difference is not None else '無有效配對'
            app.text(f'可比較 {summary["compared"]} · 無法比較 {summary["not_comparable"]} · 平均絕對差 {text}', 50, 439, width=790)
        choice = state.get('choice')
        if choice: app.text(f'已固定：{choice["nodes"]:,} 節點', 50, 485)
        else:
            for index, nodes in enumerate((50000, 200000)):
                app.button(f'learning_budget:{nodes}', f'選定 {nodes:,} 節點', (50 + index * 270, 480, 245, 36),
                           enabled=state.get('status') == 'completed' and not active)
        app.button('learning_teacher_advanced', '收起進階條件' if self.advanced else '進階條件', (50, 535, 230, 34))
        snapshot = state.get('snapshot')
        if self.advanced and snapshot:
            teacher = snapshot['teacher']
            app.text(f'{teacher["identification"]["name"]} · SHA256 {teacher["executable_sha256"][:16]}… · GPL-3.0', 50, 580, width=790)
            app.text(f'Threads {teacher["options"]["Threads"]} · Hash {teacher["options"]["Hash"]} MB · 每局面重設 · 無殘局庫', 50, 612, muted=True, width=790)
            app.text(f'訓練來源 {snapshot["sample_count"]}/100 局面 · 節點數不保證品質', 50, 644, muted=True, width=790)
            last = state.get('last_score')
            if last:
                score = f'白方 {last["white_cp"]} cp' if last['kind'] == 'cp' else '將死分數'
                app.text(f'最近採用評分：{score} · 深度 {last["depth"]} · 實際 {last["actual_nodes"]:,} 節點',
                         50, 671, muted=True, width=790)
        elif self.advanced:
            app.text('Stockfish 19 · GPL-3.0 · stockfishchess.org/download', 50, 580, width=790)
            app.text('訓練來源最多 100 局面 · 先導最多八小時', 50, 612, muted=True, width=790)
        entries = self.entries()
        app.text(f'已保存先導 {min(self.index + 1, len(entries))}/{len(entries)}', 50, 700)
        app.button('learning_pilot_prev', '上一份', (455, 690, 160, 34), enabled=len(entries) > 1 and not active)
        app.button('learning_pilot_next', '下一份', (640, 690, 160, 34), enabled=len(entries) > 1 and not active)
