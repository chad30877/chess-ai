# 專案規範

- 建立或安裝開發環境時，將執行環境、依賴套件與快取盡量放在專案目錄內；優先遵循專案及各工具的既有慣例，例如使用 .venv/ 作為虛擬環境目錄。避免修改全域環境。若所需工具無法放在專案內，先說明原因與替代位置，再詢問使用者。
- 若使用 mattpocock skill 使用本機 Markdown 追蹤議題時存放在 .scratch/<功能名稱>/
- 頁面文字應保持精簡；可由介面、操作流程或元件狀態直接理解的資訊，不要另外加入重複說明
- README、docs、註解及 Git commit message 使用繁體中文
- 每次改動完成後建立 Git commit，並簡單說明人工測試方式。


## Agent skills

### Issue tracker

實作、審查或結案工作票時，先讀 `docs/agents/issue-tracker.md` 的定位、驗收與結案規則；GitHub 為目前狀態來源。

### Domain docs

採用 single-context 根目錄文件配置，消費規則見 `docs/agents/domain.md`。

