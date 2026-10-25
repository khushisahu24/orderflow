from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Liveness: the API process is running. Does not touch the database."""
    return {"status": "ok", "service": "orderflow"}


@router.get("/version")
def get_version() -> dict[str, str]:
    return {"name": "OrderFlow", "version": __version__}


@router.get("/ready", responses={503: {"description": "Database unreachable"}})
def readiness_check(request: Request) -> JSONResponse:
    """Readiness: the API can reach PostgreSQL."""
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "database": "unreachable"}
        )
    return JSONResponse(status_code=200, content={"status": "ready", "database": "ok"})
