"""建立只接受本機連線的 FastAPI 應用程式，並提供 Angular 建置產物。"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC_DIR = ROOT / 'web' / 'dist' / 'web' / 'browser'
LOOPBACK_HOSTS = {'127.0.0.1', '::1'}

BUILD_MISSING_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>Chess AI</title></head>
<body style="font-family: sans-serif; max-width: 40rem; margin: 4rem auto; line-height: 1.6">
<h1>尚未建置網頁介面</h1>
<p>請在專案根目錄執行以下指令後重新整理此頁：</p>
<pre>cd web
npm install
npm run build</pre>
</body>
</html>
"""


def create_app(static_dir=DEFAULT_STATIC_DIR):
    static_dir = Path(static_dir)
    app = FastAPI(title='Chess AI', docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def reject_remote_clients(request: Request, call_next):
        host = request.client.host if request.client else None
        if host not in LOOPBACK_HOSTS:
            return JSONResponse({'detail': '只接受本機連線'}, status_code=403)
        return await call_next(request)

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/{path:path}', include_in_schema=False)
    def unknown_api(path: str):
        return JSONResponse({'detail': '找不到 API'}, status_code=404)

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        index = static_dir / 'index.html'
        if not index.is_file():
            return HTMLResponse(BUILD_MISSING_PAGE, status_code=503)
        target = (static_dir / path).resolve()
        if path and target.is_file() and target.is_relative_to(static_dir.resolve()):
            return FileResponse(target)
        # 其餘路徑交給 Angular 路由。
        return FileResponse(index)

    return app
