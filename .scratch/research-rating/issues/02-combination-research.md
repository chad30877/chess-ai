# 02：補齊組合學習並保存續跑

## 上層規格

[組合研究與設定棋力分數](../spec.md)。

狀態：已完成。

## 要交付的行為

研究者可選擇需要補齊的多群組組合，產生並保存直接組合和聯合訓練，停止後重開續跑，並可看見資料及測試曝光。

## 驗收條件

- [x] 使用同源的五個單群組，可建立 26 種多群組組合的直接與聯合結果；以可控資料核對完整覆蓋及來源相容性。
- [x] 直接組合保留各單組凍結權重，聯合訓練沿用既有共同校準、非負權重與驗證挑選；以公開結果核對兩種設定及來源。
- [x] 停止或整次八小時期限到達時保留已完成結果，重新開啟只補未完成項，且不自動接續下一次八小時；以可控時鐘及重開驗證。
- [x] 既有相容結果可沿用而不覆寫，舊測試資料曝光及不相容來源可辨識；以保存、重開與拒絕情境驗證。

## 阻擋

無，可立即開始。

## 驗收證據與限制

- `CombinationBatchFlowTest.test_all_26_combinations_produce_same_source_direct_and_joint_results` 使用可控教師資料、真實群組訓練與公開批次入口，實際完成 26 組；逐組核對直接權重、共同校準、非負求解、驗證選擇、曝光標示及重開不覆寫。
- `CombinationFlowTest` 以真實保存與求解核對凍結權重、來源不相容拒絕、使用者停止、期限到達、已完成結果保留及續跑。`CombinationBatchFlowTest.test_reuses_completed_combination_and_resumes_after_shared_deadline` 以可控時鐘核對整批期限、既有結果重用與手動續跑。
- `CombinationUiTest.test_batch_selection_runs_and_reopens_through_application_events` 透過應用程式事件選擇組合、啟動並重開批次。自動測試未執行正式資料、真實八小時或正式長研究；人工操作步驟不視為已執行驗收。
