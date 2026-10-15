# 測試說明

- `search/test_transposition.py`：置換表容量、深度／界限／世代保留偏好、小容量將死搜尋、歷史鍵值與每次搜尋失效。
- `self_play/test_alphabeta_comparison.py`：完整比較流程的共同搜尋條件、容量保存、配對及舊紀錄相容。

- `search/test_parallel_search.py`：真實 spawn 的將死距離、完整重複歷史、取消／逾時、程序故障與清理。
- `ui/test_live_session.py`：真人對局背景搜尋停止與舊結果隔離。
- `ui/test_chess_application.py`：輸入搜尋 worker 後執行 AI 落子，並保存實際條件。

完整測試方式與其他檔案見 [測試導覽](README.md)。
