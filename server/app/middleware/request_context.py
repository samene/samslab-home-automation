"""Request-ID, correlation-ID, timing, request logging, and exception logging middleware."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.logging.context import bind_request_context, clear_request_context

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach request context and emit a single structured event for every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process one request while guaranteeing context cleanup on every path."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id
        bind_request_context(request_id=request_id, correlation_id=correlation_id)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        logger = structlog.get_logger("http.request")
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
            )
            raise
        else:
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
            )
            return response
        finally:
            clear_request_context()
