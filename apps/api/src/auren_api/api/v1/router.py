from fastapi import APIRouter, Depends

from auren_api.api.deps import limit_by_ip
from auren_api.api.v1 import users
from auren_api.infrastructure.rate_limit import RateLimitPolicy
from auren_api.schemas.common import ErrorResponse

api_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(limit_by_ip(RateLimitPolicy.ANONYMOUS))],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
api_router.include_router(users.router)
