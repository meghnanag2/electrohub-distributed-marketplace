import sys
import time
import uuid
import logging

import structlog
from fastapi import Request
from fastapi.responses import Response


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def request_logging_middleware(request: Request, call_next) -> Response:
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.core.security import decode_access_token
            user_id = decode_access_token(auth[7:])
            if user_id:
                structlog.contextvars.bind_contextvars(user_id=user_id)
        except Exception:
            pass

    log = structlog.get_logger()
    log.info("request_started")
    t0 = time.perf_counter()
    response = await call_next(request)
    log.info("request_completed",
             status_code=response.status_code,
             duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    response.headers["X-Request-ID"] = request_id
    return response
