"""A real HTTP server (loopback) that speaks the agent protocol from the server's side.

Test-only: it lets agent commands run end to end over real sockets and verifies the agent's
signatures, nonces and benchmark answers the way the API does.
"""

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from auren_agent.benchmark import cpu_chain
from auren_agent.signing import (
    HEADER_MACHINE_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    canonical_message,
)

CHALLENGE = bytes(range(32))
ITERATIONS = 500
SCAN_ID = "5c0e1d6a-0000-4000-8000-000000000001"


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass
class ControlPlaneState:
    enrollment_token: str = "valid-enrollment-token-value"
    public_keys: dict[str, bytes] = field(default_factory=dict[str, bytes])
    nonces: set[str] = field(default_factory=set[str])
    pending_scan: bool = False
    results: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    fail_result_with: tuple[int, str] | None = None


class _Handler(BaseHTTPRequestHandler):
    state: ControlPlaneState

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, code: str) -> None:
        self._send(
            status,
            {"error": {"code": code, "message": code, "request_id": None, "details": []}},
        )

    def _authenticate(self, body: bytes) -> str | None:
        headers = self.headers
        machine_id = headers.get(HEADER_MACHINE_ID, "")
        nonce = headers.get(HEADER_NONCE, "")
        key = self.state.public_keys.get(machine_id)
        if key is None or nonce in self.state.nonces:
            return None
        message = canonical_message(
            method="POST",
            path=self.path,
            machine_id=machine_id,
            timestamp=int(headers.get(HEADER_TIMESTAMP, "0")),
            nonce=nonce,
            body=body,
        )
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(
                _b64url_decode(headers.get(HEADER_SIGNATURE, "")), message
            )
        except (InvalidSignature, ValueError):
            return None
        if abs(time.time() - int(headers[HEADER_TIMESTAMP])) > 60:
            return None
        self.state.nonces.add(nonce)
        return machine_id

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/v1/agent/enroll":
            request = json.loads(body)
            if request["enrollment_token"] != self.state.enrollment_token:
                self._error(401, "invalid_enrollment")
                return
            self.state.public_keys[request["machine_id"]] = _b64url_decode(request["public_key"])
            self._send(200, {"machine_id": request["machine_id"]})
            return
        if self._authenticate(body) is None:
            self._error(401, "unauthorized")
        elif self.path == "/v1/agent/scans/claim":
            if not self.state.pending_scan:
                self._error(404, "no_pending_scan")
                return
            self.state.pending_scan = False
            self._send(
                200,
                {
                    "scan_id": SCAN_ID,
                    "challenge": CHALLENGE.hex(),
                    "cpu_iterations": ITERATIONS,
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        elif self.path == f"/v1/agent/scans/{SCAN_ID}/result":
            if self.state.fail_result_with:
                status, code = self.state.fail_result_with
                self._error(status, code)
                return
            result = json.loads(body)
            correct = result["cpu_digest"] == cpu_chain(CHALLENGE, ITERATIONS).hex()
            self.state.results.append({**result, "digest_correct": correct})
            self._send(
                200,
                {
                    "scan_id": SCAN_ID,
                    "status": "completed",
                    "cpu_hashes_per_second": 123,
                    "listing_paused": False,
                },
            )
        else:
            self._error(404, "not_found")


class FakeControlPlane:
    def __init__(self) -> None:
        self.state = ControlPlaneState()
        handler = type("Handler", (_Handler,), {"state": self.state})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "FakeControlPlane":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
