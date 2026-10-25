# 測試說明

從專案根目錄執行：

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

| 檔案 | 測試內容 |
| --- | --- |
| `ui/test_profile_selector.py` | 共用設定選擇小視窗的名稱／群組查找、捲動、取消、各入口實際套用、多候選比較及損壞檔案恢復 |
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
| `self_play/test_batch_execution.py`、`test_parallel_batch.py` | 共用派工、單／多程序在保存前逐手回報、換局歸零、暫停／停止、每對第二色失敗仍保留第一色與程序清理 |
| `self_play/test_alphabeta_batch.py` | 一般 Alpha-Beta 批次、兩層真實 spawn、超額派工、保存失敗與後代清理 |
| `self_play/test_evaluation_comparison.py`、`test_alphabeta_comparison.py`、`test_comparison_run.py` | 共同條件、交換黑白、多候選、逐場保存、停止與舊紀錄 |
| `self_play/test_engine_match.py`、`test_cli_roundtrip.py` | 對戰 CLI、生成／匯出／回放往返 |
| `replay/test_replay_session.py`、`test_records_catalog.py`、`test_comparison_catalog.py` | 回放跳步、日期查找與比較摘要 |
| `ui/test_last_move.py` | 真人落子、回放前後跳步、易位／吃過路兵變動格、無歷史、翻轉與縮放後的棋格標示 |
| `ui/test_live_opening_state.py` | 真人庫內選步、離庫等待及搜尋、非開局策略、停止與失敗，以及批次兩步保存 |
| `ui/test_live_session.py` | 背景落子、真人回合、停止及舊結果隔離 |
| `ui/test_chess_application.py` | UI 事件、搜尋設定生效、保存、回放、縮放、進行中棋局手數與分頁，以及九候選排序另存與半組配對 |
| `test_learning_dataset.py` | 串流來源、固定抽樣與整盤分組、同組／跨組去重、合法吃過路兵身份、歷史保存、損壞／停止／保存失敗與重開 |
| `ui/test_teacher_picker.py` | 不同專案預設路徑、原生選檔回傳與取消、中文空白路徑外部教師、無效檔案恢復及保存重開 |
| `test_teacher_pilot.py`、`ui/test_teacher_pilot.py` | 教師完整歷史與白方視角、先導保存選擇重開、同手完整評分與界限、版本／異常／逾時／非法手、停止、八小時上限及保存失敗；UCI 使用外部可控制程序 |
| `test_teacher_parallel.py` | 外部教師重疊上限、亂序歷史、分預算整批量測、少量工作、凍結條件、舊資料身分、停止／失敗／期限及程序清理 |
| `test_teacher_labeling.py`、`ui/test_teacher_labeling.py` | 全分組凍結標記、相容先導重用、篩選分布、正式學習閘門、共用八小時與停止、崩潰／保存失敗重試、摘要恢復、獨占執行及 UI 關閉重開續跑；只替換外部 UCI 程序 |
| `test_discovery.py`、`test_engine_imports.py` | 測試發現及獨立程序載入 |
| `test_ticket_completion.py` | 未驗收就關票、漏關票、GitHub／本機驗收不同步與發布索引定位 |
| `test_complete_ticket.py` | 驗收完成才同步關票、讀回失敗中止、需求變更拒絕覆寫，以及重試不重複更新 |
| `helpers/executors.py` | 供流程測試手動完成背景工作 |

UI 測試使用 dummy 顯示驅動。含程序觀測的測試與獨立效能工具使用選用套件 `psutil`；效能量測見[搜尋與評分](../docs/搜尋與評分.md)，不在例行測試斷言深度 5 秒數。
教師 UI 測試另涵蓋低 CPU 預設、workers 輸入、先導部分停止重開、凍結程序數，以及標記執行中關閉後續跑。真實 Stockfish 2 程序短流程見 [R02 驗收](../.scratch/research-usability/issues/02-parallel-teachers.md)。
學習資料測試使用 `zstandard` 與小型本機棋譜；UI 事件另驗證建立、停止、修改種子另建、關閉重開與完整歷史回放，不下載整月資料。
資料建立另驗證 Windows 暫時讀鎖解除後可原子提交、持續拒絕仍失敗；外部真實 60 盤／Stockfish／組合與深度三 UI 驗收證據見 [M11](../.scratch/ml-small-trial/issues/11-offline-guide-acceptance.md)，不在日常測試跑正式研究。離線教材以資源檢查及實際渲染驗收，不為文案或圖數新增測試。
`self_play/test_experiment_flow.py`：從權重預覽到真實逐局保存，核對不可變設定、工作識別、失效預覽與非法候選阻擋。
權重實驗另驗證九組候選全數保存、百分比等價、零基準、範圍邊界及展開前數量限制。

`self_play/test_experiment_resume.py`：停止後續跑、半組配對、進度落後恢復、新程序重開與獨占執行。
比較實驗回歸另涵蓋中斷嘗試續跑後的結果表、回放與另存、相近權重不混淆，以及第八份以後設定檔的分頁操作。

開局庫：`test_live_session` 驗證種子、上限與真人偏離後不回庫；`test_batch_ui_storage` 驗證一般批次序列在單程序及 spawn 一致並可保存；`test_chess_application` 驗證 UI 設定傳遞及載入錯誤顯示。

單群組設定：`ui/test_chess_application.py` 透過 UI 事件驗證六組隔離、實際評分、回放另存及真人／比較載入。

共同開局線：`self_play/test_common_openings.py` 驗證固定 32 線、合法前綴去重與不足來源、跨候選交換黑白、三次重複、易位／吃過路兵、保存／續跑與兩層真實 spawn 歷史及停止清理。`ui/test_chess_application.py` 另以 UI 事件選兩份既有設定、預覽、短比較、停止、重開續跑及回放。

`test_weight_training.py`：以手算資料驗證逐盤校準、空分層、正式特徵一致、非負下界、零初始權重與無百分比硬上限；真實求解及保存覆蓋驗證挑選、測試凍結、取消 worker、八小時到時、重開續跑與沿用測試來源。`ui/test_weight_training.py` 以 UI 事件完成學習、重開、另存及載入真人對戰。

`test_group_training.py`：五組共用校準與整次期限、32 欄正式評分一致、零初始權重、群組隔離、部分保存失敗重試與已提交結果不重算。`ui/test_group_training.py` 以 UI 事件完成兩組後停止、重開續跑其餘組，查看階段與權重，另存並載入真人對戰。

`test_learned_comparison.py`：學習來源與原始／學習身份、各基準工作量、真實深度三短比較的停止、四程序續跑、逐開局報告及棋譜不變。`ui/test_learned_comparison.py` 以 UI 事件驗證預覽、額外參考、凍結、停止及重開；日常測試只跑小型合法開局。

`test_combination_training.py`：直接權重精確保留、來源相容與測試曝光、固定四設定手算增量、聯合選定與合法另存、真實求解程序取消及共用期限恢復。`ui/test_combination_training.py` 以事件勾選預覽、訓練、重開、另存兩種組合、載入真人對戰，並核對直接／聯合候選送入共同開局比較後的完整設定及來源。
