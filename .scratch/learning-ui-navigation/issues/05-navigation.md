# UI05：建立目的首頁、固定主入口與可返回的位置路徑

狀態：待驗收。
阻擋來源：[UI01](01-responsive-loading.md)、[UI02](02-result-selection.md)、[UI03](03-task-lifecycle.md)。
對應決策：Q1、Q2、Q4、Q8、Q9、Q15。
規格：[學習實驗導覽與操作改善](../spec.md)。
索引：[本批工作票](../README.md)。

UI01、UI02、UI03 均已完成；本票合併後整合回歸發現錯誤，待修復並重新驗收。

## 要交付的行為

學習實驗可按目的進入，固定四個主入口與正確位置路徑；流程階段另反映所選資料。缺少前置成果仍能開頁並直接前往補足。

## 範圍與界線

教師先導與標記同屬教師評分；單群組與組合同屬評分權重學習。此票可導向既有可操作子頁；單群組內容改版由 UI06、全來源候選由 UI07、比較紀錄由 UI09 交付，不以空白占位頁冒充完成入口。

參考位置：`apps/chess_application.py`、`ui/learning_view.py` 與各學習子頁的路由、來源及返回操作。檔案位置僅供探索定位，不限制合理實作方式。

## 功能驗收與驗證方式

- [x] 學習實驗首頁可依建立新實驗、接續學習、比較候選或查看成果等目的直接進入對應功能。驗證：從首頁操作各目的並核對實際頁面及來源。
- [x] 四個主入口可從各學習子頁使用。驗證：逐頁操作資料準備、教師評分、評分權重學習及比較候選。
- [x] 相同子頁的位置路徑不因進入歷史而改變。驗證：從不同入口進教師標記及比較頁，核對一致的父子關係。
- [x] 位置路徑返回正確上層並保留明確選取的來源。驗證：教師標記回教師評分、組合比較回正確上層等事件流程。
- [x] 候選入口不必先經教師或組合頁。驗證：從學習實驗首頁直接進入既有候選功能，核對操作路徑。
- [x] 資料階段狀態反映目前選定來源。驗證：在不同完成狀態的資料間切換，確認不混用其他資料的完成進度。
- [x] 缺少前置成果的頁面仍可開啟並提供直接補足入口。驗證：未完成教師標記時進學習頁，點前往接續標記。
- [x] 前置不足時無法啟動依賴該成果的運算。驗證：在缺少預算或標記資料情境操作開始，核對未建立工作。
- [x] 未滿足新任務前置條件時仍能查看既有成果。驗證：選擇未完成資料後開啟既有可讀結果。
- [ ] 新導覽中的載入返回與活動任務進度遵循 UI01、UI03。驗證：在新主入口交錯切頁、返回及進入活動任務。

## 驗證安排

沿用應用程式事件測試；畫面檢查涵蓋位置路徑、所選來源、階段狀態及活動任務提示，不用靜態文字比對代替導覽行為。
共通測試與結案規則見[索引](../README.md#驗收與結案規則)及[專案規範](../../../docs/agents/issue-tracker.md)。

## 文件與提交

- [x] 更新受影響操作說明，反映本票實際交付行為。
- [x] 記錄實際驗收證據及限制。
- [x] 同步本票、批次索引與開發計畫的狀態。
- [x] 建立繁體中文 Git commit，讀回核對提交與狀態。

## 人工重現方式（尚未執行）

從學習實驗直接進比較候選，再進教師標記並點路徑回上層；切換資料確認階段狀態跟著變化。

## 驗收證據與限制

- 應用程式事件：`tests.ui.test_learning_navigation.MainEntryCoverageTest` 使用真實保存的兩組學習成果，在首頁及 11 個子頁各操作四個主入口，共 48 次到達指定頁面；凍結評估資料供入口測試，未執行正式對局。
- `tests.ui.test_learning_navigation`、`tests.test_candidate_inventory.InventoryUiTest` 及 `tests.ui.test_combination_training.CombinationUiTest.test_select_preview_train_reopen_export_both_kinds_and_load_battle` 驗證目的入口、跨來源成果、缺少前置、不同入口的位置路徑及比較返回原來源。
- 合入 UI04 後 `tests.ui.test_learning_close tests.ui.test_learning_navigation tests.ui.test_learning_task_navigation` 共 28 項通過，涵蓋讀取返回、工作進度、停止及恢復；另於防護修改後執行群組、標記、先導與比較共 7 項通過。UI04 合入前相關回歸共 91 項通過。
- 以 SDL dummy 實際渲染檢查 900×768 與 1280×960 首頁；非使用者操作。`tests.ui.test_learning_navigation` 與 `tests.ui.test_teacher_picker` 分開執行通過，同程序執行曾出現 Tcl_AsyncDelete 並以碼 1 結束，未宣稱該組合通過。
- 獨立審查指出成果瀏覽時任務及標記來源、瀏覽模式、直接接續標記索引及比較返回來源等問題，均已修正並複審。上次選定的較早完成標記不被較新未完成標記取代。
- 本票直接使用既有單次群組候選盤點；全來源候選與比較紀錄分別由 UI07、UI09 交付。人工重現步驟不等於已執行。

- 整合分支重跑 `tests.ui.test_learning_close tests.ui.test_learning_navigation tests.ui.test_learning_task_navigation tests.ui.test_learning_loading tests.ui.test_saved_selection`，55 項中 1 錯誤：`SavedTeacherSelectionTest.test_changing_label_while_training_preserves_running_task_context` 找不到 `learning_task_return`。單獨重跑相同錯誤；需修復並重新驗收。
