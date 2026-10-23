---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

開始時讀取專案的 issue tracker 文件，依其對照將本機工作票定位到正式 issue，核對最新驗收與阻擋關係；本機檔名不表示使用本機 tracker。

Call the Skill tool with "tdd" where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, call the Skill tool with "code-review" to review the work.

Commit your work to the current branch.

依專案 tracker 文件完成必要驗證、GitHub／本機同步、結案與讀回檢查，再回覆完成。此專案提供結案命令，正常情況直接執行收尾，不另等使用者逐票人工展示或再次授權關票。只有明訂且確實無法由 Agent 完成的必要驗收，或修復後仍存在的實際錯誤，才保留開啟並說明阻礙。最終回覆須包含正式 issue 狀態；提交成功不等於工作票已結案。
