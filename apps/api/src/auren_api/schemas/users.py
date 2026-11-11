from uuid import UUID

from pydantic import BaseModel

from auren_api.domain.roles import Role


class MeResponse(BaseModel):
    id: UUID
    roles: list[Role]
