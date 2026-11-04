"""建立只接受本機連線的 FastAPI 應用程式，並提供 Angular 建置產物。"""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.home import HomeCache
from api.jobs import JobService
from engine.evaluation.config import EvaluationConfig
from engine.sessions.heavy_job import DEFAULT_LOCK_PATH, HeavyJobBusy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC_DIR = ROOT / 'web' / 'dist' / 'web' / 'browser'
LOOPBACK_HOSTS = {'127.0.0.1', '::1'}
EVENT_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15

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


class GeneralBatchRequest(BaseModel):
    white: str = 'Random'
    black: str = 'Greedy'
    white_config: str | None = None
    black_config: str | None = None
    games: int = Field(20, ge=1)
    workers: int = Field(1, ge=1)
    interval: float = Field(0.0, ge=0)
    max_plies: int | None = Field(None, ge=0)
    claim_draw: bool = False
    search_depth: int = Field(2, ge=1)
    search_workers: int = Field(1, ge=1)
    transposition_capacity: int = Field(4096, ge=1)
    opening_book: bool = False
    opening_max_plies: int = Field(12, ge=0)
    base_seed: int | None = Field(None, ge=0)


def _evaluation(project_root, strategy, name):
    if strategy == 'Random':
        return None
    if not name:
        return EvaluationConfig()
    folder = (Path(project_root) / 'configs' / 'evaluation').resolve()
    path = (folder / name).resolve()
    if path.parent != folder or path.suffix != '.json' or not path.is_file():
        raise ValueError(f'找不到評分設定檔：{name}')
    return EvaluationConfig.from_dict(json.loads(path.read_text(encoding='utf-8')))


async def job_events(jobs, request=None, *, interval=EVENT_INTERVAL, limit=None):
    """SSE：連線後先送完整快照，之後狀態有變才再送；定期送心跳。"""
    last, sent, idle = None, 0, 0.0
    while limit is None or sent < limit:
        if request is not None and await request.is_disconnected():
            return
        current = jobs.snapshots()
        if current != last:
            last = current
            sent += 1
            idle = 0.0
            yield f'event: jobs\ndata: {json.dumps(current, ensure_ascii=False)}\n\n'
            continue
        if idle >= HEARTBEAT_SECONDS:
            idle = 0.0
            yield ': heartbeat\n\n'
        await asyncio.sleep(interval)
        idle += interval


def _busy_response(exc):
    return JSONResponse({'detail': str(exc), 'owner': exc.owner}, status_code=409)


def create_app(static_dir=DEFAULT_STATIC_DIR, *, data_root=None, project_root=ROOT,
               lock_path=DEFAULT_LOCK_PATH, scan_on_start=True):
    static_dir = Path(static_dir)
    project_root = Path(project_root)
    data_root = Path(data_root) if data_root is not None else project_root / 'data'
    jobs = JobService(lock_path=lock_path)
    home = HomeCache(jobs.reads, data_root=data_root, project_root=project_root)
    jobs.on_finished(lambda _: home.refresh())

    @asynccontextmanager
    async def lifespan(_):
        if scan_on_start:
            home.refresh()
        try:
            yield
        finally:
            # 關閉伺服器時停止工作並等待已完成局保存。
            await asyncio.to_thread(jobs.shutdown)

    app = FastAPI(title='Chess AI', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.jobs = jobs
    app.state.home = home

    @app.middleware('http')
    async def reject_remote_clients(request: Request, call_next):
        host = request.client.host if request.client else None
        if host not in LOOPBACK_HOSTS:
            return JSONResponse({'detail': '只接受本機連線'}, status_code=403)
        return await call_next(request)

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/home')
    def home_state():
        return dict(home.snapshot(), running=jobs.running())

    @app.post('/api/home/refresh')
    def home_refresh():
        home.refresh()
        return home.snapshot()

    @app.get('/api/jobs')
    def list_jobs():
        return jobs.snapshots()

    @app.get('/api/jobs/events')
    async def events(request: Request):
        return StreamingResponse(job_events(jobs, request), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache'})

    @app.post('/api/jobs/{job_id}/{action}')
    def control_job(job_id: str, action: str):
        try:
            return jobs.control(job_id, action)
        except KeyError:
            raise HTTPException(404, '找不到工作') from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post('/api/batches/general', status_code=201)
    def start_general_batch(body: GeneralBatchRequest):
        from engine.sessions.batch_run import BatchRun, BatchSettings
        try:
            settings = BatchSettings(
                white=body.white, black=body.black, games=body.games, workers=body.workers,
                interval=body.interval, max_plies=body.max_plies, claim_draw=body.claim_draw,
                search_depth=body.search_depth, search_workers=body.search_workers,
                transposition_capacity=body.transposition_capacity, opening_book=body.opening_book,
                opening_max_plies=body.opening_max_plies, base_seed=body.base_seed,
                white_evaluation=_evaluation(project_root, body.white, body.white_config),
                black_evaluation=_evaluation(project_root, body.black, body.black_config))
            job = jobs.start('general_batch', f'一般批次 {body.white} 對 {body.black}・{body.games} 局', '/batch',
                             lambda executor: BatchRun(settings, data_root / 'batches', executor))
        except HeavyJobBusy as exc:
            return _busy_response(exc)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(400, str(exc)) from None
        return job.snapshot()

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
