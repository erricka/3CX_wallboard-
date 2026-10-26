import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .config import Settings, get_settings
from .db import init_db, make_engine, make_sessionmaker
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
        await init_db(engine)
        threecx = client or ThreeCXClient(settings.threecx_base_url, settings.threecx_client_id,
                                          settings.threecx_client_secret, settings.threecx_verify_ssl)
        service = WallboardService(settings, threecx, make_sessionmaker(engine))
        await service.start()
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
        days = period_days(period, settings.tz)
        warnings = await service.ensure_synced(days)
        async with service.sessionmaker() as session:
            data = await load_report(session, period, days, settings.tz, settings.queue_filter,
                                     settings.slow_answer_seconds, utcnow())
        data.warnings = warnings
        body = to_xlsx(data) if format == "xlsx" else to_csv(data)
        return Response(body, media_type=FORMATS[format], headers={
            "Content-Disposition": f'attachment; filename="{data.filename_stem}.{format}"'})

    return app
