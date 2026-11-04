# 網頁介面前端

Angular 22 與 Angular Material。啟動與建置步驟見[專案總覽](../README.md#網頁介面)。

## 開發

先在專案根目錄啟動 API 伺服器（`.venv\Scripts\python.exe -m apps.web --no-browser`），再於本目錄執行：

```cmd
npm start
```

開啟 `http://localhost:4200/`；`/api` 請求經 `proxy.conf.json` 轉到 `127.0.0.1:8642`。

## 測試

```cmd
npx ng test --watch=false
```

npm 快取設定於 `.npmrc`，放在專案根目錄的 `.cache/npm`。
