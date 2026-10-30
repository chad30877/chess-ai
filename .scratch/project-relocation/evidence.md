# 搬移驗證紀錄

日期：2026-10-30。目的地：`D:\Projects\chess-ai`。

## 資料

- 規劃檢查 12,702 份文件，更新 12,222 份 JSON 與 12,191 個內容身分。
- [搬移前](before.json)與[搬移後](after.json)的 44 項正式讀取驗證結果逐項相同，含 87 個候選設定、教師與學習完成進度、比較勝和敗及可恢復棋局數。
- [獨立內容比對](invariants.json)確認 `data/` 與 `configs/` 的 12,701 份 JSON 檔案清單相同；差異僅為路徑及 SHA-256 身分，其他研究數值、走法、文字及資料結構相同。其餘 88 份資料檔逐位元相同。
- 正式驗證執行時，原目錄內容已全部移開；原位置沒有 Python、程式碼或資料，無法作為新位置讀取失敗時的替代來源。
- 更新另外五份歸檔文件及一份效能量測 JSON 的路徑文字；Git 已提交歷史未重寫。

## 環境與測試

- Python 3.12.13 的解譯器與 `.venv` 均位於新專案，11 個依賴版本與[搬移前清單](environment.txt)完全相同。
- `tests.test_project_relocation` 的 4 個測試通過，涵蓋巢狀封印、舊格式整份雜湊、路徑索引、損毀拒絕、重複規劃、舊位置不可用，以及部分完成比較搬移後續跑。
- `tests.ui.test_comparison_recovery` 的 3 個測試通過；`tests.ui.test_saved_selection` 的 13 個案例均通過。
- 一次測試指令誤列不存在的 `tests.ui.test_learning_recovery`，造成該次指令的載入錯誤；後續改用正確的 `tests.ui.test_comparison_recovery`，與搬移測試一起執行的 7 個案例全部通過。
- 以 SDL dummy 驅動執行實際應用程式事件，從首頁開啟[候選清單](inventory.png)，並開啟既有比較棋譜按下一步；[回放畫面](replay.png)已人工檢視。未啟動新研究或正式長對局；測試後還原使用者介面偏好內容。

## 尚待使用者處理

原位置只剩空目錄，沒有 junction；Windows 的目錄占用來自 Codex 與其 Node 執行程序。使用者已表示自行移除。Codex 專案已含新路徑，但仍保留舊入口；請一併只保留新專案來源。

自動核准審查拒絕刪除 `D:\Projects\chess-ai-relocation-backup` 及本批 `runtime/` 工具暫存，僅回報 `blocked by policy`，未提供細節。備份不再是執行依賴，仍保留原始資料以待使用者清理；工具暫存與逐檔遷移清單由本批 `.gitignore` 排除。

人工檢查：從新位置執行 `.venv\Scripts\python.exe -m apps.play_ui`，開啟比較候選、既有比較紀錄及棋譜，確認完成數與回放正常。
