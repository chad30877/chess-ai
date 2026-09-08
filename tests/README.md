# 測試導覽

[回到專案總覽](../README.md) · [開發計畫](../docs/開發計畫.md)

更新日期：2026-09-09。目前測試仍平鋪於 tests，本次未搬檔或切換框架。測試分類安排在 P2，舊 ML 測試隨 P1 調整。

## 目前覆蓋

| 檔案 | 責任 |
| --- | --- |
| test_game_rules.py | 共用棋規、特殊走法、重複局面歷史、終局與上限 |
| test_evaluator_semantics.py、test_piece_square_tables.py | 評分視角、子力與 PST、鏡射；前者尚有待移除 ML 別名測試 |
| test_alphabeta_player.py、test_alphabeta_searcher.py、test_search_types.py | 搜尋委派、Minimax 比對、終局分數與參數 |
| test_batch_generation.py | 批次、CSV／JSONL、相容與失敗保存；尚含舊訓練讀入測試 |
| test_batch_ui_storage.py | UI 批次保存、日期流水號、種子與跨午夜分類 |
| test_replay_session.py | 回放跳步及邊界 |
| test_live_session.py | 背景選步、暫停／停止、真人回合與歷史 |
| test_chess_application.py | Pygame 事件、模式、真人落子、回放查找與縮放 |
| test_documentation.py | 文件本機連結／標題錨點與程式碼區塊完整性 |

## 執行方式

從專案根目錄執行完整測試：

```powershell
& "./.venv/Scripts/python.exe" -m unittest discover -s tests -v
```

只檢查文件：

```powershell
& "./.venv/Scripts/python.exe" -m unittest discover -s tests -p test_documentation.py -v
```

環境設定見 [README](../README.md#環境設定)。UI 自動測試使用 dummy 驅動，不代表實體桌面 DPI、所有平台或真人目視驗證已完成。`scripts/test.py` 是手動 FEN 除錯工具，不是這套測試入口。

## 分類草案

P2 規劃依 rules、evaluation、search、self_play、replay、ui 分類，共用工具放 helpers；沒有測試的分類不先建立。文件測試可留根目錄。以 `__init__.py` 或適合目前 Python 的配置維持 unittest 遞迴發現。

目前 test_chess_application.py 直接匯入 test_live_session.py 的 ManualExecutor；搬檔時應抽出共用工具，更新其他跨測試引用。先盤點測試 ID，再確認分類後同等案例仍被執行；只看最後 exit code 不足以排除漏跑。

## 驗證界線

正確性測試、執行時間／節點量測、棋力對戰是不同證據。例行測試採小型且有界案例；長時間棋力與調參實驗另行執行並記錄設定。每次程式或文件改動依 AGENTS.md 更新相關測試，完整驗證後 commit。
