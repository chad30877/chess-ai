# 組合研究與設定棋力分數

狀態：規格及七張工作票已發布 GitHub，均開啟且待實作；驗收狀態以 GitHub 為準。

[規格 #40](https://github.com/chad30877/chess-ai/issues/40)（[本機副本](spec.md)）以既有學習及比較流程為基礎，不自動開始尚未選擇的對局。[發布索引](publication.json)保存編號、阻擋關係及發布時雜湊。

| 工作票 | 本機副本 | 阻擋 |
| --- | --- | --- |
| [#41](https://github.com/chad30877/chess-ai/issues/41) | [盤點組合並展示十個候選](issues/01-candidate-inventory.md) | 無 |
| [#42](https://github.com/chad30877/chess-ai/issues/42) | [補齊組合學習並保存續跑](issues/02-combination-research.md) | 無 |
| [#43](https://github.com/chad30877/chess-ai/issues/43) | [從完整對局計算設定棋力分數](issues/03-rating-report.md) | 無 |
| [#44](https://github.com/chad30877/chess-ai/issues/44) | [在設定選擇處查看棋力分數](issues/04-profile-rating.md) | #43 |
| [#45](https://github.com/chad30877/chess-ai/issues/45) | [選定候選並執行短對局篩選](issues/05-screening.md) | #41 |
| [#46](https://github.com/chad30877/chess-ai/issues/46) | [對選定候選完成雙基準比較](issues/06-final-comparison.md) | #45 |
| [#47](https://github.com/chad30877/chess-ai/issues/47) | [以未曝光資料評估凍結候選](issues/07-heldout-evaluation.md) | #46 |
