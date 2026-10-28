# R07：整理 Windows CMD 環境準備與資源下載範例

狀態：已完成本機驗收與整合結案；不發布 GitHub。

## 父規格

本批本機規格「研究前的環境準備、教師並行與操作改善」。

## 建置內容

README 成為精簡的環境準備與操作入口：假設已安裝 Git，提供 CMD 的專案取得、Git 設定、Python 環境、依賴及啟動指令。以目前 Stockfish、棋譜與開局庫示範下載，明確標示可換其他相容來源，並連到既有詳細操作文件。

本票以文件檢閱交付，不要求全新電腦驗收或新增靜態文字測試。教師選檔、workers 與先導估時說明以已完成介面為準；不等待不影響環境準備的棋盤、設定選擇與真人狀態功能。

## 必要驗收

- [x] Git 已安裝的前提、CMD 專案取得及 Git 設定指令完整，提交身分設定置於開發用途；以文件檢閱驗證，不加入 Git 安裝教學。
- [x] Python 環境、必要依賴與啟動指令不綁定作者電腦配置；以逐段 CMD 語法與相對位置檢閱驗證。
- [x] Stockfish 下載與解壓範例對應可用執行檔及教師選檔流程；以官方來源核對及介面對照驗證。
- [x] 棋譜下載範例標明來源與目前支援的輸入格式；以來源核對及既有資料入口對照驗證。
- [x] 開局庫說明已隨專案提供，另附同版本取得／修復範例並標明 TSV 格式；以來源及專案內容檢閱驗證。
- [x] 各資源明示只是範例，可換其他相容來源，不誤稱任意格式皆可使用；以文件檢閱驗證。
- [x] 教師選檔、workers 及先導預估的簡短說明對應已交付操作；以實際介面對照驗證。
- [x] 重複歷史整理為目前狀態及既有文件連結，保留必要操作入口；以文件結構與連結檢閱驗證。

## 阻擋來源

- R01：教師選檔介面交付後才能核對下載位置與操作說明。
- R03：同條件先導預估交付後才能核對教師操作說明；其已間接依賴 R02，不重列阻擋。

## 文件與結案

- [x] 保存文件檢閱證據並整理開發計畫目前狀態，同步本機驗收狀態並建立提交。

## 人工重現方式（非額外驗收）

需要準備環境時，依 README 的 CMD 範例取得專案、建立環境、取得相容資源並啟動 UI；此說明不要求為結案另建乾淨電腦。

## 文件檢閱證據（2026-10-25）

- 開始撰寫前已確認 R01、R03 驗收完成，工作分支同步至整合提交 `e884c5c`（包含 R03 `e4442b4`）。本票只更新 README、此票與既有失效連結；開發計畫由整合工作統一同步。
- 逐段檢閱 README 九個 CMD 區塊：專案取得使用 `%USERPROFILE%` 範例與 `cd /d`；虛擬環境以 `py -3.12` 建立；所有執行、安裝、解壓命令使用專案相對位置。`for %F` 為互動式 CMD 寫法，另說明 `.bat` 的 `%%F`。Git 身分範例放在開發用途，沒有執行或改動使用者身分。
- [Python Windows 官方入口](https://www.python.org/downloads/windows/)及目前 Python 3.12／`chess`、`pygame`、`zstandard`、`numpy`、`scipy` 使用處已對照；原生選檔需要 Tcl/Tk，完整程序觀測測試另需 `psutil`。未要求安裝作者本機環境。
- [Stockfish 官方下載](https://stockfishchess.org/download/)及 [sf_19 固定發布](https://github.com/official-stockfish/Stockfish/releases/tag/sf_19)已核對。實際下載固定 x86-64 Universal ZIP 至系統暫存目錄（81,431,614 bytes），以 `zipfile` 檢查唯一執行檔為 `stockfish/stockfish-windows-x86-64-universal.exe`；故 README 解壓至 `tools` 正好對應 `TeacherView.default_command` 的專案相對位置。沒有引用隔離驗收的 C 槽路徑，也未改動既有教師。
- [Lichess 官方資料庫](https://database.lichess.org/)的 2013-01 PGN 連結與 CC0 已核對；下載 URL 和 `engine/learning/dataset.py` 的 `SOURCE_URL` 一致，格式說明依實際 UTF-8 PGN 及 zstd／gzip／bzip2 讀取分支。此票沒有下載整月棋譜或執行正式研究。
- [開局來源固定版本說明](https://raw.githubusercontent.com/lichess-org/chess-openings/a6189a30dc273ccb21fc2536a9a2fefd5592a67a/README.md)確認 TSV 欄位與 CC0。`git ls-files data/openings` 確認五個 TSV、COPYING 與 manifest 隨專案提供；另實際讀取官方相同 revision 六檔，SHA256 全數與本機 manifest 一致。替換來源說明保留檔案結構、授權／來源及雜湊驗證條件，下載定位為同版本取得／修復。
- 對照 `ui/teacher_view.py`、教師並行／估時實作與 [R03 實際畫面](../evidence/r03-pilot-estimates.png)：選取檔案、同時分析局面數、兩種節點的實測／後續標記時間、預算選擇與凍結規則均相符；README 明示同 workers 吞吐、最多 100 局面、舊量測不足與共享八小時上限。
- README 精簡為 118 行，11 個本機文件連結全部存在；保留既有「環境設定」「快速開始」錨點，將自動對戰文件連往移除歷史段落的連結改為測試說明。`scripts.generate_dataset --help` 核對短批次參數，`git diff --check` 通過。
- 本票依規格以文件檢閱、來源核對與介面對照驗收；未新增靜態文字測試，未宣稱在乾淨電腦部署或重跑功能測試。

- 整合收尾：開發計畫已整理為目前交付與後續研究，README 與本票已合併至整合分支；整合審查另由批次記錄。
