"""Domain errors and the handlers that turn them into HTTP responses.

Every error body has the shape {"detail": ...}. Messages are written for
the API caller and never include SQL, stack traces, or connection strings.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger("orderflow")


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class UnprocessableError(DomainError):
    status_code = 422


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, _: IntegrityError) -> JSONResponse:
        logger.warning(
            "Integrity error request_id=%s path=%s",
            getattr(request.state, "request_id", "-"),
            request.url.path,
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "The request conflicts with existing data."},
        )

    @app.exception_handler(OperationalError)
    async def handle_operational_error(
        request: Request, _: OperationalError
    ) -> JSONResponse:
        logger.error(
            "Database unavailable request_id=%s path=%s",
            getattr(request.state, "request_id", "-"),
            request.url.path,
        )
        return JSONResponse(status_code=503, content={"detail": "Database unavailable."})
