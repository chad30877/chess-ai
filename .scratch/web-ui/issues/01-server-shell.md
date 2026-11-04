# W01：伺服器骨架、啟動入口與側欄外殼

狀態：已完成。
阻擋來源：無。
實作：Claude。
規格：[網頁介面](../spec.md)。
索引：[本批工作票](../README.md)。

## 要交付的行為

執行一行指令，即可啟動只接受本機連線的伺服器並開啟瀏覽器，看到含四區側欄與各區占位頁的 Angular 外殼。每區都有自己的網址，瀏覽器的上一頁可以返回前一區。缺少前端建置時，顯示建置指示。依賴改由 `requirements.txt` 安裝。

## 功能驗收與驗證方式

- [x] 啟動指令開啟瀏覽器並顯示外殼。驗證：Agent 實際啟動並截圖。
- [x] 伺服器拒絕非 127.0.0.1 連線。驗證：API 測試以非本機位址請求。
- [x] 未建置前端時顯示建置指示，而不是空白頁。驗證：移除建置產物後啟動並截圖。
- [x] 四區網址可直接開啟，上一頁返回前一區。驗證：在實際瀏覽器操作。
- [x] `requirements.txt` 可在乾淨的 `.venv` 安裝現有依賴與 fastapi、uvicorn。驗證：新建臨時虛擬環境，安裝後啟動。
- [x] Node 套件與建置產物位於專案內，並列入 `.gitignore`。驗證：`git status` 中沒有建置產物。
- [x] 使用者實際啟動並確認。驗證：使用者於 2026-11-04 確認通過。

## 文件與提交

- [x] 更新受影響的操作說明：README 的安裝與「網頁介面」一節、`web/README.md`、`tests/TESTING.md`。
- [x] 記錄實際驗收證據與限制。
- [x] 同步本票與批次索引狀態。
- [x] 建立繁體中文 Git commit，讀回核對。

## 驗收證據與限制

- **API 測試**：`.venv\Scripts\python.exe -m unittest tests.api.test_server` 共 6 例通過，涵蓋：
  - `127.0.0.1` 與 `::1` 可存取 `/api/health`
  - 從 `192.168.1.20` 存取 API、首頁和前端路由都回 403
  - 未建置時回 503，並顯示 `npm run build` 指示
  - 提供建置檔，並把前端路由導回 `index.html`
  - 未知的 `/api` 路徑回 404，不會導到前端
  - 不提供建置目錄以外的檔案
- **完整回歸**：`.venv\Scripts\python.exe -m unittest discover -s tests -t .` 共 561 例通過，耗時 1,400 秒。
- **前端單元測試**：`npx ng test --watch=false` 1 例通過，確認側欄四區的標籤與網址。
- **實際瀏覽器**：用 `python -m apps.web --no-browser` 啟動，在內建瀏覽器操作：
  - 點側欄切換區塊
  - 上一頁從 `/learning` 回到 `/batch`
  - 直接開啟 `/records`，頁面標題為「對局紀錄 · Chess AI」
  - 1280 寬度淺色與 900 寬度深色截圖正常，深淺色跟隨系統
  - 暫時移走 `web/dist` 後首頁回 503，並顯示建置指示
- **乾淨環境**：在 scratchpad 用 uv 建立臨時 Python 3.12 環境，以 `requirements.txt` 安裝後，可載入全部依賴，`/api/health` 回應正常。
- **限制**：
  - 自動開啟瀏覽器使用 `webbrowser.open`。Agent 驗證時用 `--no-browser`，避免在使用者桌面跳出視窗，因此這一項留給使用者確認。
  - 外觀仍是 Angular Material 預設主題，字型與圖示暫時從 Google Fonts 載入，W02 再定版。
- **快取**：uv 與 npm 的快取放在專案的 `.cache/`，已列入 `.gitignore`。
- 預設埠號由 8765 改為 8642：本機 local-llm 專案使用 8765。
