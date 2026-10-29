"""同頁呈現教師條件、估時與標記進度。"""
from ui.teacher_view import _duration


def render_teacher(learning, app):
    teacher, labels = learning.teacher, learning.labels
    teacher.refresh()
    labels.refresh(app)
    state = teacher.state
    busy = teacher.active()
    app.text('教師評分', 50, 78, large=True)
    app.button('learning_teacher_select_labels', '選擇教師評分', (360, 74, 230, 36))
    app.button('learning_teacher_rename_labels', learning.rename_draft + ' |' if learning.rename_focus else '重新命名', (605, 74, 235, 36), enabled=labels.path is not None)
    app.button('learning_engine', teacher.draft + ' |' if teacher.focus == 'engine' else str(teacher.command), (50, 130, 620, 34), enabled=not busy)
    app.button('learning_engine_pick', '選取引擎', (685, 130, 155, 34), enabled=not busy)
    app.button('learning_teacher_workers', '同時分析：' + (teacher.draft if teacher.focus == 'workers' else str(teacher.workers)), (50, 177, 230, 34), enabled=not busy)
    app.button('learning_pilot_start', '量測預計時間', (295, 177, 230, 34), enabled=not busy and teacher.dataset is not None, primary=True)
    app.button('learning_pilot_stop', '停止量測', (540, 177, 145, 34), enabled=busy)
    choice = state.get('choice')
    for index, nodes in enumerate((50000, 200000)):
        estimate = state.get('labeling_estimates', {}).get(str(nodes), {}).get('seconds')
        text = f'{nodes:,} 節點' + (' · 約 ' + _duration(estimate) if estimate is not None else '')
        if choice and choice['nodes'] == nodes: text = '[x] ' + text
        app.button(f'learning_budget:{nodes}', text, (50 + index * 405, 224, 385, 34), enabled=state.get('status') == 'completed' and not busy and not choice)
    message = teacher.message or state.get('error')
    if busy: message = f'估時中 {state.get("completed", 0)}/{state.get("total", 0)}'
    elif state.get('status') in ('stopped', 'interrupted'): message = '量測未完成，請重新量測' + (' · ' + message if message else '')
    elif not teacher.dataset:
        app.button('learning_need_data', '選擇資料', (700, 177, 140, 34))
    if message: app.text(message, 50, 269, width=790)
    app.text(learning.saved_name(labels.path, '教師評分') if labels.path else '尚未建立教師評分', 50, 314, width=790)
    active = labels.active()
    ready = labels.state.get('ready', False)
    available = bool(choice) and not busy and not active and labels.loading is None and teacher.loading is None
    app.button('learning_labels_new', '使用既有／開始評分', (50, 355, 260, 36), enabled=available, primary=True)
    app.button('learning_labels_resume', '續跑', (325, 355, 120, 36), enabled=bool(labels.path) and not ready and not active and labels.loading is None)
    app.button('learning_labels_recreate', '重新評分', (460, 355, 200, 36), enabled=available)
    app.button('learning_labels_stop', '停止', (675, 355, 165, 36), enabled=active)
    status = labels.state
    if status:
        titles = {'ready':'待開始', 'running':'評分中', 'queued':'排隊', 'completed':'完成', 'stopped':'已停止', 'failed':'失敗', 'interrupted':'待續跑'}
        app.text(f'{titles.get(status.get("status"), "待續跑")} · {status.get("completed", 0)}/{status.get("total", 0)} 局面', 50, 407, width=790)
    if labels.loading: app.text('載入教師評分…', 50, 445)
    elif labels.message or status.get('error'): app.text(labels.message or status['error'], 50, 445, width=790)
    if labels.load_error and labels.path: app.button('learning_labels_retry', '重新讀取', (650, 440, 190, 34))
    summary = status.get('summary')
    if summary:
        app.text(f'有效 {summary["valid"]} · 排除 {summary["excluded"]}', 50, 484, width=790)
        for i, (key, title) in enumerate((('train','訓練'), ('validation','驗證'), ('test','測試'))):
            row = summary['splits'][key]
            app.text(f'{title}：{row["games"]} 盤 / {row["positions"]} 局面', 50, 520 + i * 30, width=790)
    app.button('learning_choose_training_labels', '選擇評分開始學習', (50, 650, 320, 36))
    app.button('learning_saved_list', '量測紀錄', (540, 650, 300, 36))
