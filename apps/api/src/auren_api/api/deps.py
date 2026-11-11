"""FastAPI dependency providers: infrastructure access, authentication, authorization, limits."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.api.client_ip import resolve_client_ip
from auren_api.auth.clerk import JwksUnavailableError, TokenVerificationError
from auren_api.auth.principal import Principal
from auren_api.container import Container
from auren_api.domain.roles import Role
from auren_api.errors import (
    ForbiddenError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.services.users import UserService

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False, description="Clerk session token")


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    container: ContainerDep,
    session: SessionDep,
) -> Principal:
    """Authenticate the bearer token, then load the caller's stored roles."""
    if credentials is None:
        raise UnauthorizedError
    try:
        claims = await container.token_verifier.verify(credentials.credentials)
    except TokenVerificationError as exc:
        logger.info("authentication_failed", reason=str(exc))
        raise UnauthorizedError("Invalid or expired token.") from exc
    except JwksUnavailableError as exc:
        logger.error("jwks_unavailable")
        raise ServiceUnavailableError from exc

    account = await UserService(session).get_or_provision(claims.subject)
    structlog.contextvars.bind_contextvars(user_id=str(account.id))
    return Principal(user_id=account.id, clerk_user_id=account.clerk_user_id, roles=account.roles)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Authorize callers holding at least one of ``roles``. Everything else is denied."""

    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.has_any_role(roles):
            raise ForbiddenError
        return principal

    return dependency


async def _enforce(container: Container, policy: RateLimitPolicy, identity: str) -> None:
    try:
        decision = await container.rate_limiter.hit(policy, identity)
    except RedisError as exc:
        logger.error("rate_limiter_unavailable", policy=policy.value, error=type(exc).__name__)
        if container.settings.rate_limit_fail_open:
            return
        raise ServiceUnavailableError from exc
    if not decision.allowed:
        logger.warning(
            "rate_limited", policy=policy.value, identity_kind=identity.partition(":")[0]
        )
        raise RateLimitedError(decision.retry_after_seconds)


def limit_by_ip(policy: RateLimitPolicy) -> Callable[[Request, Container], Awaitable[None]]:
    """Rate limit by client IP. Use for unauthenticated endpoints."""

    async def dependency(request: Request, container: ContainerDep) -> None:
        ip = resolve_client_ip(request, container.settings.trusted_proxy_count)
        await _enforce(container, policy, f"ip:{ip}")

    return dependency  # pyright: ignore[reportReturnType]


def limit_by_user(policy: RateLimitPolicy) -> Callable[[Principal, Container], Awaitable[None]]:
    """Rate limit by authenticated user. Use for authenticated endpoints."""

    async def dependency(principal: PrincipalDep, container: ContainerDep) -> None:
        await _enforce(container, policy, f"user:{principal.user_id}")

    return dependency  # pyright: ignore[reportReturnType]
