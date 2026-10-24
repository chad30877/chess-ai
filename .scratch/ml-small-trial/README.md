# ML 小規模試驗：規格與工作票索引

目前 #27–#37 均已驗收結案；完整短流程與離線教學已交付，整批雙軸審查與修正已完成，待整合收尾。正式研究尚未完成，勿將軟體短流程當棋力證據。最新票況以 GitHub 為準；本目錄保存同步需求及各票證據，實作歷史由 Git 保存。

- [父規格 #26](https://github.com/chad30877/chess-ai/issues/26)／[本機規格](spec.md)
- [離線操作教學](../../docs/ML試驗教學.html)／[目前狀態與接續研究](../../docs/開發計畫.md)
- [發布編號與依賴對照](publication.json)：發布時雜湊不是最新驗收紀錄，不覆寫歷史宣稱重新驗證。

## 工作票

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


## 整批審查證據

Spec 審查無缺失，驗收稽核通過；Standards 無明文規範違反，指出三個學習流程的候選選擇重複。收尾將驗證 MAE、凍結順序及同分容差集中在 `training.select_candidate`，保留各流程錯誤文字，並補齊 README 的 numpy／scipy 依賴與隔離 uv 命令。

既有單組、五組、組合與三個 UI 模組共 17 項測試，重構前 209.995 秒、重構後 210.666 秒均通過；沿用公開流程的求解、選擇、凍結、保存及續跑驗證，不新增內部實作測試。README 相同五套件的隔離 uv 環境已成功匯入並呼叫 `training_rules()`（Python 3.12.13、numpy 2.5.4、scipy 1.18.1）。人工重現可依 README 建立環境，從學習頁執行單組／五組與聯合訓練，確認驗證候選凍結後可另存。

## 已核准的測試入口

1. 應用程式 UI 事件及學習實驗公開執行入口：走真實資料處理、求解、保存、重開、續跑，再接既有比較與回放。
2. 只在外部 UCI 教師程序邊界使用可控制替身；真實 Stockfish 短流程另存證據。時間及檔案系統故障可控制，避免等待八小時或製造不可重現失敗。
3. 少量可手算數值契約驗證資料隔離、校準、非負權重與正式評分一致；合法開局及真實 spawn 守住歷史與停止清理。不測靜態文案、常數或內部呼叫形式。

測試定位見 [tests/TESTING.md](../../tests/TESTING.md)。各票驗收證據及限制見上表同步文件；M11 的交付版 UI 包含實際來源、Stockfish、五組與組合、深度三搜尋、停止重開及回放。完整 500 盤標記、候選正式研究與每候選每基準 64 局留交付後分次執行。

## 同步與結案

依 [tracker](../../docs/agents/issue-tracker.md) 完成證據、GitHub／本機票勾選、索引與計畫同步、提交及讀回稽核；一般代理操作驗收不要求使用者再做一次。原生阻擋關係未解除的票不提前宣稱完成；不連帶關閉父規格。
