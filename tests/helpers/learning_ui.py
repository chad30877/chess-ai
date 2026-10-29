"""由實際選擇器事件開啟指定教師評分，支援受控及真實執行器。"""
import pygame


def settle(app, future):
    if future is None: return
    if hasattr(app.executor, 'finish'):
        if not future.done(): app.executor.finish(next(i for i, job in enumerate(app.executor.jobs) if job[0] is future))
    else: future.result(timeout=30)
    app.render()


def choose_labels(app, path, *, training=False):
    app.learning.root = path.parents[2]
    app.dispatch('learning_choose_training_labels' if training else 'learning_teacher_select_labels')
    settle(app, app.learning.page_loading)
    index = next(i for i, entry in enumerate(app.learning.label_choices.entries) if entry['path'] == path)
    app.learning.label_choices.page = index // 8
    app.render()
    button = next(b for b in app.buttons if b.action == f'learning_label_choice:{index}')
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1))
    settle(app, app.learning.page_loading)
    settle(app, app.learning.labels.loading)
