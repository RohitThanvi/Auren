"""HTTP client for the Auren API (agent endpoints)."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auren_agent.signing import sign_request

_NO_PENDING_SCAN = "no_pending_scan"


class ControlPlaneError(Exception):
    """The API rejected a request. ``code`` is the API's stable error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"{status} {code}: {message}")


@dataclass(frozen=True, slots=True)
class ScanChallenge:
    scan_id: uuid.UUID
    challenge: bytes
    cpu_iterations: int


class ControlPlaneClient:
    def __init__(self, http: httpx.Client, base_url: str) -> None:
        self._http = http
        self._base_url = base_url

    def enroll(self, machine_id: uuid.UUID, token: str, public_key_b64: str) -> None:
        response = self._http.post(
            f"{self._base_url}/v1/agent/enroll",
            json={
                "machine_id": str(machine_id),
                "enrollment_token": token,
                "public_key": public_key_b64,
            },
        )
        self._raise_for_error(response)

    def claim_scan(
        self, private_key: Ed25519PrivateKey, machine_id: uuid.UUID
    ) -> ScanChallenge | None:
        """Claim the next requested scan; None if the provider has not requested one."""
        try:
            body = self._signed_post(private_key, machine_id, "/v1/agent/scans/claim", b"")
        except ControlPlaneError as exc:
            if exc.code == _NO_PENDING_SCAN:
                return None
            raise
        return ScanChallenge(
            scan_id=uuid.UUID(body["scan_id"]),
            challenge=bytes.fromhex(body["challenge"]),
            cpu_iterations=int(body["cpu_iterations"]),
        )

    def submit_result(
        self,
        private_key: Ed25519PrivateKey,
        machine_id: uuid.UUID,
        scan_id: uuid.UUID,
        report: dict[str, Any],
        cpu_digest: bytes,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {"report": report, "cpu_digest": cpu_digest.hex()}, separators=(",", ":")
        ).encode("utf-8")
        return self._signed_post(
            private_key, machine_id, f"/v1/agent/scans/{scan_id}/result", payload
        )

    def _signed_post(
        self, private_key: Ed25519PrivateKey, machine_id: uuid.UUID, path: str, body: bytes
    ) -> dict[str, Any]:
        headers = sign_request(
            private_key, machine_id=machine_id, method="POST", path=path, body=body
        )
        headers["Content-Type"] = "application/json"
        response = self._http.post(f"{self._base_url}{path}", content=body, headers=headers)
        self._raise_for_error(response)
        result: dict[str, Any] = response.json()
        return result

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            error = response.json()["error"]
            raise ControlPlaneError(response.status_code, str(error["code"]), str(error["message"]))
        except (ValueError, KeyError, TypeError):
            raise ControlPlaneError(
                response.status_code, "unknown_error", response.reason_phrase
            ) from None
