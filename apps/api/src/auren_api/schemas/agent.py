"""Contract for the machine-authenticated agent endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from auren_api.schemas.provider import InventoryReport

HEX_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
PUBLIC_KEY_B64_LENGTH = 43  # 32 bytes, unpadded base64url


class _AgentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentEnrollRequest(_AgentBody):
    machine_id: UUID
    enrollment_token: str = Field(min_length=16, max_length=128)
    # Ed25519 public key, unpadded base64url. The private key never leaves the machine.
    public_key: str = Field(min_length=PUBLIC_KEY_B64_LENGTH, max_length=PUBLIC_KEY_B64_LENGTH)


class AgentEnrollResponse(BaseModel):
    machine_id: UUID


class ScanChallengeResponse(BaseModel):
    scan_id: UUID
    # Hex of 32 random bytes. cpu_digest = SHA-256 applied cpu_iterations times, starting here.
    challenge: str
    cpu_iterations: int
    expires_at: datetime


class ScanResultRequest(_AgentBody):
    report: InventoryReport
    cpu_digest: str = Field(pattern=HEX_DIGEST_PATTERN)


class ScanResultResponse(BaseModel):
    scan_id: UUID
    status: Literal["completed"]
    cpu_hashes_per_second: int
    # True when the new scan made an existing listing invalid and the machine was paused.
    listing_paused: bool
