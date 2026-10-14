# Issue tracker：GitHub

本專案的 issue 和規格使用 GitHub Issues 管理，所有操作使用 `gh` CLI。

## 慣例

- 建立 issue：`gh issue create --title "..." --body "..."`；多行內容請使用 heredoc。
- 讀取 issue：`gh issue view <number> --json number,title,body,labels,comments`。
- 列出 issue：使用 `gh issue list --state open --json number,title,body,labels,comments`，並依需求加上 `--label`、`--state` 等篩選條件。
- 將 issue 設為另一個 issue 的子項：使用 `gh issue create --parent <parent>`，或事後執行 `gh issue edit <parent> --add-sub-issue <child>`（需 gh 2.94 以上）。若不支援子項，請在子 issue 內文開頭加入 `Part of #<parent>`。
- 留言：`gh issue comment <number> --body "..."`。
- 新增或移除標籤：`gh issue edit <number> --add-label "..."` 或 `--remove-label "..."`。
- 關閉 issue：`gh issue close <number> --comment "..."`。

`gh` 會從目前 clone 的 Git remote 判斷 repository。

## Pull request 作為需求入口

**PR 作為需求入口：否。** 若本專案日後將外部 PR 納入需求分流，可將此值改為 `是`。

## 技能操作對照

- 「發布到 issue tracker」：建立 GitHub issue。
- 「取得相關 ticket」：依上述方式讀取 GitHub issue。
