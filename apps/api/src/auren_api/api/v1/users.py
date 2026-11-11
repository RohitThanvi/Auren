from fastapi import APIRouter, Depends

from auren_api.api.deps import PrincipalDep, limit_by_user
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.schemas.users import MeResponse

router = APIRouter(tags=["users"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user",
    dependencies=[Depends(limit_by_user(RateLimitPolicy.AUTHENTICATED))],
)
async def read_me(principal: PrincipalDep) -> MeResponse:
    return MeResponse(id=principal.user_id, roles=sorted(principal.roles))
