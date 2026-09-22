"""FastAPI application: middleware, error mapping, health checks and routers."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from gtmos import __version__
from gtmos.api.routes import accounts, crm, integrations, ops
from gtmos.config import get_settings
from gtmos.db import get_engine
from gtmos.services.common import (
    Conflict,
    NotFound,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from gtmos.services.signal_service import InvalidSignal

log = logging.getLogger("gtmos.api")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(
        title="GTMOS API",
        version=__version__,
        description="AI-native revenue engine: explainable scoring, enrichment waterfalls, signals, routing, "
        "workflows, CRM sync and GTM analytics. DEMO data is labeled via `data_origin`.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # explicit allow-list, never "*"
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-GTMOS-Actor", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id", "")
        cid = incoming if incoming.isalnum() and len(incoming) <= 64 else new_correlation_id()
        token = set_correlation_id(cid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-ID"] = cid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/health"):
            log.info("%s %s %s %.0fms cid=%s", request.method, request.url.path, response.status_code, ms, cid)
        return response

    def err(status: int, message: str, request: Request) -> JSONResponse:
        return JSONResponse({"error": message, "request_id": request.headers.get("x-request-id")}, status_code=status)

    @app.exception_handler(NotFound)
    async def _nf(request: Request, exc: NotFound) -> JSONResponse:
        return err(404, str(exc), request)

    @app.exception_handler(Conflict)
    async def _cf(request: Request, exc: Conflict) -> JSONResponse:
        return err(409, str(exc), request)

    @app.exception_handler(InvalidSignal)
    async def _is(request: Request, exc: InvalidSignal) -> JSONResponse:
        return err(422, str(exc), request)

    @app.exception_handler(IntegrityError)
    async def _ie(request: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error: %s", exc.orig)
        return err(409, "conflicting write (duplicate or stale reference)", request)

    @app.exception_handler(RequestValidationError)
    async def _ve(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": "validation failed",
                "details": [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()],
            },
            status_code=422,
        )

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready() -> dict[str, Any]:
        checks: dict[str, str] = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception as exc:  # health endpoints report, never raise
            checks["database"] = f"error: {exc.__class__.__name__}"
        if settings.redis_url:
            try:
                from redis import Redis

                Redis.from_url(settings.redis_url, socket_timeout=1).ping()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = f"error: {exc.__class__.__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "checks": checks, "version": __version__},
            status_code=200 if ok else 503,
        )  # type: ignore[return-value]

    for r in (accounts.router, crm.router, ops.router, integrations.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
