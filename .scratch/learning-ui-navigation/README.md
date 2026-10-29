# 學習實驗導覽與操作改善

狀態：UI01、UI02、UI03、UI04 已完成；其餘工作票待開始，不發布 GitHub Issues。

- [設計規格](spec.md)：已確認 Q1～Q18、頁面結構、驗收情境及現況證據。
- [領域詞彙](../../GLOSSARY.md)：單群組學習、教師作業與比較用途的共同定義。
- [開發計畫](../../docs/開發計畫.md)：目前交付與本批待辦狀態。
- [本機工作票規則](../../docs/agents/issue-tracker.md)：實作、驗收、同步與結案要求。

## 工作票與阻擋

狀態及依賴另列；「無」只代表沒有本批前置票，不表示本輪會開始實作。依賴票完成必要驗收並同步狀態後才解除阻擋。

| 代號 | 工作票 | 狀態 | 直接阻擋 | 可交付的行為 |
| --- | --- | --- | --- | --- |
| UI01 | [載入立即回應並隔離過期結果](issues/01-responsive-loading.md) | 已完成 | 無 | 慢頁面先回應，返回及切換來源不被舊讀取覆蓋 |
| UI02 | [用可讀清單選擇資料與成果並保存顯示名稱](issues/02-result-selection.md) | 已完成 | UI01 | 直接選取、命名並重開正確成果 |
| UI03 | [統一跨頁任務進度與耗時工作互斥](issues/03-task-lifecycle.md) | 已完成 | 無 | 切頁繼續工作且一次只跑一項耗時任務 |
| UI04 | [關閉時停止保存並於重開後手動恢復](issues/04-stop-and-resume.md) | 已完成 | UI02、UI03 | 關閉保存，重開後按實際能力手動恢復 |
| UI05 | [建立目的首頁、固定主入口與可返回的位置路徑](issues/05-navigation.md) | 待開始 | UI01、UI02、UI03 | 直接抵達目的頁並辨識位置、資料階段及缺少前置 |
| UI06 | [合併單群組學習並區分新建、續跑與結果](issues/06-group-learning.md) | 待開始 | UI04、UI05 | 五組選取、新建／續跑分離與學習摘要 |
| UI07 | [跨來源查找候選並相容舊棋子位置成果](issues/07-all-candidates.md) | 待開始 | UI05 | 查找所有來源候選並相容舊棋子位置成果 |
| UI08 | [依比較用途選候選並預覽實際工作量](issues/08-comparison-setup.md) | 待開始 | UI04、UI07 | 選用途、核對候選／基準／總局數並開始比較 |
| UI09 | [直接查找比較紀錄、續跑與查看有依據的結果](issues/09-comparison-results.md) | 待開始 | UI08 | 查找比較紀錄、接續對局、查看結果及回放 |
| UI10 | [完成跨流程與視窗驗收並更新操作文件](issues/10-integration-acceptance.md) | 待開始 | UI06、UI09 | 跨流程、視窗及相關回歸驗收與操作文件更新 |

## 依賴與建議順序

- UI01、UI03 沒有本批前置票。
- UI02 依賴 UI01；UI04 依賴 UI02、UI03。
- UI05 依賴 UI01、UI02、UI03。
- UI06 依賴 UI04、UI05；UI07 依賴 UI05。
- UI08 依賴 UI04、UI07；UI09 依賴 UI08。
- UI10 直接依賴 UI06、UI09，其依賴閉包涵蓋 UI01～UI09。九票必要驗收未完成時，不能以整合票宣稱整批交付。

UI05 先讓現有可操作功能能直接進入；UI06、UI07、UI09 再替換學習內容、擴大候選範圍及接入比較紀錄。UI07 不等待 UI06 的新介面即可讀取既有保存格式。這些界線避免把整批塞進單一導覽票，也避免循環依賴。

## 決策覆蓋

