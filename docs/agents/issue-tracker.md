# Issue tracker：GitHub

本專案的 issue 和規格使用 GitHub Issues 管理，所有操作使用 `gh` CLI。

## 慣例

- 建立 issue：`gh issue create --title "..." --body-file <檔案>`；多行內容先存檔，再傳 `--body-file`。
- 讀取 issue：`gh issue view <number> --json number,title,body,labels,comments`。
- 列出 issue：使用 `gh issue list --state open --json number,title,body,labels,comments`，並依需求加上 `--label`、`--state` 等篩選條件。
- 將 issue 設為另一個 issue 的子項：使用 `gh issue create --parent <parent>`，或事後執行 `gh issue edit <parent> --add-sub-issue <child>`（需 gh 2.94 以上）。若不支援子項，請在子 issue 內文開頭加入 `Part of #<parent>`。
- 留言：`gh issue comment <number> --body "..."`。
- 新增或移除標籤：`gh issue edit <number> --add-label "..."` 或 `--remove-label "..."`。
- 關閉 issue：`gh issue close <number> --comment "..."`。

`gh` 會從目前 clone 的 Git remote 判斷 repository。

## 工作票定位與驗收

開始實作或審查時，將使用者提供的編號、標題或本機檔名解析到 GitHub issue，讀取最新內文、留言與阻擋關係。若提供 `.scratch` 檔名，先查同批 `publication.json` 的編號對照；只有確實有多個相符結果才詢問使用者。發布索引內的雜湊與驗證結果是發布當時的紀錄，不代表目前完成狀態。

每條驗收依實際證據判定。自動測試、Agent 實際操作、使用者確認是不同證據，需如實記錄；只提供操作步驟不等於已執行。能由 Agent 完成的必要驗證應在本次完成；確實需要使用者操作或主觀確認時，列出具體未完成項並保留 issue 開啟。

切票時，一個勾選項只放一個可判定的成果，寫明驗證方式。文件／提交與功能驗收分開。優先採可執行的自動或 Agent 操作驗證；只有需要使用者參與的項目才列為必要人工驗收。供使用者重現的「人工測試方式」放在說明區，不自行提升為必須等待使用者的驗收條件。已核准的必要驗收須完成，或取得明確範圍變更後更新，不能為了結案默默降格。

## 結案流程

1. 對照最新工作票完成必要實作、測試與審查，逐條補上證據。仍有必要驗收未完成時，回報「實作完成、待驗收」，保留未勾選及開啟狀態；不得宣稱整票完成。
2. 同步 GitHub 與對應本機票的驗收勾選、證據及限制，更新批次索引和開發計畫的目前狀態；完成程式與文件提交。不要用改寫發布雜湊來宣稱重新驗證。
3. 具備本專案新版發布索引的工作票，執行結案前檢查：`python scripts/check_ticket_completion.py --manifest .scratch/ml-small-trial/publication.json --issue <編號> --phase before-close`。其他批次替換索引路徑；不支援的舊格式需明確回報並人工核對，不能當作通過。
4. 必要驗收全部完成且使用者已授權完成該票時，使用 `gh` 關閉該工作票並讀回狀態。同步本機票、批次索引與開發計畫的結案狀態，提交收尾更新；不連帶關閉父規格或其他工作票。
5. 用相同命令改為 `--phase after-close`，確認 GitHub 已關閉且兩邊驗收一致。最終回覆附 issue 編號／狀態、提交、驗證與未完成項；外部操作失敗時回報「結案同步未完成」，保留可恢復的進度，不冒稱成功。

工具是唯讀檢查，不會補勾、評論、關閉或重新開啟 issue，也無法證明人工操作真的發生。省略 `--phase` 時只稽核索引內已關閉的工作票；開啟且未完成是合法狀態。退出碼 0 表示狀態檢查通過、1 表示驗收／同步矛盾、2 表示無法核對，三者不可混用。

相關 PR 的 CI 會執行檢查器回歸與 ML 批次已關閉票的稽核；也可手動執行 workflow。CI 需在 workflow 提交到 GitHub 後才可用，不取代本機結案前／後檢查，不會阻止 GitHub 使用者手動關票。

## Pull request 作為需求入口

**PR 作為需求入口：否。** 若本專案日後將外部 PR 納入需求分流，可將此值改為 `是`。

## 技能操作對照

- 「發布到 issue tracker」：建立 GitHub issue。
- 「取得相關 ticket」：依上述方式讀取 GitHub issue。
