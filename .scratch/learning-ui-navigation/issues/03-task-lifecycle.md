# UI03：統一跨頁任務進度與耗時工作互斥

狀態：已完成。
阻擋來源：無。
對應決策：Q9、Q13、Q18。
規格：[學習實驗導覽與操作改善](../spec.md)。
索引：[本批工作票](../README.md)。

已完成跨頁任務與互斥實作、驗證及審查；相關依賴可依其他前置票的狀態接續。

## 要交付的行為

教師、學習或比較執行中可離開執行頁查看舊成果，跨頁保留進度、返回任務與停止操作；一次只啟動一項耗時任務。先接入現有導覽，固定四入口由 UI05 交付。

## 範圍與界線

涵蓋教師先導、教師標記、舊獨立棋子位置訓練、五組訓練、組合訓練及學習比較的實際開始入口。保留每項任務內既有並行與預算，不增加排隊或多任務排程；關閉與重開由 UI04 負責。

參考位置：`apps/chess_application.py`、`ui/learning_view.py` 與教師、單群組、組合、比較頁的背景工作持有及停止入口。檔案位置僅供探索定位，不限制合理實作方式。

## 功能驗收與驗證方式

- [x] 離開執行頁後原任務持續工作。驗證：分別以教師、學習與比較小任務跨頁，核對同一任務持續產生進度或保存成果。
- [x] 跨頁可看到目前任務的簡短進度並返回正確任務。驗證：從其他功能頁操作返回，核對任務身分與來源保持一致。
- [x] 跨頁停止操作能停止實際任務並保留已提交成果。驗證：對教師、學習與比較分別停止，檢查公開保存結果。
- [x] 已有任務時其他教師、訓練與比較開始入口不能啟動第二項工作。驗證：交叉操作各類入口，包含新建與續跑，確認沒有第二項任務或多餘子程序。
- [x] 互斥限制不縮減單一任務原有並行設定。驗證：沿用可控制外部教師及既有比較派工測試核對實際設定與並行上限。
- [x] 正在使用的同一份資料與研究條件不可修改。驗證：執行中嘗試修改來源條件，確認活動任務快照不變；獨立的新任務草稿可準備。
- [x] 停止及保存尚未完成時任務仍占用執行位置。驗證：延遲保存後操作第二次開始，確認待結束後才開放。
- [x] 任務失敗後有簡短原因與可展開的詳細錯誤。驗證：注入可控制工作失敗，核對已保存進度與目前失敗任務身分。

## 驗證安排

使用真實 UI 事件與既有公開執行入口。外部 UCI、時間及保存故障可控制；不以純狀態物件測試取代跨頁、停止、子程序清理及保存行為。
共通測試與結案規則見[索引](../README.md#驗收與結案規則)及[專案規範](../../../docs/agents/issue-tracker.md)。

## 文件與提交

- [x] 更新受影響操作說明，反映本票實際交付行為。
- [x] 記錄實際驗收證據及限制。
- [x] 同步本票、批次索引與開發計畫的狀態。
- [x] 建立繁體中文 Git commit，讀回核對提交與狀態。

## 人工重現方式（尚未執行）

開始一項小型標記，切到既有成果頁查看，再嘗試開始訓練；確認被擋且顯示目前任務，最後從跨頁進度停止。

## 驗收證據與限制

已以 `..\chess-ai\.venv\Scripts\python.exe -m unittest tests.ui.test_learning_task_navigation tests.ui.test_teacher_labeling tests.ui.test_group_training tests.ui.test_learned_comparison tests.ui.test_teacher_pilot` 驗證 10 項通過。教師先導、教師標記、群組學習與比較的事件測試涵蓋返回、跨頁停止或任務保留；以延遲執行工作確認停止後保存尚未完成時仍阻擋另一項開始。另執行相同命令並加入 `tests.ui.test_chess_application`，60 項通過。追加事件測試驗證教師標記切頁期間完成數增加，以及注入摘要保存失敗後可展開錯誤詳情；教師工作期間各學習與比較開始入口的互斥亦經派發測試。另以 `tests.ui.test_group_training` 確認切頁後群組完成數增加並停止保存；以 `tests.ui.test_learning_task_navigation.TaskNavigationTest.test_short_comparison_keeps_saving_after_leaving_batch_page` 執行合法短對局，確認離開批次頁後繼續保存並跨頁停止。追加教師工作期間檢查一般評分比較開始按鈕、群組工作期間檢查教師及標記開始按鈕；工作完成之前均受阻。既有先導及比較測試確認保留實際 worker 數；延遲執行器測試確認停止後未完成保存前仍受阻。另以真實短比較執行中派發各學習開始入口，確認不產生其他工作；群組工作中嘗試變更已保存教師預算並編輯另一份草稿，逐位元確認原先導狀態與訓練快照不變。功能驗證已完成。人工重現步驟不等於已通過。

審查修正：以實際事件確認工作期間切換另一份資料後返回原來源及任務、群組工作期間進入組合、紀錄頁續跑受互斥限制，以及背景標記失敗時跨頁提示並返回詳情。執行 `tests.ui.test_learning_task_navigation tests.ui.test_teacher_labeling tests.ui.test_group_training tests.ui.test_learned_comparison tests.ui.test_teacher_pilot tests.ui.test_chess_application` 共 61 項通過；審查發現的問題已修正並複審。

複審修正：以三份資料的真實 UI 事件驗證 A 執行、切換 B、A 完成、B 執行再切換 C，仍能返回與停止 B；`tests.ui.test_learning_task_navigation` 5 項通過。

整合分支複跑 ` .\.venv\Scripts\python.exe -m unittest tests.ui.test_learning_task_navigation tests.ui.test_teacher_labeling tests.ui.test_group_training tests.ui.test_learned_comparison tests.ui.test_teacher_pilot tests.ui.test_chess_application`：62 項通過。獨立複審確認先前的互斥、跨頁瀏覽、背景失敗提示與連續跨資料任務問題已修正。未進行正式長實驗；人工重現方式仍僅供操作參考。

- 整合回歸追查：比較恢復頁可排入背景報告讀取，手動執行器若完成最後工作會完成讀取而非比較，狀態仍為停止中。事件測試改為等待原比較 future，確認保存完成後為已停止；跨頁、比較恢復與既有比較回歸 11 項通過。

- 整合分支修正後重跑比較恢復、比較紀錄、跨頁任務、關閉及跨來源整合，共 39 項通過。
