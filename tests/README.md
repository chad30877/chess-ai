# 測試導覽

[回到專案總覽](../README.md) · [開發計畫](../docs/開發計畫.md)

更新日期：2026-09-09。P2 已完成，測試依責任分類，沿用 unittest。P3 更新 engine 匯入／patch 路徑後為 91 個測試；P4 增至 98 個，P5 增至 105 個，P6/S0 增至 114 個，S1 新增 5 個基本排序案例，目前完整 119 個測試通過。

## 目前覆蓋

| 檔案 | 責任 |
| --- | --- |
| rules/test_game_rules.py | 共用棋規、特殊走法、重複局面歷史、終局與上限 |
| evaluation/test_evaluation_config.py、evaluation/test_evaluator_semantics.py、evaluation/test_piece_square_tables.py | 評分設定驗證／往返、分項加總、評分視角、子力與 PST、鏡射 |
| search/test_alphabeta_player.py、search/test_alphabeta_searcher.py、search/test_greedy_terminal_scoring.py、search/test_move_ordering.py、search/test_search_types.py | 搜尋委派、Minimax 比對、共用終局／申請和棋分數、基本走法排序、分支歷史、根棋盤隔離與參數 |
| self_play/test_batch_generation.py | 批次、CSV／JSONL、相容與失敗保存 |
| self_play/test_batch_ui_storage.py | UI 批次保存、日期流水號、種子與跨午夜分類 |
| replay/test_replay_session.py | 回放跳步及邊界 |
| ui/test_live_session.py | 背景選步、暫停／停止、真人回合與歷史 |
| ui/test_chess_application.py | Pygame 事件、模式、真人落子、回放查找與縮放 |
| self_play/test_engine_match.py | Random／material CLI 完整對戰、原子力語意、種子、輪替／統計與舊選項拒絕 |
| self_play/test_evaluation_comparison.py | 設定 A/B 同局面交換黑白、種子重現、Random baseline、未完成統計、CLI 與範例設定 |
| test_engine_imports.py | 各 engine 模組與 UI 入口於獨立程序載入，檢查循環匯入 |
| self_play/test_cli_roundtrip.py | CLI 多程序生成、CSV 棋譜匯出及回放結果一致 |
| test_discovery.py | 遞迴發現涵蓋所有測試模組、使用 tests 命名空間且案例不重複 |
| helpers/executors.py | 共用 ManualExecutor，由測試控制背景工作完成時機 |
| test_documentation.py | 文件本機連結／標題錨點與程式碼區塊完整性 |

## 執行方式

從專案根目錄執行完整測試：

```powershell
& "./.venv/Scripts/python.exe" -m unittest discover -s tests -t . -v
```

只檢查文件：

```powershell
& "./.venv/Scripts/python.exe" -m unittest discover -s tests -t . -p test_documentation.py -v
```

環境設定見 [README](../README.md#環境設定)。UI 自動測試使用 dummy 驅動，不代表實體桌面 DPI、所有平台或真人目視驗證已完成。`scripts/test.py` 是手動 FEN 除錯工具，不是這套測試入口。

## 分類與共用工具

`rules/` 管共用棋規，`evaluation/` 管靜態評分，`search/` 管搜尋，`self_play/` 管自動對戰、批次保存與 CLI，`replay/` 管回放狀態，`ui/` 管介面與即時對局。跨區塊整合案例依主要責任歸類；例如批次 UI 保存放在 self_play，保留整個測試類別與驗證內容。

共用 `ManualExecutor` 位於 `helpers/executors.py`；介面與即時對局測試都從 `tests.helpers.executors` 匯入，不再互相匯入測試檔。僅單一檔案使用的測試工具留在該檔。文件與 discovery 測試留根目錄；tests 與各子目錄均以 `__init__.py` 標記為套件。

執行 discovery 時加上 `-t .`，以專案根目錄為匯入起點，讓 UI 測試使用 `tests.ui`，避免與正式程式的 `ui` 套件同名衝突。單一分類與單一模組可分別執行：

```powershell
& "./.venv/Scripts/python.exe" -m unittest discover -s tests/ui -t . -v
& "./.venv/Scripts/python.exe" -m unittest tests.self_play.test_engine_match -v
```

P2 搬移前後已逐一比對 88 個原有案例 ID（只移除新增的套件前綴），無遺漏或重複；搬移的 test 方法也經 AST 比對，內容未變。新增的 discovery 測試會檢查磁碟上的所有測試模組都被發現，避免子目錄缺少套件標記而靜默漏跑。完整測試包含多程序、CLI 與 dummy UI，89 個全部通過，`git diff --check` 通過。

## 驗證界線

正確性測試、執行時間／節點量測、棋力對戰是不同證據。例行測試採小型且有界案例；長時間棋力與調參實驗另行執行並記錄設定。每次程式或文件改動依 AGENTS.md 更新相關測試，完整驗證後 commit。
