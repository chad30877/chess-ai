# 網頁介面

狀態：W01 已完成；W02 程式實作完成，待使用者驗收；其餘待實作。不發布 GitHub Issues。

- [設計規格](spec.md)
- [訪談紀錄](../../docs/design/web-ui.md)
- [領域詞彙](../../GLOSSARY.md)
- [本機工作票規則](../../docs/agents/issue-tracker.md)

## 工作票與阻擋

依賴票完成必要驗收並同步狀態後才解除阻擋。

| 代號 | 工作票 | 狀態 | 直接阻擋 | 實作 |
| --- | --- | --- | --- | --- |
| W01 | [伺服器骨架、啟動入口與側欄外殼](issues/01-server-shell.md) | 已完成 | 無 | Claude |
| W02 | [設計規範與 Material 主題](issues/02-design-system.md) | 待使用者驗收 | W01 | Claude、使用者 |
| W03 | [伺服器工作服務、全機工作鎖、工作列與首頁](issues/03-job-service.md) | 待實作 | W01 | Claude |
| W04 | [網頁選檔對話框](issues/04-file-dialog.md) | 待實作 | W01 | Claude |
| W05 | [對局紀錄清單與設定檢視](issues/05-records.md) | 待實作 | W02、W03 | Codex |
| W06 | [回放與局面評分拆解](issues/06-replay.md) | 待實作 | W05 | Codex |
| W07 | [回放評分草稿編輯與另存設定](issues/07-evaluation-draft.md) | 待實作 | W06 | Codex |
| W08 | [真人對 AI](issues/08-live-game.md) | 待實作 | W03、W06 | Codex |
| W09 | [一般批次對戰](issues/09-general-batch.md) | 待實作 | W03 | Codex |
| W10 | [評分比較、權重實驗與續跑](issues/10-evaluation-comparison.md) | 待實作 | W09、W04 | Codex |
| W11 | [研究頁原型與使用者確認](issues/11-research-prototype.md) | 待實作 | W02 | Claude、使用者 |
| W12 | [研究頁骨架、資料步驟與資料清單](issues/12-research-data.md) | 待實作 | W03、W11 | Codex |
| W13 | [教師先導、教師標記步驟與教師評分清單](issues/13-research-teacher.md) | 待實作 | W12、W04 | Codex |
| W14 | [權重學習步驟](issues/14-research-learning.md) | 待實作 | W13 | Codex |
| W15 | [候選清單、對 stable 比較與比較紀錄](issues/15-candidates-stable.md) | 待實作 | W12、W03 | Codex |
| W16 | [移除 pygame 與端到端驗收](issues/16-remove-pygame.md) | 待實作 | W05、W06、W07、W08、W09、W10、W12、W13、W14、W15 | Codex |

## 階段與順序

- 第 1 階段 W01～W04 由 Claude 實作，定下 API、SSE、工作鎖、Angular 結構與主題的寫法；W02、W11 需要使用者確認。
- W05 起交由 Codex 實作、Claude 審查；每次呼叫記錄於 [codex-log.md](codex-log.md)。
- 可平行的前沿：W01 完成後 W02、W03、W04 可平行；W02、W03 完成後紀錄（W05→W06→W07）、批次（W09→W10）與研究（W11→W12→…）三條線可平行；W08 需 W03、W06。
- W16 移除 pygame，阻擋於所有畫面票；搬家期間 pygame 照常可用並共用全機工作鎖。

## 驗收與結案規則

每張畫面票交付 API 測試、1280 與 900 寬度截圖及 design-critique 結論；engine 既有測試須持續通過。共通規則見[專案規範](../../docs/agents/issue-tracker.md)。
