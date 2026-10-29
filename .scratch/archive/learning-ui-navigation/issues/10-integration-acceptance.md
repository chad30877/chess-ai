# UI10：完成跨流程與視窗驗收並更新操作文件

狀態：已完成。
阻擋來源：[UI06](06-group-learning.md)、[UI09](09-comparison-results.md)。
對應決策：Q1～Q18（整合驗收）。
規格：[學習實驗導覽與操作改善](../spec.md)。
索引：[本批工作票](../README.md)。

UI01～UI09 已完成；本票整合驗證與獨立複審均已完成。

## 要交付的行為

驗證所有工作票合併後仍能從直接入口使用舊成果、新建學習、跨頁執行、停止重開及比較回放，並在最小與預設視窗保持可操作。更新實際操作文件及本批結案證據。

## 範圍與界線

UI06 與 UI09 的直接依賴閉包涵蓋 UI01～UI09，九票均完成必要驗收後才可開始本票。各票自己的功能驗收不能延後到本票才補做；本票負責跨票整合與文件一致性，不啟動正式長研究。

參考位置：本批已完成 UI 與公開執行入口、`tests/TESTING.md`、`docs/使用者介面.md`、`docs/ML試驗教學.html`、本批索引及 `docs/開發計畫.md`。檔案位置僅供探索定位，不限制合理實作方式。

## 功能驗收與驗證方式

- [x] 已確認 Q1～Q18 均有完成票與對應驗收證據。驗證：逐條稽核規格、各票勾選、實際測試或操作證據，未通過項保留未勾選。
- [x] 已有舊成果的使用者能直接從學習實驗進入比較。驗證：以新舊格式及跨來源資料走實際 UI 事件，不先經教師或組合頁。
- [x] 新建單群組學習到另存與用於對戰的短流程可完成。驗證：小資料真實求解、保存與實際套用設定。
- [x] 任務跨頁、停止、關閉及重開續跑的整條流程保持同一來源。驗證：教師標記、訓練及比較各做短整合案例並核對保存成果。
- [x] 較早完成成果不被後來未完成或失效成果取代。驗證：混合來源選擇、改名、重開及失效恢復的跨頁事件流程。
- [x] 比較結果、設定明細與回放返回維持正確來源。驗證：跨來源候選建立短比較後檢視結果與回放。
- [x] 900×768 最小視窗中的主操作可讀可用。驗證：實際渲染導覽、進度、錯誤、群組選擇與長清單並操作捲動。
- [x] 1280×960 預設視窗中的資訊層級清楚。驗證：Agent 畫面檢查位置、階段、任務與結果摘要，詳細資訊不壓過主操作。
- [x] 相關既有一般批次、真人與回放流程沒有因共用路由或任務變更而退化。驗證：依實際改動範圍跑現有事件整合回歸。
- [x] 整批必要驗收的限制與未完成項均有如實記錄。驗證：區分自動測試、Agent 實際操作與僅提供人工步驟，必要驗收缺漏不得宣稱結案。

## 驗證安排

