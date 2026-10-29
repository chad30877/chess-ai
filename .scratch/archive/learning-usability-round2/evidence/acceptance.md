# 驗收紀錄

本批依使用者核准的簡化規格實作。UI 驗證使用實際 Pygame 應用程式事件與原生畫面；沒有以瀏覽器替代桌面應用。

## 功能與實測

- 資料：選檔取消保留路徑，來源與毫秒種子跨重開保存；錯誤訊息與舊資料摘要分行。
- 教師：同頁估時及節點預算、同條件重用、明確重新評分、標記命名與來源選擇。真實 Stockfish 完成 24／24 個局面，重用成功，5.68 秒，見 [紀錄](real-teacher.json)。沒有啟動正式長作業。
- 工作：另一教師工作執行中可以學習已完成標記；切換來源會保留完整背景工作上下文，關閉停止並保存全部工作。回歸過程找到並修正「切換量測紀錄改寫背景標記來源」問題。
- 候選：預設／自訂／已凍結學習設定統一列出，無報告仍可比較；顯示名稱不改 config 位元組或來源身分。按需驗證詳細來源，損壞來源不能送入比較。
- 排序：棋力使用共同基準、搜尋與開局條件；MAE 使用相同資料、標記與校準；取最新有效結果，缺值排最後。暫估與正式分開標示。
- 本機資料量測：原清單 66 筆、11.528 秒；新清單 87 筆、0.471 秒。筆數增加來自自訂與預設設定，並非相同覆蓋範圍的純算法基準；測試另監測首屏不讀 inputs.json 或 comparison.json。

## 畫面

檢查 900×768 與 1280×960 的資料、教師、候選六張截圖，未見文字重疊或按鈕互擋：

- [資料 900](data-900.png)、[資料 1280](data-1280.png)
- [教師 900](teacher-900.png)、[教師 1280](teacher-1280.png)
- [候選 900](inventory-900.png)、[候選 1280](inventory-1280.png)

## 自動測試

使用專案 `.venv\Scripts\python.exe -m unittest` 執行以下模組；舊介面測試改走新入口，保留原有保存、來源驗證、程序清理與續跑斷言。舊棋子位置頁的操作測試改為「入口消失、保存資料未變、統一候選可比較」。

- `tests.ui.test_learning_loading`：13 項通過。
- `tests.ui.test_learning_integration tests.ui.test_comparison_setup tests.test_all_candidates`：14 項通過。
- `tests.ui.test_labeling_estimates tests.ui.test_learning_navigation tests.ui.test_learning_task_navigation tests.ui.test_teacher_labeling tests.test_config_catalog`：14 項通過。
- 兩項來源切換回歸加 `tests.ui.test_learning_usability tests.ui.test_learning_close`：25 項通過，包含真實教師及求解子程序退出。
- `tests.ui.test_saved_selection tests.ui.test_combination_training tests.ui.test_group_training tests.ui.test_weight_training tests.ui.test_group_draft`：23 項完成驗證；初次有兩項上下文錯誤及一項舊資料測試路徑錯誤，修正後失敗項分別重跑通過。
- `tests.ui.test_saved_selection tests.ui.test_learning_usability tests.ui.test_teacher_pilot`：最終 21 項整組重跑通過。
- `tests.ui.test_teacher_pilot tests.ui.test_teacher_picker tests.ui.test_chess_application tests.ui.test_comparison_history tests.ui.test_comparison_recovery`：68 項中 65 項首跑通過；兩項量測測試的舊資料頁入口已更新並於上述 21 項中通過，未評估標示測試改為先選棋力排序後重跑通過。
- `git diff --check` 與 `compileall` 通過；未宣稱執行全專案測試。

## 人工重現方式

1. 執行 `.venv\Scripts\python.exe -m apps.play_ui`，進入學習實驗。資料準備切本機、選檔、按隨機；重開核對路徑與種子。
2. 教師評分選擇既有評分或量測預算。同條件按「使用既有／開始評分」應重用；只有「重新評分」產生另一份，可改名。
3. 評分權重學習選完成教師評分；另一工作仍在跑時應可選既有資料。返回任務核對來源，停止或關閉可保存。
4. 比較候選搜尋、切方式與群組、選棋力或驗證誤差及評估來源；勾選一筆改名，重開名稱仍在。未評估設定也可進入比較用途。

以上人工步驟為交付後重現說明，不冒充使用者已確認。未執行正式長研究、全量新對戰或棋力提升驗證。
