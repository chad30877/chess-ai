# Chess AI

以 Python 開發的西洋棋 AI 實驗專案，提供真人對戰、批次比較、棋譜回放及評分權重學習。棋規使用 `chess`，介面使用 `pygame`；選步、評分與研究流程由專案實作。

## 環境設定

以下使用 **Windows CMD（命令提示字元）**，假設已安裝 Git。另準備 [Python 3.12](https://www.python.org/downloads/windows/)（含 `py` 啟動器及 Tcl/Tk，供檔案選擇器使用）。安裝位置可自行選擇，不需要原作者的 Python 或 Conda 環境。

先取得專案；此範例放在使用者的 `Projects` 資料夾，也可改成自己的位置：

```cmd
if not exist "%USERPROFILE%\Projects" mkdir "%USERPROFILE%\Projects"
cd /d "%USERPROFILE%\Projects"
git clone https://github.com/chad30877/chess-ai.git
cd chess-ai
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install chess pygame zstandard numpy scipy
```

後續指令都從專案根目錄執行，直接指定虛擬環境的 Python，無須先啟用環境。依賴版本目前未鎖定；既有學習實驗會保存並核對數值套件版本。

## 快速開始

```cmd
.venv\Scripts\python.exe -m apps.play_ui
```

首頁提供真人下棋、批次自動對戰、對局紀錄與學習實驗。批次完成每盤即保存；停止後可從紀錄查找。評分設定按鈕開啟共用小視窗，以名稱及實際啟用群組查找，候選可多選。

先看隨專案附上的回放：

```cmd
.venv\Scripts\python.exe -m apps.play_ui --replay data\replays\sample_replay.json
```

也可產生兩盤短批次，檢查輸出與回放；每盤最多雙方合計落子 12 次：

```cmd
.venv\Scripts\python.exe -m scripts.generate_dataset --games 2 --workers 2 --seed 42 --max-plies 12 --batch-name "輸出驗證" --tag smoke
```

## 研究資源範例

以下採目前使用的來源。可以替換成相容資源，但須符合各入口支援的格式與條件；正式研究前先查看[開發計畫](docs/開發計畫.md)與既有保存結果。

### Stockfish 19

教師先導使用 [Stockfish 官方下載](https://stockfishchess.org/download/)的命令列引擎（GPL-3.0）。以下固定下載 [19 版 Windows x86-64 Universal](https://github.com/official-stockfish/Stockfish/releases/tag/sf_19)，適用 x64 Windows：

```cmd
if not exist tools\stockfish mkdir tools\stockfish
curl.exe -fL "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip" -o "tools\stockfish\stockfish19.zip"
.venv\Scripts\python.exe -m zipfile -e "tools\stockfish\stockfish19.zip" tools
```

壓縮檔本身含 `stockfish` 目錄，解壓後的執行檔為 `tools\stockfish\stockfish-windows-x86-64-universal.exe`。**新先導預填所在專案的這個位置**；也能按「選取檔案」使用其他安裝位置。取消選檔保留原值，重開既有先導顯示其保存路徑。其他硬體請從官方選對應版本；現有教師流程會檢查引擎身分與 UCI 條件，不保證任意引擎都相容。

### 標準西洋棋 PGN

「學習實驗」可直接取得 [Lichess 2013 年 1 月標準棋譜](https://database.lichess.org/)（CC0），亦可先下載後選擇本機來源：

```cmd
if not exist data\learning\sources mkdir data\learning\sources
curl.exe -fL "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst" -o "data\learning\sources\lichess-2013-01.pgn.zst"
```

本機來源填入 `data\learning\sources\lichess-2013-01.pgn.zst`。支援 UTF-8 標準棋 PGN，以及 `.pgn.zst`、`.pgn.gz`、`.pgn.bz2` 壓縮版本，無須手動解壓；可換其他月份或相容 PGN，來源授權需自行確認。資料建立會去重抽樣、分組及保存來源身分，非標準棋不納入。

### 已隨專案提供的開局庫

`data/openings/` 已包含 [Lichess 開局資料](https://github.com/lichess-org/chess-openings)的 `a.tsv` 至 `e.tsv`、授權及來源清單，正常 clone 後即可使用。來源固定為 `a6189a30dc273ccb21fc2536a9a2fefd5592a67a`（CC0）；以下只在需要取得或修復同版本檔案時執行，會替換這六個檔案：

```cmd
for %F in (a.tsv b.tsv c.tsv d.tsv e.tsv COPYING.txt) do curl.exe -fL "https://raw.githubusercontent.com/lichess-org/chess-openings/a6189a30dc273ccb21fc2536a9a2fefd5592a67a/%F" -o "data\openings\%F"
```

這是互動式 CMD 語法；若另存 `.bat`，將 `%F` 改為 `%%F`。保留專案的 `manifest.json`，載入時會核對六檔 SHA256。開局資料採含 `eco`、`name`、`pgn` 欄位的 TSV；替換其他來源需整理為相同檔案結構，並同步來源及雜湊清單，不能只更換任意 TSV。

## 學習流程入口

1. 在「學習實驗」建立資料，查看分組與抽樣局面，再進入「教師先導」。
2. 確認專案內的 Stockfish 路徑或選取其他執行檔，設定「同時分析局面數」。新先導預設取可用 CPU 數與 4 的較小值，至少 1；每個教師程序固定單執行緒。
3. 建立先導，使用訓練組最多 100 個局面。完成後並列 50,000／200,000 節點的實測時間與「後續標記」預估，再選定預算。
4. 進入「教師標記」，沿用凍結的教師、預算及並行數。停止後重開按「續跑／重試」，只補未完成或失敗的局面；完整標記後才能學習、另存設定及建立共同開局比較。

預估使用同一並行條件的實測吞吐，依實際局面數並扣除可重用先導結果計算，只涵蓋後續教師標記。舊資料缺少量測時顯示「無法估計」；改並行數須建立新先導。每次執行共用八小時上限，停止保存、不自動接續。完整操作與結果判讀見 [ML 離線教學](docs/ML試驗教學.html)，請連同 `docs/ml-guide/` 保存。

## 文件與資料位置

| 入口 | 內容 |
| --- | --- |
| [使用者介面](docs/使用者介面.md) | 真人、批次、對局查找、回放與設定選擇 |
| [自動對戰](docs/自動對戰.md) | CLI、批次保存及棋譜匯出 |
| [評分調整與實驗](docs/評分調整與實驗.md) | 評分設定、比較及研究條件 |
| [搜尋與評分](docs/搜尋與評分.md) | 選步策略、評分項與效能量測 |
| [開發計畫](docs/開發計畫.md) | 目前交付、後續研究與限制 |
| [測試說明](tests/TESTING.md) | 各測試保護的行為及執行方式 |

評分設定檔在 `configs/evaluation/`；學習實驗在 `data/learning/`，批次在 `data/batches/`，單盤回放在 `data/replays/`。批次的 `games.csv` 是摘要，`positions.csv`／JSONL 才是逐手局面。軟體驗收與短流程證據不等於完整研究或棋力提升；開發歷史以 Git 為準。

## 開發用途

需要提交修改時，在本專案設定自己的 Git 身分（替換範例姓名與信箱）：

```cmd
git config user.name "你的名字"
git config user.email "you@example.com"
git status
```

執行完整測試前另裝程序觀測使用的 `psutil`：

```cmd
.venv\Scripts\python.exe -m pip install psutil
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

測試需保留 `-t .`，避免測試目錄與正式模組重名。提交規範見 [AGENTS.md](AGENTS.md)，工作票規則見 [issue tracker](docs/agents/issue-tracker.md)；獨立效能工具的用法見[搜尋與評分](docs/搜尋與評分.md)。
