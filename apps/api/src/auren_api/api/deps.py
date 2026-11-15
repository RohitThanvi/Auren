"""FastAPI dependency providers: infrastructure access, authentication, authorization, limits."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from auren_api.api.client_ip import resolve_client_ip
from auren_api.auth.agent import (
    HEADER_MACHINE_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    NONCE_PATTERN,
    SIGNATURE_BYTES,
    AgentPrincipal,
    b64url_decode,
    canonical_message,
    verify_signature,
)
from auren_api.auth.clerk import JwksUnavailableError, TokenVerificationError
from auren_api.auth.principal import Principal
from auren_api.container import Container
from auren_api.domain.clock import utcnow
from auren_api.domain.machine import MachineStatus
from auren_api.domain.roles import Role
from auren_api.errors import (
    ForbiddenError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.repositories.agents import AgentRepository
from auren_api.services.agent import AgentService
from auren_api.services.provider import ProviderService
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


def get_provider_service(container: ContainerDep, session: SessionDep) -> ProviderService:
    return ProviderService(session, container.provider_policy)


ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]


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


def get_agent_service(container: ContainerDep, session: SessionDep) -> AgentService:
    return AgentService(session, container.provider_policy)


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]

_AGENT_SCHEME = "Auren-Signature"
_MAX_TIMESTAMP_DIGITS = 12


def _agent_unauthorized(reason: str) -> UnauthorizedError:
    logger.info("agent_authentication_failed", reason=reason)
    return UnauthorizedError("Invalid agent credentials.", scheme=_AGENT_SCHEME)


async def get_agent_principal(
    request: Request, container: ContainerDep, session: SessionDep
) -> AgentPrincipal:
    """Authenticate a signed agent request (signature, freshness, single-use nonce)."""
    machine_header = request.headers.get(HEADER_MACHINE_ID)
    timestamp_header = request.headers.get(HEADER_TIMESTAMP)
    nonce = request.headers.get(HEADER_NONCE)
    signature_header = request.headers.get(HEADER_SIGNATURE)
    if not (machine_header and timestamp_header and nonce and signature_header):
        raise _agent_unauthorized("missing_header")
    try:
        machine_id = uuid.UUID(machine_header)
        signature = b64url_decode(signature_header)
    except ValueError:
        raise _agent_unauthorized("malformed_header") from None
    if (
        not timestamp_header.isdigit()
        or len(timestamp_header) > _MAX_TIMESTAMP_DIGITS
        or not NONCE_PATTERN.match(nonce)
        or len(signature) != SIGNATURE_BYTES
    ):
        raise _agent_unauthorized("malformed_header")

    timestamp = int(timestamp_header)
    max_skew = container.settings.agent_request_max_skew_seconds
    if abs(utcnow().timestamp() - timestamp) > max_skew:
        raise _agent_unauthorized("stale_timestamp")

    identity = await AgentRepository(session).identity(machine_id)
    if identity is None or identity.machine_status is MachineStatus.WITHDRAWN:
        raise _agent_unauthorized("unknown_machine")
    message = canonical_message(
        method=request.method,
        path=request.url.path,
        machine_id=str(machine_id),
        timestamp=timestamp,
        nonce=nonce,
        body=await request.body(),
    )
    if not verify_signature(identity.public_key, signature, message):
        raise _agent_unauthorized("bad_signature")

    # The nonce is recorded only after the signature is valid, so unsigned junk cannot fill Redis.
    try:
        fresh = await container.nonce_store.claim(machine_id, nonce, 2 * max_skew)
    except RedisError as exc:
        logger.error("nonce_store_unavailable", error=type(exc).__name__)
        raise ServiceUnavailableError from exc
    if not fresh:
        raise _agent_unauthorized("replayed_nonce")

    structlog.contextvars.bind_contextvars(machine_id=str(machine_id))
    return AgentPrincipal(machine_id=machine_id, owner_user_id=identity.owner_user_id)


AgentDep = Annotated[AgentPrincipal, Depends(get_agent_principal)]


def limit_by_machine(
    policy: RateLimitPolicy,
) -> Callable[[AgentPrincipal, Container], Awaitable[None]]:
    """Rate limit by authenticated machine. Use for agent endpoints."""

    async def dependency(agent: AgentDep, container: ContainerDep) -> None:
        await _enforce(container, policy, f"machine:{agent.machine_id}")

    return dependency  # pyright: ignore[reportReturnType]
