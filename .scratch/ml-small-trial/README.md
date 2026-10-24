# ML 小規模試驗：規格與工作票索引

狀態：測試入口與十一票切分已核准，一份父規格與十一張子票均已發布 GitHub，套用 `ready-for-agent`，並建立原生父子及阻擋關係。後續規格與進度以 GitHub 為準；本目錄的規格與工作票同步最新核准內容及進度，不是另一套 issue tracker；`publication.json` 僅保留原始發布編號、關係與當時雜湊，歷次變更由 Git 保存。

M01（#27）已於 `658fede` 完成實作，325 項完整測試及雙軸審查通過，Issue 已關閉；依核准後的驗收方式，UI 事件整合測試已驗證選用、另存與載入對戰，全部驗收完成，詳見[狀態與操作方式](issues/01-readable-presets.md#實作與驗證狀態2026-10-23)。

M08（#34）程式已於 `c87fe17` 完成，323 項測試與雙軸審查通過；使用者已確認完成人工操作對戰驗收，Issue 已關閉。其餘工作票的最新狀態仍以 GitHub 為準。

## 規格

[#26：可操作、可續跑的 ML 小規模權重試驗與共同開局驗證](https://github.com/chad30877/chess-ai/issues/26)（[本機同步文件](spec.md)）

規格完整保留已確認的資料、教師、校準、訓練、誤差判準、組合、開局、UI、續跑及教學決策。本輪對戰只做深度 3／q4；深度 5 延後。教師正式節點預算仍依已約定的先導量測選擇，並非新的需求未決事項。

## 工作票切分

| 代號 | 工作票 | 阻擋來源 | 可獨立展示的成果 |
| --- | --- | --- | --- |
| M01 | [#27 辨識、選用與另存單群組設定](https://github.com/chad30877/chess-ai/issues/27)（[同步文件](issues/01-readable-presets.md)） | 無 | UI 看懂六個基本設定、另存並用於既有對戰 |
| M02 | [#28 建立資料分組與局面預覽](https://github.com/chad30877/chess-ai/issues/28)（[同步文件](issues/02-dataset-preview.md)） | 無 | 選棋譜、分盤抽樣去重、查看統計、保存重開 |
| M03 | [#29 教師先導量測與預算選擇](https://github.com/chad30877/chess-ai/issues/29)（[同步文件](issues/03-teacher-pilot.md)） | M02 | UI 比較教師兩種節點預算並凍結選擇 |
| M04 | [#30 教師標記、篩選與停止續跑](https://github.com/chad30877/chess-ai/issues/30)（[同步文件](issues/04-resumable-labeling.md)） | M03 | 逐局面標記、八小時停止、重開只補未完成 |
| M05 | [#31 單群組校準、學習、評估與另存](https://github.com/chad30877/chess-ai/issues/31)（[同步文件](issues/05-single-group-learning.md)） | M01、M04 | 棋子位置走通三強度訓練、獨立評估、另存 |
| M06 | [#32 五個單群組學習與結果比較](https://github.com/chad30877/chess-ai/issues/32)（[同步文件](issues/06-five-group-report.md)） | M05 | 共用資料、尺度及整次預算，分組結果可選用 |
| M07 | [#33 直接組合、聯合訓練與搭配比較](https://github.com/chad30877/chess-ai/issues/33)（[同步文件](issues/07-combinations.md)） | M06 | 自選群組，活動力＋王安全的固定權重與重訓分開 |
| M08 | [#34 一般與真人對戰開局庫](https://github.com/chad30877/chess-ai/issues/34)（[同步文件](issues/08-live-opening-book.md)） | 無 | 啟用開局庫、調整上限、離庫後搜尋、保存回放 |
| M09 | [#35 共同開局線的比較、續跑與歷史](https://github.com/chad30877/chess-ai/issues/35)（[同步文件](issues/09-common-opening-lines.md)） | M08 | 任意既有設定使用固定 32 線交換黑白，保留完整歷史 |
| M10 | [#36 學習結果接入深度三對戰報告](https://github.com/chad30877/chess-ai/issues/36)（[同步文件](issues/10-learned-comparison.md)） | M06、M09 | 學習候選進入共同開局比較，查看逐開局結果與回放 |
| M11 | [#37 離線截圖教學與完整流程驗收](https://github.com/chad30877/chess-ai/issues/37)（[同步文件](issues/11-offline-guide-acceptance.md)） | M07、M10 | 照實際畫面教學操作，核對重開續跑與研究證據 |

M01 已完成實作並結案；M02 可開工；M08 已完成並通過人工驗收，M09 已實作共同 32 線、完整歷史與既有設定續跑，正在完成審查與結案。M10 不被 M07 阻擋：單組與組合均輸出同一完整評分設定契約，組合完成後由 M11 一起驗收。M09 依賴 M08 是重用固定來源與合法開局序列服務，不把即時隨機選步帶入共同開局比較。沒有與功能無關的前置重構票。

## 已核准的測試入口

1. 以應用程式 UI 事件／學習實驗公開執行入口為主，走真實資料處理、訓練、保存、重開與續跑，再接既有比較／回放入口。既有範例是權重實驗流程、續跑與 UI 事件測試。
2. 只在外部 UCI 教師程序邊界使用可控制替身，測試分數視角、mate／bound、錯誤、逾時與中斷；真實 Stockfish 先導量測另跑。
3. 用少量可手算數值測試守住資料隔離、校準、非負權重與正式評分一致性；開局歷史用比較／回放流程及少量真實 spawn 測試。不測常數、文案或內部呼叫形式。

測試先例：現有 `test_experiment_flow`、`test_experiment_resume`、`test_alphabeta_comparison`、`test_chess_application` 與 `test_replay_session`。新學習入口比逐個替換內部模組更適合驗證需求，不預先指定檔名或拆模組數量。

## 發布紀錄與目前結案方式

- 已核對 GitHub 現有 #18–#25 均關閉，沒有待處理的同名 ML 規格；前一批功能作為既有基礎，不重複開票。
- GitHub CLI 2.103.0 可用，`ready-for-agent` 標籤存在；執行時使用已安裝的完整 CLI 路徑。
- 首次發布時已由 GitHub 讀回核對全部 12 個 issue 的標題、內文、開啟狀態及標籤；11 個父子關係與 11 條原生阻擋關係均符合核准切分。[發布編號與驗證對照](publication.json)保存精確編號及內文雜湊，後續請勿重複建立。
- 2026-10-23 依使用者要求同步調整父規格與十一張子票：一般操作由 Agent 驗證，必要功能、真實教師先導與實際截圖要求保留；M01、M08 已完成，其餘票保持開啟且未勾選。
- 後續 `/implement` 應依 [tracker 結案流程](../../docs/agents/issue-tracker.md)完成驗證、同步、提交與關票，再讀回核對。供使用者重現的操作方式不是另一次必要人工驗收；正式長實驗在軟體交付後由使用者分次執行。
- 可開啟父規格 #26 核對 11 張子票；開啟 #31 或 #36 核對兩個阻擋來源，並比較 GitHub 與本機工作票內容。
