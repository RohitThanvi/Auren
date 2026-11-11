"""Application factory and lifespan wiring."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from auren_api import __version__
from auren_api.api import health
from auren_api.api.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from auren_api.api.v1.router import api_router
from auren_api.auth.clerk import ClerkTokenVerifier
from auren_api.config import Settings, get_settings
from auren_api.container import Container
from auren_api.errors import register_error_handlers
from auren_api.infrastructure.database import create_engine, create_session_factory
from auren_api.infrastructure.rate_limit import RedisRateLimiter, rules_from_settings
from auren_api.infrastructure.redis import create_redis
from auren_api.logging import configure_logging

logger = structlog.get_logger(__name__)

RATE_LIMIT_KEY_PREFIX = "auren:ratelimit"


def _build_container(settings: Settings) -> Container:
    engine = create_engine(settings)
    redis = create_redis(settings)
    http_client = httpx.AsyncClient(
        timeout=settings.http_client_timeout_seconds, follow_redirects=False
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        redis=redis,
        http_client=http_client,
        token_verifier=ClerkTokenVerifier(
            issuer=settings.clerk_issuer,
            jwks_url=settings.clerk_jwks_url,
            authorized_parties=frozenset(settings.clerk_authorized_parties),
            audience=settings.clerk_audience,
            leeway_seconds=settings.auth_clock_leeway_seconds,
            cache_ttl_seconds=settings.jwks_cache_ttl_seconds,
            min_refresh_interval_seconds=settings.jwks_min_refresh_interval_seconds,
            http_client=http_client,
        ),
        rate_limiter=RedisRateLimiter(redis, rules_from_settings(settings), RATE_LIMIT_KEY_PREFIX),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.environment)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        container = _build_container(settings)
        app.state.container = container
        logger.info("application_started", environment=settings.environment.value)
        try:
            yield
        finally:
            await container.http_client.aclose()
            await container.redis.aclose()
            await container.engine.dispose()
            logger.info("application_stopped")

    app = FastAPI(
        title="Auren API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=None if settings.is_production else "/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)

    # Middleware added last is outermost: security headers wrap everything, including errors.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    return app
