"""OrderFlow API entry point.

`create_app` builds one application from a `Settings` object. Uvicorn
imports the module-level `app`, which reads settings from the environment.
Tests call `create_app(settings)` with a test database.
"""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.errors import register_error_handlers
from app.routers import auth, customers, health, orders, products
from app.security import hash_password

logger = logging.getLogger("orderflow")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="OrderFlow",
        summary="Manages customers, products, inventory, and orders.",
        version=__version__,
    )
    engine = build_engine(settings.database_url, settings.db_connect_timeout_seconds)
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = build_session_factory(engine)
    application.state.dummy_password_hash = hash_password(
        "not-a-real-password", settings.bcrypt_rounds
    )

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled error request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            response = JSONResponse(
                status_code=500, content={"detail": "Internal server error."}
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    register_error_handlers(application)
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(customers.router)
    application.include_router(products.router)
    application.include_router(orders.router)
    return application


def __getattr__(name: str) -> FastAPI:
    """Build the default app lazily, so importing `app.main` in tests does
    not require production environment variables."""
    if name == "app":
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(name)
