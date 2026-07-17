"""RFC 7807-compatible error representation and FastAPI exception handlers."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging.context import get_request_context


class ProblemDetails(BaseModel):
    """A stable public error shape based on RFC 7807 problem details."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    trace_id: str | None = None


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render framework HTTP errors as safe, consistent problem details."""
    http_exception = cast(StarletteHTTPException, exc)
    detail = str(http_exception.detail)
    problem = ProblemDetails(
        title=http_exception.__class__.__name__,
        status=http_exception.status_code,
        detail=detail,
        instance=str(request.url.path),
        trace_id=get_request_context().get("request_id"),
    )
    return JSONResponse(
        content=problem.model_dump(by_alias=True, exclude_none=True),
        status_code=http_exception.status_code,
        media_type="application/problem+json",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Avoid leaking internal exceptions while returning a traceable problem response."""
    problem = ProblemDetails(
        title="Internal Server Error",
        status=500,
        detail="An unexpected server error occurred.",
        instance=str(request.url.path),
        trace_id=get_request_context().get("request_id"),
    )
    return JSONResponse(
        content=problem.model_dump(exclude_none=True),
        status_code=500,
        media_type="application/problem+json",
    )
