"""Machine-authenticated endpoints used by the Auren agent (not by browsers)."""

from uuid import UUID

from fastapi import APIRouter, Depends

from auren_api.api.deps import AgentDep, AgentServiceDep, limit_by_ip, limit_by_machine
from auren_api.auth.agent import b64url_decode
from auren_api.domain.errors import RuleViolationError
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.schemas.agent import (
    AgentEnrollRequest,
    AgentEnrollResponse,
    ScanChallengeResponse,
    ScanResultRequest,
    ScanResultResponse,
)
from auren_api.schemas.common import ErrorResponse

router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)

_machine_limit = Depends(limit_by_machine(RateLimitPolicy.AUTHENTICATED))


@router.post(
    "/enroll",
    response_model=AgentEnrollResponse,
    summary="Bind an agent's public key to a machine (one-time token)",
    dependencies=[Depends(limit_by_ip(RateLimitPolicy.AUTH))],
)
async def enroll(body: AgentEnrollRequest, service: AgentServiceDep) -> AgentEnrollResponse:
    try:
        public_key = b64url_decode(body.public_key)
    except ValueError:
        raise RuleViolationError(
            "invalid_public_key", "The public key is not valid base64url."
        ) from None
    await service.enroll(body.machine_id, body.enrollment_token, public_key)
    return AgentEnrollResponse(machine_id=body.machine_id)


@router.post(
    "/scans/claim",
    response_model=ScanChallengeResponse,
    summary="Claim the next requested scan and receive its challenge (signed request)",
    dependencies=[_machine_limit],
)
async def claim_scan(agent: AgentDep, service: AgentServiceDep) -> ScanChallengeResponse:
    claimed = await service.claim_scan(agent.machine_id)
    return ScanChallengeResponse(
        scan_id=claimed.scan_id,
        challenge=claimed.challenge.hex(),
        cpu_iterations=claimed.cpu_iterations,
        expires_at=claimed.expires_at,
    )


@router.post(
    "/scans/{scan_id}/result",
    response_model=ScanResultResponse,
    summary="Submit the hardware report and benchmark answer (signed request)",
    dependencies=[_machine_limit],
)
async def submit_scan_result(
    scan_id: UUID, body: ScanResultRequest, agent: AgentDep, service: AgentServiceDep
) -> ScanResultResponse:
    outcome = await service.submit_result(
        agent.machine_id,
        scan_id,
        body.report.to_snapshot(),
        body.report.model_dump(mode="json"),
        bytes.fromhex(body.cpu_digest),
    )
    return ScanResultResponse(
        scan_id=outcome.scan_id,
        status="completed",
        cpu_hashes_per_second=outcome.cpu_hashes_per_second,
        listing_paused=outcome.listing_paused,
    )
