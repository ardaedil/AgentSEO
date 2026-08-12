from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from .api import router
from .config import get_settings
from .database import create_schema

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_schema()
    yield


app = FastAPI(
    title="AgentSEO API",
    version="0.1.0",
    description="Deterministic AI-agent compatibility benchmarking for OpenAPI interfaces.",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")

request_times: defaultdict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def basic_rate_limit(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in {"/api/health", "/docs", "/openapi.json"}:
        return await call_next(request)
    key = request.client.host if request.client else "unknown"
    now = monotonic()
    bucket = request_times[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 240:
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    bucket.append(now)
    return await call_next(request)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "AgentSEO", "docs": "/docs", "health": "/api/health"}
