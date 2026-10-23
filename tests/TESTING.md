# 測試說明

從專案根目錄執行：

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| 檔案 | 測試內容 |
| --- | --- |
| `rules/test_game_rules.py` | 共用棋規、特殊走法、重複歷史與終局 |
| `evaluation/test_evaluation_config.py`、`test_evaluator_semantics.py` | 設定驗證、舊版本讀取、保存、總分與白方視角 |
| `evaluation/test_numeric_evaluation.py`、`search/test_numeric_search.py` | 全項／混合／零權重與特殊走法的舊版數值、分項一致性、單／多程序搜尋選步及原棋盤歷史 |
| `evaluation/test_piece_square_tables.py`、`test_tapered_evaluation.py` | 棋子位置表、鏡射與中殘局混合 |
| `evaluation/test_pawn_structure.py`、`test_mobility.py`、`test_king_safety.py`、`test_coordination.py` | 兵形、活動力、國王安全與棋子協調評分 |
| `search/test_alphabeta_searcher.py`、`test_alphabeta_player.py`、`test_search_types.py` | Minimax 比對、搜尋契約、玩家與參數 |
| `search/test_greedy_terminal_scoring.py` | Greedy 與 Alpha-Beta 共用終局計分 |
| `search/test_iterative_deepening.py`、`test_move_ordering.py`、`test_quiescence.py`、`test_pvs.py`、`test_aspiration.py` | 迭代加深、排序、延伸、窄窗重搜及取消／逾時 |
| `search/test_transposition.py` | 容量與替換、易位／吃過路兵、歷史／將死鍵值與搜尋隔離 |
| `search/test_parallel_search.py` | 真實 spawn 搜尋、將死／歷史、取消、故障與程序清理 |
| `self_play/test_batch_generation.py`、`test_batch_ui_storage.py` | 批次格式、保存失敗、流水號與日期分類 |
| `self_play/test_batch_execution.py`、`test_parallel_batch.py` | 共用派工、逐局發布、暫停／停止與失敗清理 |
| `self_play/test_alphabeta_batch.py` | 一般 Alpha-Beta 批次、兩層真實 spawn、超額派工、保存失敗與後代清理 |
| `self_play/test_evaluation_comparison.py`、`test_alphabeta_comparison.py`、`test_comparison_run.py` | 共同條件、交換黑白、多候選、逐場保存、停止與舊紀錄 |
| `self_play/test_engine_match.py`、`test_cli_roundtrip.py` | 對戰 CLI、生成／匯出／回放往返 |
| `replay/test_replay_session.py`、`test_records_catalog.py`、`test_comparison_catalog.py` | 回放跳步、日期查找與比較摘要 |
| `ui/test_live_session.py` | 背景落子、真人回合、停止及舊結果隔離 |
| `ui/test_chess_application.py` | UI 事件、搜尋設定生效、保存、回放、縮放，以及九候選排序另存與半組配對 |
| `test_discovery.py`、`test_engine_imports.py` | 測試發現及獨立程序載入 |
| `helpers/executors.py` | 供流程測試手動完成背景工作 |

UI 測試使用 dummy 顯示驅動。含程序觀測的測試與獨立效能工具使用選用套件 `psutil`；效能量測見[搜尋與評分](../docs/搜尋與評分.md)，不在例行測試斷言深度 5 秒數。
`self_play/test_experiment_flow.py`：從權重預覽到真實逐局保存，核對不可變設定、工作識別、失效預覽與非法候選阻擋。
權重實驗另驗證九組候選全數保存、百分比等價、零基準、範圍邊界及展開前數量限制。