| 規格決策 | 成果 | 責任工作票 |
| --- | --- | --- |
| Q1、Q2、Q15 | 目的首頁、四個主入口、位置路徑與資料階段 | [UI05](issues/05-navigation.md) |
| Q3、Q10、Q11 | 單群組學習、新建與續跑 | [UI06](issues/06-group-learning.md) |
| Q4 | 直接進候選與比較紀錄 | [UI05](issues/05-navigation.md)、[UI07](issues/07-all-candidates.md)、[UI08](issues/08-comparison-setup.md)、[UI09](issues/09-comparison-results.md) |
| Q5 | 立即載入回饋、返回與過期結果隔離 | [UI01](issues/01-responsive-loading.md) |
| Q6 | 成果清單與記住選擇 | [UI02](issues/02-result-selection.md)、[UI09](issues/09-comparison-results.md) |
| Q16 | 自動顯示名稱與改名 | [UI02](issues/02-result-selection.md) |
| Q7 | 跨來源與舊格式候選查找 | [UI07](issues/07-all-candidates.md) |
| Q8 | 前置不足仍可進頁並提供補足入口 | [UI05](issues/05-navigation.md)、[UI08](issues/08-comparison-setup.md) |
| Q9 | 跨頁任務與停止 | [UI03](issues/03-task-lifecycle.md)、[UI05](issues/05-navigation.md)、[UI08](issues/08-comparison-setup.md) |
| Q13 | 耗時工作互斥 | [UI03](issues/03-task-lifecycle.md)、[UI08](issues/08-comparison-setup.md) |
| Q12 | 比較用途、前置及工作量 | [UI08](issues/08-comparison-setup.md) |
| Q14 | 關閉保存與手動續跑 | [UI04](issues/04-stop-and-resume.md)、[UI09](issues/09-comparison-results.md) |
| Q17 | 學習與比較摘要、詳細資訊及下一步 | [UI06](issues/06-group-learning.md)、[UI09](issues/09-comparison-results.md) |
| Q18 | 讀取、選擇與任務失敗的恢復 | [UI01](issues/01-responsive-loading.md)、[UI02](issues/02-result-selection.md)、[UI03](issues/03-task-lifecycle.md)、[UI04](issues/04-stop-and-resume.md)、[UI07](issues/07-all-candidates.md)、[UI09](issues/09-comparison-results.md) |

UI10 稽核 Q1～Q18 的整體覆蓋；功能驗收仍由各責任票完成，不能先結案再等整合票補證據。

## 規格驗收情境對照

下表逐列對應規格的 19 個情境，沒有刪除或降低原驗收要求。

| 情境 | 責任工作票 |
| --- | --- |
| 已有成果，今天只想比較 | [UI05](issues/05-navigation.md)、[UI07](issues/07-all-candidates.md) |
| 從不同入口進同一子頁 | [UI05](issues/05-navigation.md) |
| 昨日完成、今日另有未完成訓練 | [UI02](issues/02-result-selection.md) |
| 不同來源與舊棋子位置成果 | [UI07](issues/07-all-candidates.md) |
| 改名與同名成果 | [UI02](issues/02-result-selection.md) |
| 開啟大量教師標記 | [UI01](issues/01-responsive-loading.md) |
| 載入未完就切換來源 | [UI01](issues/01-responsive-loading.md) |
| 尚未完成教師標記 | [UI05](issues/05-navigation.md) |
| 新建單群組學習 | [UI06](issues/06-group-learning.md) |
| 舊任務續跑及另建 | [UI06](issues/06-group-learning.md) |
| 任務執行中切頁 | [UI03](issues/03-task-lifecycle.md) |
| 執行中啟動另一項任務 | [UI03](issues/03-task-lifecycle.md) |
| 關閉有任務的程式 | [UI04](issues/04-stop-and-resume.md) |
| 重開未完成工作 | [UI04](issues/04-stop-and-resume.md)、[UI09](issues/09-comparison-results.md) |
| 停止教師先導 | [UI04](issues/04-stop-and-resume.md) |
| 比較三個候選 | [UI08](issues/08-comparison-setup.md) |
| 只有教師誤差改善 | [UI06](issues/06-group-learning.md)、[UI09](issues/09-comparison-results.md) |
| 保存資料失效或任務失敗 | [UI01](issues/01-responsive-loading.md)、[UI02](issues/02-result-selection.md)、[UI03](issues/03-task-lifecycle.md)、[UI04](issues/04-stop-and-resume.md)、[UI07](issues/07-all-candidates.md)、[UI09](issues/09-comparison-results.md) |
| 最小視窗及大量清單 | [UI10](issues/10-integration-acceptance.md) |

## 驗收與結案規則

- 每張票的功能驗收與文件／提交分開勾選；功能勾選項附可執行的驗證方式，人工重現步驟不算已執行證據。
- 主要使用實際應用程式事件及公開保存／執行入口，重用現有測試；必要時在外部 UCI、時間、讀檔與保存邊界控制故障。不要測私有呼叫次數、固定文案或把實作照抄成測試。
- 小資料真實求解與合法開局短對局驗證串接；正式 16／128 局規模以實際比較計畫核對，不為 UI 驗收啟動正式長研究或要求使用者提供新資料。
- 程式、依賴及快取沿用專案內環境；保護現有研究資料、候選身分、校準／篩選／對戰規則，不借切票擴張研究能力。
- 每票記錄測試命令、結果、Agent 畫面／操作證據及限制。必要驗收缺漏時維持未勾選並標示待驗收，不讓其他票替它宣稱完成。
- 每票完成時同步票、索引及開發計畫，建立繁體中文提交後讀回核對；只更新實際完成的票，不連帶結案其他項目。

## 本次規劃的核對方式

已建立十票、決策覆蓋及情境對照；規劃檢查只涵蓋文件連結、狀態一致、依賴無循環與範圍覆蓋，不代表任何 UI 功能已實作或驗收。

人工核對：從工作票表開啟任一張票，查看直接阻擋、功能驗收與驗證方式，再對照規格及上方覆蓋表。後續工作依阻擋關係實作。

