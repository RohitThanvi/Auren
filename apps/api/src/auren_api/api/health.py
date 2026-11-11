"""Liveness and readiness probes (unversioned, unauthenticated, not rate limited)."""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from auren_api.api.deps import ContainerDep
from auren_api.container import Container

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "failed"]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckStatus]


async def _check_database(container: Container) -> CheckStatus:
    try:
        async with container.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness_database_failed")
        return "failed"
    return "ok"


async def _check_redis(container: Container) -> CheckStatus:
    try:
        await container.redis.ping()  # pyright: ignore[reportUnknownMemberType]  # redis-py stub gap
    except Exception:
        logger.exception("readiness_redis_failed")
        return "failed"
    return "ok"


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(container: ContainerDep) -> ReadyResponse | JSONResponse:
    timeout = container.settings.readiness_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            database, redis = await asyncio.gather(
                _check_database(container), _check_redis(container)
            )
    except TimeoutError:
        logger.error("readiness_timed_out", timeout_seconds=timeout)
        database = redis = "failed"
    checks: dict[str, CheckStatus] = {"database": database, "redis": redis}
    if all(value == "ok" for value in checks.values()):
        return ReadyResponse(status="ok", checks=checks)
    body = ReadyResponse(status="unavailable", checks=checks)
    return JSONResponse(status_code=503, content=body.model_dump())
