import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .db import init_db, make_engine, make_sessionmaker
from .diagnostics import run_checks
from .reports import load_report, to_csv, to_xlsx
from .service import WallboardService
from .threecx import ThreeCXClient
from .timeutil import PERIODS, Period, period_days, utcnow

FORMATS = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}


def create_app(settings: Settings | None = None, client: ThreeCXClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        threecx = client or ThreeCXClient(settings.threecx_base_url, settings.threecx_client_id,
                                          settings.threecx_client_secret, settings.threecx_verify_ssl)
        service = WallboardService(settings, threecx, make_sessionmaker(engine))
        service.start(prepare_db=lambda: init_db(engine))
        app.state.service = service
        yield
        await service.stop()
        await threecx.close()
        await engine.dispose()

    app = FastAPI(title="3CX Wallboard", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_methods=["GET"], allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.get("/api/health")
    async def health(request: Request):
        snapshot = request.app.state.service.snapshot or {}
        return {"ok": not snapshot.get("stale", False), "last_update": snapshot.get("generated_at")}

    @app.get("/api/wallboard")
    async def wallboard(request: Request):
        snapshot = request.app.state.service.snapshot
        if snapshot is None:
            raise HTTPException(503, "Waiting for first data from 3CX")
        return snapshot

    @app.websocket("/ws/wallboard")
    async def wallboard_ws(websocket: WebSocket):
        await websocket.accept()
        service: WallboardService = websocket.app.state.service
        updates = service.subscribe()
        try:
            if service.snapshot:
                await websocket.send_json(service.snapshot)
            while True:
                await websocket.send_json(await updates.get())
        except WebSocketDisconnect:
            pass
        finally:
            service.unsubscribe(updates)

    @app.get("/api/reports/periods")
    async def report_periods():
        return [{"value": k, "label": v} for k, v in PERIODS.items()]

    @app.get("/api/reports/daily")
    async def daily_report(request: Request, period: Period = "today", format: Literal["xlsx", "csv"] = "xlsx"):
        service: WallboardService = request.app.state.service
        if not service.db_ready:
            raise HTTPException(503, "The PostgreSQL database is not ready yet")
        days = period_days(period, settings.tz)
        warnings = await service.ensure_synced(days)
        async with service.sessionmaker() as session:
            data = await load_report(session, period, days, settings.tz, settings.queue_filter,
                                     settings.slow_answer_seconds, utcnow())
        data.warnings = warnings
        body = to_xlsx(data) if format == "xlsx" else to_csv(data)
        return Response(body, media_type=FORMATS[format], headers={
            "Content-Disposition": f'attachment; filename="{data.filename_stem}.{format}"'})

    @app.get("/api/diagnostics")
    async def diagnostics(request: Request):
        """Which 3CX endpoints work on this PBX (field names only, no call data)."""
        results, _ = await run_checks(request.app.state.service.client, settings)
        return {"threecx": settings.threecx_base_url, "all_ok": all(r["ok"] for r in results), "checks": results}

    if settings.static_dir:
        if (Path(settings.static_dir) / "index.html").exists():
            app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
        else:
            logging.getLogger(__name__).warning("No built frontend in %s; serving the API only", settings.static_dir)

    return app
