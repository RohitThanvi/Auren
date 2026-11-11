"""Shared fixtures. Tests run against real PostgreSQL and Redis; only Clerk's JWKS is faked.

The suite truncates tables and flushes Redis, so it refuses to run unless the configured test
database name ends in ``_test``. Connection strings come from the environment (see .env.example).
"""

import dataclasses
import os
from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from auren_api.auth.clerk import ClerkTokenVerifier
from auren_api.config import Environment, Settings, get_settings
from auren_api.main import create_app
from tests.support import AUTHORIZED_PARTY, ISSUER, TokenFactory

API_ROOT = Path(__file__).resolve().parents[1]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.exit(f"{name} must be set to run the test suite (see .env.example)", returncode=2)
    return value


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _require_env("AUREN_TEST_DATABASE_URL")
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.exit("AUREN_TEST_DATABASE_URL must point at a database whose name ends in _test")
    return url


@pytest.fixture(scope="session")
def redis_url() -> str:
    return _require_env("AUREN_TEST_REDIS_URL")


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str, redis_url: str) -> Iterator[None]:
    """Rebuild the schema from migrations (exercises upgrade and downgrade)."""
    patch = pytest.MonkeyPatch()
    patch.setenv("AUREN_ENVIRONMENT", Environment.TEST.value)
    patch.setenv("AUREN_DATABASE_URL", database_url)
    patch.setenv("AUREN_REDIS_URL", redis_url)
    patch.setenv("AUREN_CLERK_ISSUER", ISSUER)
    get_settings.cache_clear()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    get_settings.cache_clear()
    patch.undo()


@pytest.fixture
def make_settings(database_url: str, redis_url: str) -> Callable[..., Settings]:
    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "environment": Environment.TEST,
            "database_url": database_url,
            "redis_url": redis_url,
            "clerk_issuer": ISSUER,
            "clerk_authorized_parties": [AUTHORIZED_PARTY],
            "cors_allowed_origins": [AUTHORIZED_PARTY],
            "log_level": "WARNING",
            **overrides,
        }
        return Settings(**values)  # pyright: ignore[reportArgumentType]

    return factory


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def jwks_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
async def make_client(
    tokens: TokenFactory, jwks_requests: list[httpx.Request]
) -> AsyncGenerator[Callable[[Settings], "ClientHandle"]]:
    """Build an app + HTTP client for the given settings, with Clerk's JWKS served locally."""
    handles: list[ClientHandle] = []

    def build(settings: Settings) -> ClientHandle:
        handle = ClientHandle(settings, tokens, jwks_requests)
        handles.append(handle)
        return handle

    yield build
    for handle in handles:
        await handle.close()


class ClientHandle:
    def __init__(
        self, settings: Settings, tokens: TokenFactory, jwks_requests: list[httpx.Request]
    ) -> None:
        self.settings = settings
        self.app = create_app(settings)
        self._lifespan = self.app.router.lifespan_context(self.app)
        self._tokens = tokens
        self._jwks_requests = jwks_requests
        self.client: httpx.AsyncClient

    async def start(self, *, reset_database: bool = True) -> "ClientHandle":
        await self._lifespan.__aenter__()
        container = self.app.state.container

        def jwks_handler(request: httpx.Request) -> httpx.Response:
            self._jwks_requests.append(request)
            return httpx.Response(200, json=self._tokens.jwks())

        verifier = ClerkTokenVerifier(
            issuer=self.settings.clerk_issuer,
            jwks_url=self.settings.clerk_jwks_url,
            authorized_parties=frozenset(self.settings.clerk_authorized_parties),
            audience=self.settings.clerk_audience,
            leeway_seconds=self.settings.auth_clock_leeway_seconds,
            cache_ttl_seconds=self.settings.jwks_cache_ttl_seconds,
            min_refresh_interval_seconds=self.settings.jwks_min_refresh_interval_seconds,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(jwks_handler)),
        )
        self.app.state.container = dataclasses.replace(container, token_verifier=verifier)
        if reset_database:
            async with self.app.state.container.engine.begin() as connection:
                await connection.execute(text("TRUNCATE users, user_roles CASCADE"))
        await container.redis.flushdb()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://testserver"
        )
        return self

    async def close(self) -> None:
        await self.client.aclose()
        await self._lifespan.__aexit__(None, None, None)


@pytest.fixture
async def api(settings: Settings, make_client: Callable[[Settings], ClientHandle]) -> ClientHandle:
    return await make_client(settings).start()