重用各票已通過的證據，針對跨票風險追加整合案例；既有來源、UCI、保存與求解邊界沿用現有測試慣例，不建立通用測試框架或靜態文字測試。
共通測試與結案規則見[索引](../README.md#驗收與結案規則)及[專案規範](../../../../docs/agents/issue-tracker.md)。

## 文件與提交

- [x] 更新 `docs/使用者介面.md`，反映實際交付入口及任務行為。
- [x] 更新 `docs/ML試驗教學.html` 與受影響畫面，使步驟能照實際介面操作。
- [x] 更新 `tests/TESTING.md` 的驗證入口，記錄本批整合證據。
- [x] 記錄實際驗收證據及限制。
- [x] 同步本票、批次索引與開發計畫的狀態。
- [x] 建立繁體中文 Git commit，讀回核對提交與狀態。

## 人工重現方式（尚未執行）

依新文件從學習實驗直接找舊候選，再做一組小型學習；執行中切頁、停止重開、手動續跑，最後查看比較結果及回放。

## Q1～Q18 逐項稽核

| 決策 | 完成票 | 已保存的驗收證據 |
| --- | --- | --- |
| Q1 目的入口 | UI05 | `tests.ui.test_learning_navigation.LearningNavigationTest` 的目的入口事件 |
| Q2 路徑與階段 | UI05 | `SourceStageTest`、`MainEntryCoverageTest` 與兩尺寸畫面 |
| Q3 合併單群組 | UI06 | `tests.ui.test_group_draft` 新建與舊棋子位置操作 |
| Q4 直接比較與紀錄 | UI05、UI07～UI09 | `tests.ui.test_learning_integration` 與 `tests.ui.test_comparison_history` |
| Q5 載入回應 | UI01 | `tests.ui.test_learning_loading` 返回及交錯讀取事件 |
| Q6 清單及選擇 | UI02、UI09 | `tests.ui.test_saved_selection` 與比較紀錄重開 |
| Q7 跨來源候選 | UI07 | `tests.test_all_candidates` 多資料來源與舊格式；整合短比較來源核對 |
| Q8 前置不足 | UI05、UI08 | `LearningNavigationTest.test_learning_entry_reaches_missing_labels_and_return_to_teacher` 及比較前置事件 |
| Q9 跨頁工作 | UI03、UI05、UI08 | `tests.ui.test_learning_task_navigation` 與本票停止恢復鏈 |
| Q10 群組選擇 | UI06 | `tests.ui.test_group_draft` 零、一、多組選擇及真實求解 |
| Q11 新建與續跑 | UI06 | `tests.ui.test_group_draft`、`tests.ui.test_group_training` |
| Q12 用途與工作量 | UI08 | `tests.ui.test_comparison_setup` 三候選預覽與凍結計畫 |
| Q13 耗時互斥 | UI03、UI08 | `TaskNavigationTest.test_another_start_is_blocked_while_pilot_is_running` 與比較開始事件 |
| Q14 停止保存與手動恢復 | UI04、UI09 | `tests.ui.test_learning_close`、`tests.ui.test_comparison_history` |
| Q15 固定入口與層級 | UI05 | `MainEntryCoverageTest` 各子頁進入四個主入口 |
| Q16 名稱與改名 | UI02、UI09 | `tests.ui.test_saved_selection` 同名、重開與快照不變；比較紀錄改名 |
| Q17 摘要與下一步 | UI06、UI09 | `tests.ui.test_group_draft`、`tests.ui.test_comparison_history` 及完成／未比較畫面 |
| Q18 失效恢復 | UI01～UI04、UI07、UI09 | 載入失效、損壞／缺失混合、重試及紀錄改選事件 |

## 驗收證據與限制

- UI01～UI09 的各票均為已完成且各項已勾選；上表逐項追溯對應事件與原票證據。
- 整合版本先執行關閉／群組／成果選擇 37 項、比較紀錄／用途／候選／導覽 23 項、一般批次／真人／回放／載入與跨頁 69 項，均通過；修復後重跑關閉／群組／成果選擇 37 項，以及跨來源候選／新整合案例／比較紀錄／一般 UI 68 項均通過。
- 新增三條完整來源鏈與長清單滾輪事件同程序重跑 4 項通過；最終 `tests.ui.test_learning_close tests.ui.test_learning_integration tests.ui.test_saved_selection.SavedTeacherSelectionTest.test_long_named_dataset_list_can_reach_last_page` 共 21 項通過；11 份真實候選的滾輪分頁事件亦通過。`git diff --check` 通過。
- `tests.ui.test_learning_integration` 從候選清單勾選舊棋子位置與單群組、選用途並啟動，使用合法短開局實際完成 32 局，再由整組紀錄逐一核對凍結來源、設定及回放返回；僅在開局來源邊界替換成短局，不是正式研究。
- `tests.ui.test_learning_close` 的標記、單群組及比較案例各經實際事件切頁、關閉停止、重開並手動續跑，核對來源快照及已提交資料；均不自動啟動續跑。
- 900×768 以 SDL dummy 實際繪製並檢查群組草稿、工作進度、缺失資料錯誤與十份長名稱清單；滾輪事件從第一頁移到第二頁並能選取。1280×960 檢查首頁、群組成果、工作進度、候選及用途預覽；這些是 Agent 檢視，非使用者操作。
- 教材現行步驟使用六張當前應用程式畫面；舊版 60 盤研究過程保留並收合為歷史紀錄。畫面以小型測試資料及 SDL dummy 產生；HTML 25 張圖片均存在。
- 本票不要求正式長研究，未執行完整正式局數；真實系統選檔視窗、不同桌面 DPI 與輸入法亦未由本次自動驗收覆蓋。人工重現步驟僅供操作參考。

- 獨立審查指出需由 UI 實際選擇跨來源候選並執行整組比較，已補測並複審；滾輪、模態與群組啟動狀態亦經複審。

- 整合分支再以專案虛擬環境執行 `tests.ui.test_learning_close tests.ui.test_learning_integration tests.ui.test_saved_selection.SavedTeacherSelectionTest.test_long_named_dataset_list_can_reach_last_page`，21 項通過；獨立複審未確認其他阻擋。
