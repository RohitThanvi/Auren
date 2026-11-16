"""Agent protocol: enrolment, request signing, replay protection, platform scan lifecycle."""

import asyncio
import copy
import dataclasses
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from redis.asyncio import Redis
from sqlalchemy import text

from auren_api.auth.agent import HEADER_NONCE
from auren_api.config import RateLimitRule, Settings
from auren_api.domain.scan import hashes_per_second
from auren_api.infrastructure.replay import RedisNonceStore
from tests.agent_client import TestAgent
from tests.conftest import ClientHandle
from tests.flows import (
    EXAMPLE,
    enrolled_agent,
    machine,
    provider,
    set_db,
)
from tests.support import TokenFactory

SCANS = "/v1/provider/machines/{machine_id}/scans"
SCAN = "/v1/provider/machines/{machine_id}/scans/{scan_id}"
ITERATIONS = 2_000  # tests/conftest.py


async def issue_token(api: ClientHandle, headers: dict[str, str], machine_id: str) -> str:
    response = await api.client.post(
        f"/v1/provider/machines/{machine_id}/enrollment", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["enrollment_token"]


async def new_machine(
    api: ClientHandle, tokens: TokenFactory, subject: str
) -> tuple[dict[str, str], str]:
    headers = await provider(api, tokens, subject)
    return headers, await machine(api, headers)


# --- enrolment ------------------------------------------------------------------------------


async def test_enrolment_token_is_single_use(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_enrol")
    token = await issue_token(api, headers, machine_id)
    assert (await TestAgent(api, machine_id).enroll(token)).status_code == 200
    second = await TestAgent(api, machine_id).enroll(token)
    assert (second.status_code, second.json()["error"]["code"]) == (401, "invalid_enrollment")


async def test_enrolment_tokens_are_stored_only_as_hashes(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_hash")
    token = await issue_token(api, headers, machine_id)
    async with api.app.state.container.engine.connect() as connection:
        stored = await connection.scalar(text("SELECT token_hash FROM machine_enrollments"))
    assert stored != token
    assert stored is not None
    assert len(stored) == 64


async def test_all_enrolment_failures_look_the_same(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_oracle")
    token = await issue_token(api, headers, machine_id)
    other_machine = await machine(api, headers, "other")
    agent = TestAgent(api, machine_id)
    wrong_token = await agent.enroll("x" * 43)
    other = await agent.enroll(token, machine_id=other_machine)  # token belongs to another machine
    unknown = await agent.enroll(token, machine_id=str(uuid.uuid4()))
    bodies = [r.json()["error"] for r in (wrong_token, other, unknown)]
    assert {r.status_code for r in (wrong_token, other, unknown)} == {401}
    assert len({(b["code"], b["message"]) for b in bodies}) == 1
    assert (await agent.enroll(token)).status_code == 200  # the real token still works


async def test_expired_enrolment_tokens_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_expired_token")
    token = await issue_token(api, headers, machine_id)
    await set_db(api, "UPDATE machine_enrollments SET expires_at = now() - interval '1 second'")
    assert (await TestAgent(api, machine_id).enroll(token)).status_code == 401


async def test_a_new_token_revokes_older_unused_ones(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_revoke")
    first = await issue_token(api, headers, machine_id)
    second = await issue_token(api, headers, machine_id)
    agent = TestAgent(api, machine_id)
    assert (await agent.enroll(first)).status_code == 401
    assert (await agent.enroll(second)).status_code == 200


async def test_re_enrolling_replaces_the_credential(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_reenrol")
    old_agent = await enrolled_agent(api, headers, machine_id)
    assert (await old_agent.claim()).status_code == 404  # authenticated, nothing to claim
    new_agent = TestAgent(api, machine_id)
    assert (await new_agent.enroll(await issue_token(api, headers, machine_id))).status_code == 200
    assert (await old_agent.claim()).status_code == 401
    assert (await new_agent.claim()).status_code == 404
    async with api.app.state.container.engine.connect() as connection:
        active = await connection.scalar(
            text("SELECT count(*) FROM machine_credentials WHERE revoked_at IS NULL")
        )
    assert active == 1


async def test_withdrawn_machines_cannot_be_enrolled(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_withdrawn_enrol")
    token = await issue_token(api, headers, machine_id)
    await api.client.post(f"/v1/provider/machines/{machine_id}/withdraw", headers=headers)
    assert (await TestAgent(api, machine_id).enroll(token)).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"enrollment_token": "short", "public_key": "A" * 43},
        {"enrollment_token": "t" * 43, "public_key": "A" * 42},
        {"enrollment_token": "t" * 43, "public_key": "A" * 44},
        {"enrollment_token": "t" * 43, "public_key": "A" * 43, "extra": 1},
    ],
)
async def test_enrolment_input_is_validated(
    api: ClientHandle, tokens: TokenFactory, body: dict[str, Any]
) -> None:
    _, machine_id = await new_machine(api, tokens, "user_enrol_validation")
    response = await api.client.post("/v1/agent/enroll", json={"machine_id": machine_id, **body})
    assert response.status_code == 422


async def test_enrolment_rejects_keys_with_invalid_characters(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_bad_keys")
    token = await issue_token(api, headers, machine_id)
    response = await api.client.post(
        "/v1/agent/enroll",
        json={"machine_id": machine_id, "enrollment_token": token, "public_key": "!" * 43},
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "invalid_public_key")
    # the token was not consumed by the failed attempt
    assert (await TestAgent(api, machine_id).enroll(token)).status_code == 200


async def test_enrolment_is_rate_limited_with_the_strict_auth_policy(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(
        make_settings(rate_limit_auth=RateLimitRule(limit=2, window_seconds=60))
    ).start()
    _, machine_id = await new_machine(handle, tokens, "user_enrol_limit")
    codes = [(await TestAgent(handle, machine_id).enroll("x" * 43)).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


# --- signed requests ------------------------------------------------------------------------


async def authenticated(api: ClientHandle, tokens: TokenFactory, subject: str) -> TestAgent:
    headers, machine_id = await new_machine(api, tokens, subject)
    return await enrolled_agent(api, headers, machine_id)


async def test_unsigned_and_partially_signed_requests_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    agent = await authenticated(api, tokens, "user_unsigned")
    path = "/v1/agent/scans/claim"
    bare = await api.client.post(path)
    assert bare.status_code == 401
    assert bare.headers["WWW-Authenticate"] == "Auren-Signature"
    full = agent.headers("POST", path, b"")
    for missing in full:
        if missing == "Content-Type":
            continue
        partial = {k: v for k, v in full.items() if k != missing}
        assert (await api.client.post(path, headers=partial)).status_code == 401, missing


async def test_valid_signatures_are_accepted(api: ClientHandle, tokens: TokenFactory) -> None:
    agent = await authenticated(api, tokens, "user_valid_sig")
    response = await agent.claim()
    assert (response.status_code, response.json()["error"]["code"]) == (404, "no_pending_scan")


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"key": Ed25519PrivateKey.generate()}, id="other-key"),
        pytest.param({"signed_path": "/v1/agent/scans/other"}, id="other-path"),
        pytest.param({"signed_body": b"{}"}, id="other-body"),
        pytest.param({"machine_id": str(uuid.uuid4())}, id="other-machine-in-signature"),
    ],
)
async def test_tampered_requests_are_rejected(
    api: ClientHandle, tokens: TokenFactory, tamper: dict[str, Any]
) -> None:
    agent = await authenticated(api, tokens, "user_tamper")
    response = await agent.claim(**tamper)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid agent credentials."


async def test_timestamps_outside_the_window_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    agent = await authenticated(api, tokens, "user_clock")
    now = int(time.time())
    for offset in (-120, 120):
        assert (await agent.claim(timestamp=now + offset)).status_code == 401
    assert (await agent.claim(timestamp=now - 30)).status_code == 404  # within the 60 s window


@pytest.mark.parametrize(
    "nonce", ["short", "has space in it 1234", "x" * 65, "bad/char/in/nonce!!"]
)
async def test_malformed_nonces_are_rejected(
    api: ClientHandle, tokens: TokenFactory, nonce: str
) -> None:
    agent = await authenticated(api, tokens, "user_nonce_format")
    assert (await agent.claim(nonce=nonce)).status_code == 401


async def test_malformed_timestamp_and_machine_headers_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    agent = await authenticated(api, tokens, "user_header_format")
    path = "/v1/agent/scans/claim"
    for name, value in (
        ("X-Auren-Timestamp", "abc"),
        ("X-Auren-Timestamp", "9" * 30),
        ("X-Auren-Machine-Id", "not-a-uuid"),
        ("X-Auren-Signature", "not base64 !!"),
        ("X-Auren-Signature", "AAAA"),
    ):
        headers = agent.headers("POST", path, b"")
        headers[name] = value
        assert (await api.client.post(path, headers=headers)).status_code == 401, (name, value)


async def test_replayed_requests_are_rejected(api: ClientHandle, tokens: TokenFactory) -> None:
    agent = await authenticated(api, tokens, "user_replay")
    path = "/v1/agent/scans/claim"
    headers = agent.headers("POST", path, b"")
    first = await api.client.post(path, headers=headers)
    assert first.status_code == 404  # authenticated; the nonce is now spent
    replay = await api.client.post(path, headers=headers)
    assert (replay.status_code, replay.json()["error"]["message"]) == (
        401,
        "Invalid agent credentials.",
    )
    assert headers[HEADER_NONCE]


async def test_unknown_machines_are_indistinguishable_from_bad_signatures(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    agent = await authenticated(api, tokens, "user_unknown")
    ghost = TestAgent(api, str(uuid.uuid4()))
    unknown = await ghost.claim()
    forged = await agent.claim(key=Ed25519PrivateKey.generate())
    assert unknown.status_code == forged.status_code == 401
    assert unknown.json()["error"]["message"] == forged.json()["error"]["message"]


async def test_agent_auth_fails_closed_when_redis_is_down(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    agent = await authenticated(api, tokens, "user_redis_down")
    unreachable = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2
    )
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, nonce_store=RedisNonceStore(unreachable, "test")
    )
    response = await agent.claim()
    assert (response.status_code, response.json()["error"]["code"]) == (503, "service_unavailable")
    await unreachable.aclose()


async def test_agent_requests_are_rate_limited_per_machine(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(
        make_settings(rate_limit_authenticated=RateLimitRule(limit=2, window_seconds=60))
    ).start()
    agent = await authenticated(handle, tokens, "user_agent_limit")
    other = await authenticated(handle, tokens, "user_agent_limit_2")
    codes = [(await agent.claim()).status_code for _ in range(3)]
    assert codes == [404, 404, 429]
    assert (await other.claim()).status_code == 404  # another machine has its own budget


# --- scan lifecycle -------------------------------------------------------------------------


async def start_scan(api: ClientHandle, headers: dict[str, str], machine_id: str) -> str:
    response = await api.client.post(SCANS.format(machine_id=machine_id), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def scan_state(
    api: ClientHandle, headers: dict[str, str], machine_id: str, scan_id: str
) -> dict[str, Any]:
    response = await api.client.get(
        SCAN.format(machine_id=machine_id, scan_id=scan_id), headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_scans_need_an_enrolled_agent(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_no_agent")
    response = await api.client.post(SCANS.format(machine_id=machine_id), headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "agent_not_enrolled")


async def test_full_scan_lifecycle(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_lifecycle")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    assert (await scan_state(api, headers, machine_id, scan_id))["status"] == "pending"

    claimed = await agent.claim()
    challenge = claimed.json()
    assert claimed.status_code == 200
    assert challenge["scan_id"] == scan_id
    assert len(challenge["challenge"]) == 64
    assert challenge["cpu_iterations"] == ITERATIONS
    assert (await scan_state(api, headers, machine_id, scan_id))["status"] == "claimed"

    result = await agent.submit(scan_id, EXAMPLE, TestAgent.answer(challenge))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    state = await scan_state(api, headers, machine_id, scan_id)
    assert state["status"] == "completed"
    assert state["completed_at"] is not None
    assert state["cpu_hashes_per_second"] == result.json()["cpu_hashes_per_second"] > 0

    async with api.app.state.container.engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT cpu_hashes_per_second, scan_elapsed_ms FROM machine_inventories")
            )
        ).one()
    assert row.cpu_hashes_per_second == hashes_per_second(ITERATIONS, row.scan_elapsed_ms)


async def test_only_one_scan_can_be_open_per_machine(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_open_scan")
    await enrolled_agent(api, headers, machine_id)
    responses = await asyncio.gather(
        *(api.client.post(SCANS.format(machine_id=machine_id), headers=headers) for _ in range(6))
    )
    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "scan_in_progress"
    }


async def test_a_challenge_can_be_claimed_only_once(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_claim_once")
    agent = await enrolled_agent(api, headers, machine_id)
    await start_scan(api, headers, machine_id)
    first, second = await asyncio.gather(agent.claim(), agent.claim())
    assert sorted([first.status_code, second.status_code]) == [200, 404]


async def test_claiming_starts_a_short_server_side_deadline(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_deadline")
    agent = await enrolled_agent(api, headers, machine_id)
    await start_scan(api, headers, machine_id)
    claimed = (await agent.claim()).json()
    async with api.app.state.container.engine.connect() as connection:
        seconds_left = await connection.scalar(
            text("SELECT extract(epoch FROM expires_at - now()) FROM machine_scans")
        )
    assert seconds_left is not None
    assert 0 < float(seconds_left) <= 120  # scan_result_deadline_seconds
    assert claimed["expires_at"]


async def test_a_wrong_benchmark_answer_fails_the_scan_for_good(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_bad_digest")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    claimed = (await agent.claim()).json()
    wrong = await agent.submit(scan_id, EXAMPLE, "0" * 64)
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (422, "benchmark_mismatch")
    state = await scan_state(api, headers, machine_id, scan_id)
    assert (state["status"], state["failure_reason"]) == ("failed", "benchmark_mismatch")
    retry = await agent.submit(scan_id, EXAMPLE, TestAgent.answer(claimed))
    assert (retry.status_code, retry.json()["error"]["code"]) == (409, "scan_not_claimed")
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    assert detail["inventory"] is None
    await start_scan(api, headers, machine_id)  # a failed scan does not block a new one


async def test_results_are_single_use(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_single_use")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    claimed = (await agent.claim()).json()
    answer = TestAgent.answer(claimed)
    assert (await agent.submit(scan_id, EXAMPLE, answer)).status_code == 200
    again = await agent.submit(scan_id, EXAMPLE, answer)
    assert (again.status_code, again.json()["error"]["code"]) == (409, "scan_not_claimed")


async def test_results_for_unclaimed_scans_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_unclaimed")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    response = await agent.submit(scan_id, EXAMPLE, "0" * 64)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "scan_not_claimed")


async def test_an_agent_cannot_answer_another_machines_scan(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_victim")
    victim_agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    challenge = (await victim_agent.claim()).json()

    attacker_headers, attacker_machine = await new_machine(api, tokens, "user_attacker")
    attacker = await enrolled_agent(api, attacker_headers, attacker_machine)
    response = await attacker.submit(scan_id, EXAMPLE, TestAgent.answer(challenge))
    assert (response.status_code, response.json()["error"]["code"]) == (404, "scan_not_found")
    unknown = await attacker.submit(str(uuid.uuid4()), EXAMPLE, "0" * 64)
    assert unknown.json()["error"] == {
        **response.json()["error"],
        "request_id": unknown.json()["error"]["request_id"],
    }
    state = await scan_state(api, headers, machine_id, scan_id)
    assert state["status"] == "claimed"  # untouched


async def test_other_providers_cannot_read_scans(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_scan_owner")
    await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    other = await provider(api, tokens, "user_scan_snoop")
    response = await api.client.get(
        SCAN.format(machine_id=machine_id, scan_id=scan_id), headers=other
    )
    assert response.status_code == 404


async def test_late_results_are_rejected_and_fail_the_scan(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_late")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    claimed = (await agent.claim()).json()
    await set_db(api, "UPDATE machine_scans SET expires_at = now() - interval '1 second'")
    late = await agent.submit(scan_id, EXAMPLE, TestAgent.answer(claimed))
    assert (late.status_code, late.json()["error"]["code"]) == (409, "scan_expired")
    state = await scan_state(api, headers, machine_id, scan_id)
    assert (state["status"], state["failure_reason"]) == ("failed", "expired")


async def test_stale_open_scans_expire_and_do_not_block_new_ones(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_stale")
    agent = await enrolled_agent(api, headers, machine_id)
    old = await start_scan(api, headers, machine_id)
    await set_db(api, "UPDATE machine_scans SET expires_at = now() - interval '1 second'")
    assert (await scan_state(api, headers, machine_id, old))["status"] == "expired"
    assert (await agent.claim()).status_code == 404  # an expired challenge cannot be claimed
    new = await start_scan(api, headers, machine_id)
    assert new != old
    old_state = await scan_state(api, headers, machine_id, old)
    assert (old_state["status"], old_state["failure_reason"]) == ("failed", "expired")


async def test_invalid_reports_are_rejected_without_consuming_the_scan(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_bad_report")
    agent = await enrolled_agent(api, headers, machine_id)
    scan_id = await start_scan(api, headers, machine_id)
    claimed = (await agent.claim()).json()
    answer = TestAgent.answer(claimed)

    def variant(path: list[str], value: Any) -> dict[str, Any]:
        body: dict[str, Any] = copy.deepcopy(EXAMPLE)
        node: Any = body
        for key in path[:-1]:
            node = node[int(key)] if key.isdigit() else node[key]
        node[path[-1]] = value
        return body

    bad_reports = [
        variant(["cpu", "logical_cores"], 0),
        variant(["cpu", "logical_cores"], 10**9),
        variant(["cpu", "physical_cores"], 64),
        variant(["cpu", "model_name"], "evil\nmodel"),
        variant(["security", "confidential_computing_flags"], ["quantum"]),
        variant(["memory", "available_bytes"], 10**15),
        variant(["memory", "total_bytes"], 2**60),
        variant(["memory", "total_bytes"], "68719476736"),
        variant(["storage", "free_bytes"], 10**15),
        variant(["gpus"], [EXAMPLE["gpus"][0]] * 17),
        variant(["platform", "unexpected"], "field"),
        variant(["gpus", "0", "index"], 3),
        variant(["gpus"], [EXAMPLE["gpus"][0], {**EXAMPLE["gpus"][0], "index": 1}]),
        variant(["security", "cgroup_controllers"], ["x"] * 33),
        variant(["security", "agent_running_as_root"], "no"),
        variant(["network"], [{"name": "eth0", "speed_mbps": -5, "is_up": True}]),
        {k: v for k, v in EXAMPLE.items() if k != "memory"},
        {**EXAMPLE, "extra": 1},
    ]
    for report in bad_reports:
        response = await agent.submit(scan_id, report, answer)
        assert response.status_code == 422, report
    assert (await agent.submit(scan_id, EXAMPLE, "ABC")).status_code == 422
    assert (await scan_state(api, headers, machine_id, scan_id))["status"] == "claimed"
    assert (await agent.submit(scan_id, EXAMPLE, answer)).status_code == 200


async def test_enrolment_and_scan_requests_share_the_strict_expensive_limit(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(
        make_settings(rate_limit_expensive=RateLimitRule(limit=3, window_seconds=60))
    ).start()
    headers, machine_id = await new_machine(handle, tokens, "user_expensive")
    await enrolled_agent(handle, headers, machine_id)  # 1: enrolment token
    first = await handle.client.post(SCANS.format(machine_id=machine_id), headers=headers)  # 2
    second = await handle.client.post(SCANS.format(machine_id=machine_id), headers=headers)  # 3
    third = await handle.client.post(SCANS.format(machine_id=machine_id), headers=headers)
    assert (first.status_code, second.status_code, third.status_code) == (201, 409, 429)


async def test_weak_public_keys_cannot_be_enrolled(api: ClientHandle, tokens: TokenFactory) -> None:
    headers, machine_id = await new_machine(api, tokens, "user_weak_key")
    token = await issue_token(api, headers, machine_id)
    for weak in ("A" * 43, "AQ" + "A" * 41):  # all-zero key; identity point
        response = await api.client.post(
            "/v1/agent/enroll",
            json={"machine_id": machine_id, "enrollment_token": token, "public_key": weak},
        )
        assert (response.status_code, response.json()["error"]["code"]) == (
            422,
            "invalid_public_key",
        )
    assert (await TestAgent(api, machine_id).enroll(token)).status_code == 200
