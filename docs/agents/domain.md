# Domain 文件

工程技能探索程式碼前，請依下列規則讀取本專案的 domain 文件。

## 探索前讀取

- 若根目錄有 `GLOSSARY.md`，請讀取。
- 若根目錄有 `GLOSSARY-MAP.md`，請依 map 讀取與工作主題相關的各 context glossary。
- 讀取與工作範圍相關的 `docs/adr/` 決策紀錄。

文件不存在時，直接繼續，不需特別提醒或預先建議建立。當詞彙或決策確定後，再由 domain-modeling skill 建立所需文件。

## 單一脈絡配置

本專案採用根目錄單一脈絡配置：`GLOSSARY.md` 放在根目錄，ADR 放在 `docs/adr/`。

## 使用 glossary 詞彙

在 issue 標題、重構提案、假設或測試名稱中提及 domain 概念時，請使用 glossary 定義的詞彙，避免改用 glossary 明確排除的同義詞。若需要的概念尚未收錄，請留意是否需要由 domain-modeling skill 補足。

## 標示 ADR 衝突

若產出與既有 ADR 衝突，請明確指出衝突的 ADR，不要默默忽略或覆寫。
