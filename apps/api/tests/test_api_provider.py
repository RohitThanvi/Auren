"""End-to-end provider flows over HTTP against real PostgreSQL and Redis."""

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from auren_api.config import RateLimitRule, Settings
from tests.conftest import ClientHandle
from tests.flows import (
    CEILING,
    EXAMPLE,
    FLOOR,
    GIB,
    OFFER,
    auth,
    enrolled_agent,
    listing,
    machine,
    provider,
    put_listing,
    run_scan,
    scanned_machine,
    set_db,
)
from tests.support import TokenFactory

# --- enrolment ------------------------------------------------------------------------------


async def test_anyone_can_become_a_provider_and_it_is_idempotent(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = auth(tokens, "user_new_provider")
    first = await api.client.post("/v1/provider/enable", headers=headers)
    second = await api.client.post("/v1/provider/enable", headers=headers)
    assert first.json()["roles"] == ["buyer", "provider"]
    assert second.json() == first.json()
    me = await api.client.get("/v1/me", headers=headers)
    assert me.json()["roles"] == ["buyer", "provider"]
    async with api.app.state.container.engine.connect() as connection:
        granted = await connection.scalar(
            text("SELECT granted_at FROM user_roles WHERE role = 'provider'")
        )
    assert granted is not None


async def test_enabling_requires_authentication(api: ClientHandle) -> None:
    assert (await api.client.post("/v1/provider/enable")).status_code == 401


async def test_enabling_is_rate_limited_with_the_strict_auth_policy(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(
        make_settings(rate_limit_auth=RateLimitRule(limit=2, window_seconds=60))
    ).start()
    headers = auth(tokens, "user_spammer")
    codes = [
        (await handle.client.post("/v1/provider/enable", headers=headers)).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


async def test_machine_routes_require_the_provider_role(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = auth(tokens, "user_only_buyer")
    some_id = uuid.uuid4()
    calls = [
        api.client.get("/v1/provider/machines", headers=headers),
        api.client.post("/v1/provider/machines", json={"name": "x"}, headers=headers),
        api.client.get(f"/v1/provider/machines/{some_id}", headers=headers),
        api.client.put(f"/v1/provider/machines/{some_id}/listing", json={}, headers=headers),
    ]
    for response in await asyncio.gather(*calls):
        assert response.status_code == 403
    assert (await api.client.get("/v1/provider/machines")).status_code == 401


# --- machines -------------------------------------------------------------------------------


async def test_register_and_list_machines(api: ClientHandle, tokens: TokenFactory) -> None:
    headers = await provider(api, tokens, "user_p1")
    machine_id = await machine(api, headers, "  my rig  ")
    listed = (await api.client.get("/v1/provider/machines", headers=headers)).json()
    assert [(m["id"], m["name"], m["status"]) for m in listed] == [
        (machine_id, "my rig", "registered")
    ]
    assert listed[0]["inventory"] is None
    assert listed[0]["listing"] is None


async def test_duplicate_machine_names_are_rejected_per_owner(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    alice = await provider(api, tokens, "user_alice")
    bob = await provider(api, tokens, "user_bob")
    await machine(api, alice, "rig")
    duplicate = await api.client.post("/v1/provider/machines", json={"name": "rig"}, headers=alice)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "machine_name_taken"
    await machine(api, bob, "rig")  # the same name is fine for another provider


async def test_machine_limit_is_enforced_even_under_concurrency(
    make_settings: Callable[..., Settings],
    make_client: Callable[[Settings], ClientHandle],
    tokens: TokenFactory,
) -> None:
    handle = await make_client(make_settings(provider_max_machines=3)).start()
    headers = await provider(handle, tokens, "user_many")
    responses = await asyncio.gather(
        *(
            handle.client.post("/v1/provider/machines", json={"name": f"m{i}"}, headers=headers)
            for i in range(8)
        )
    )
    codes = sorted(response.status_code for response in responses)
    assert codes == [201, 201, 201, 409, 409, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "machine_limit_reached"
    }


async def test_machine_name_validation(api: ClientHandle, tokens: TokenFactory) -> None:
    headers = await provider(api, tokens, "user_names")
    for bad in ["", "   ", "x" * 101, "bad\nname", "bad\x00name"]:
        response = await api.client.post(
            "/v1/provider/machines", json={"name": bad}, headers=headers
        )
        assert response.status_code == 422, bad
    extra = await api.client.post(
        "/v1/provider/machines", json={"name": "ok", "owner": "someone"}, headers=headers
    )
    assert extra.status_code == 422


async def test_other_providers_machines_are_invisible_everywhere(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    alice = await provider(api, tokens, "user_owner")
    mallory = await provider(api, tokens, "user_mallory")
    machine_id, _ = await scanned_machine(api, alice)
    assert (await put_listing(api, alice, machine_id, listing(10000))).status_code == 200
    base = f"/v1/provider/machines/{machine_id}"

    attempts = [
        api.client.get(base, headers=mallory),
        api.client.post(f"{base}/enrollment", headers=mallory),
        api.client.post(f"{base}/scans", headers=mallory),
        api.client.get(f"{base}/scans/{uuid.uuid4()}", headers=mallory),
        api.client.post(f"{base}/price-range", json={**OFFER, "tier": "standard"}, headers=mallory),
        api.client.put(f"{base}/listing", json=listing(10000), headers=mallory),
        api.client.post(f"{base}/pause", headers=mallory),
        api.client.post(f"{base}/resume", headers=mallory),
        api.client.post(f"{base}/withdraw", headers=mallory),
    ]
    for response in await asyncio.gather(*attempts):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "machine_not_found"

    assert (await api.client.get("/v1/provider/machines", headers=mallory)).json() == []
    untouched = (await api.client.get(base, headers=alice)).json()
    assert untouched["status"] == "listed"
    # A machine that does not exist looks exactly like one owned by someone else.
    unknown = await api.client.get(f"/v1/provider/machines/{uuid.uuid4()}", headers=mallory)
    foreign = await api.client.get(base, headers=mallory)
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json()["error"]["code"] == foreign.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == foreign.json()["error"]["message"]


# --- platform scan results ------------------------------------------------------------------


def mutated(path: list[str], value: Any) -> dict[str, Any]:
    body = json.loads(json.dumps(EXAMPLE))
    node = body
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return body


async def test_machine_detail_shows_the_platform_scan(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_inv")
    machine_id, agent = await scanned_machine(api, headers)
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    inventory = detail["inventory"]
    assert (inventory["logical_cores"], inventory["gpu_count"], inventory["kvm_available"]) == (
        32,
        1,
        True,
    )
    assert inventory["confidential_computing_flags"] == ["sev", "sev_es", "sev_snp"]
    assert inventory["cpu_hashes_per_second"] > 0
    assert inventory["verification"] == "agent_scanned"
    assert detail["confidential_verified"] is False
    assert agent.machine_id == machine_id


async def test_every_scan_is_kept_and_the_latest_is_current(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_history")
    machine_id, agent = await scanned_machine(api, headers)
    upgraded = mutated(["cpu", "logical_cores"], 64)
    assert (await run_scan(api, headers, agent, upgraded)).status_code == 200
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    assert detail["inventory"]["logical_cores"] == 64
    async with api.app.state.container.engine.connect() as connection:
        rows = await connection.scalar(text("SELECT count(*) FROM machine_inventories"))
    assert rows == 2


async def test_providers_cannot_submit_hardware_facts_themselves(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_no_self_report")
    machine_id = await machine(api, headers)
    for method in ("put", "post"):
        response = await getattr(api.client, method)(
            f"/v1/provider/machines/{machine_id}/inventory", json=EXAMPLE, headers=headers
        )
        assert response.status_code in {404, 405}
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    assert detail["inventory"] is None


# --- pricing and listing --------------------------------------------------------------------


async def test_price_range_is_computed_by_the_server(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_range")
    machine_id, _ = await scanned_machine(api, headers)
    response = await api.client.post(
        f"/v1/provider/machines/{machine_id}/price-range",
        json={**OFFER, "tier": "standard"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "base": {"amount_minor": 9800, "currency": "INR"},
        "floor": {"amount_minor": FLOOR, "currency": "INR"},
        "ceiling": {"amount_minor": CEILING, "currency": "INR"},
    }


async def test_price_range_requires_a_scan_and_a_feasible_offer(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_range_errors")
    unscanned = await machine(api, headers, "empty")
    body = {**OFFER, "tier": "standard"}
    response = await api.client.post(
        f"/v1/provider/machines/{unscanned}/price-range", json=body, headers=headers
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "inventory_required")

    scanned, _ = await scanned_machine(api, headers, "full")
    response = await api.client.post(
        f"/v1/provider/machines/{scanned}/price-range",
        json={**body, "cpu_cores": 32},
        headers=headers,
    )
    assert response.json()["error"]["code"] == "allocation_exceeds_capacity"
    missing_tier = await api.client.post(
        f"/v1/provider/machines/{scanned}/price-range", json=OFFER, headers=headers
    )
    assert missing_tier.status_code == 422


async def test_a_provider_can_choose_any_price_inside_the_range(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_market")
    machine_id, _ = await scanned_machine(api, headers)
    for price in (FLOOR, 9800, CEILING, FLOOR + 1):
        response = await put_listing(api, headers, machine_id, listing(price))
        assert response.status_code == 200, (price, response.text)
        body = response.json()
        assert body["status"] == "listed"
        assert body["listing"]["tier"] == "standard"
        assert body["listing"]["price_per_hour"] == {"amount_minor": price, "currency": "INR"}
        assert body["listing"]["gpu_indices"] == [0]


async def test_prices_outside_the_range_are_rejected(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_outside")
    machine_id, _ = await scanned_machine(api, headers)
    for price in (FLOOR - 1, CEILING + 1, 1, 10**9):
        response = await put_listing(api, headers, machine_id, listing(price))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "price_out_of_range"
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    assert (detail["status"], detail["listing"]) == ("registered", None)


async def test_prices_must_be_whole_positive_numbers(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_price_types")
    machine_id, _ = await scanned_machine(api, headers)
    for price in (0, -5, 99.5, "9800"):
        response = await put_listing(api, headers, machine_id, listing(price))  # type: ignore[arg-type]
        assert response.status_code == 422, price


async def test_listing_rules_beyond_price(api: ClientHandle, tokens: TokenFactory) -> None:
    headers = await provider(api, tokens, "user_rules")
    unscanned = await machine(api, headers, "unscanned")
    assert (await put_listing(api, headers, unscanned, listing(9800))).json()["error"][
        "code"
    ] == "inventory_required"

    machine_id, _ = await scanned_machine(api, headers)
    cases = {
        "max_hosting_hours_exceeded": listing(9800, max_hosting_hours=100_000),
        "allocation_exceeds_capacity": listing(9800, gpu_indices=[3]),
    }
    for code, body in cases.items():
        response = await put_listing(api, headers, machine_id, body)
        assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    duplicate_gpu = await put_listing(api, headers, machine_id, listing(9800, gpu_indices=[0, 0]))
    assert duplicate_gpu.json()["error"]["code"] == "allocation_exceeds_capacity"
    bad_tier = await put_listing(api, headers, machine_id, listing(9800, tier="premium"))
    assert bad_tier.status_code == 422


# --- tiers ----------------------------------------------------------------------------------

NO_GPU: dict[str, Any] = {**OFFER, "gpu_indices": []}
# Standard base 2600 (floor 1820, ceiling 3900); confidential base 3900 (floor 2730, ceiling 5850).


async def test_confidential_prices_are_higher_than_standard_for_the_same_offer(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_tiers")
    machine_id, _ = await scanned_machine(api, headers)
    path = f"/v1/provider/machines/{machine_id}/price-range"
    standard = (
        await api.client.post(path, json={**NO_GPU, "tier": "standard"}, headers=headers)
    ).json()
    await set_db(api, "UPDATE machines SET confidential_verified_at = now()")
    confidential = (
        await api.client.post(path, json={**NO_GPU, "tier": "confidential"}, headers=headers)
    ).json()
    assert standard["base"]["amount_minor"] == 2600
    assert confidential["base"]["amount_minor"] == 3900
    assert confidential["floor"]["amount_minor"] > standard["floor"]["amount_minor"]
    assert confidential["ceiling"]["amount_minor"] > standard["ceiling"]["amount_minor"]


async def test_confidential_listing_requires_platform_attestation(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_attest")
    machine_id, _ = await scanned_machine(api, headers)
    body = listing(3000, "confidential", gpu_indices=[])
    denied = await put_listing(api, headers, machine_id, body)
    assert (denied.status_code, denied.json()["error"]["code"]) == (422, "attestation_required")

    await set_db(api, "UPDATE machines SET confidential_verified_at = now()")
    detail = (await api.client.get(f"/v1/provider/machines/{machine_id}", headers=headers)).json()
    assert detail["confidential_verified"] is True
    accepted = await put_listing(api, headers, machine_id, body)
    assert accepted.status_code == 200
    assert accepted.json()["listing"]["tier"] == "confidential"
    assert (
        await put_listing(api, headers, machine_id, listing(1900, "confidential", gpu_indices=[]))
    ).json()["error"][
        "code"
    ] == "price_out_of_range"  # 1900 is a valid standard price but below the confidential floor


async def test_confidential_listing_cannot_include_gpus_yet(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_cc_gpu")
    machine_id, _ = await scanned_machine(api, headers)
    await set_db(api, "UPDATE machines SET confidential_verified_at = now()")
    response = await put_listing(api, headers, machine_id, listing(9800, "confidential"))
    assert response.json()["error"]["code"] == "confidential_gpu_unsupported"


async def test_confidential_listing_requires_reported_hardware_support(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_cc_flags")
    machine_id = await machine(api, headers)
    agent = await enrolled_agent(api, headers, machine_id)
    no_flags = mutated(["security", "confidential_computing_flags"], [])
    assert (await run_scan(api, headers, agent, no_flags)).status_code == 200
    await set_db(api, "UPDATE machines SET confidential_verified_at = now()")
    response = await put_listing(
        api, headers, machine_id, listing(3000, "confidential", gpu_indices=[])
    )
    assert response.json()["error"]["code"] == "confidential_not_supported"


async def test_a_rescan_that_loses_confidential_support_pauses_the_listing(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_cc_lost")
    machine_id, agent = await scanned_machine(api, headers)
    await set_db(api, "UPDATE machines SET confidential_verified_at = now()")
    await put_listing(api, headers, machine_id, listing(3000, "confidential", gpu_indices=[]))
    result = await run_scan(
        api, headers, agent, mutated(["security", "confidential_computing_flags"], [])
    )
    assert result.json()["listing_paused"] is True
    base = f"/v1/provider/machines/{machine_id}"
    assert (await api.client.get(base, headers=headers)).json()["status"] == "paused"
    assert (await api.client.post(f"{base}/resume", headers=headers)).json()["error"][
        "code"
    ] == "confidential_not_supported"


# --- lifecycle ------------------------------------------------------------------------------


async def test_pause_resume_withdraw_lifecycle(api: ClientHandle, tokens: TokenFactory) -> None:
    headers = await provider(api, tokens, "user_life")
    machine_id, agent = await scanned_machine(api, headers)
    base = f"/v1/provider/machines/{machine_id}"

    resume_early = await api.client.post(f"{base}/resume", headers=headers)
    assert resume_early.status_code == 422  # registered -> listed needs a listing first
    assert (await api.client.post(f"{base}/pause", headers=headers)).status_code == 409

    await put_listing(api, headers, machine_id, listing(9800))
    paused = await api.client.post(f"{base}/pause", headers=headers)
    assert paused.json()["status"] == "paused"
    assert (await api.client.post(f"{base}/pause", headers=headers)).status_code == 409
    resumed = await api.client.post(f"{base}/resume", headers=headers)
    assert resumed.json()["status"] == "listed"

    withdrawn = await api.client.post(f"{base}/withdraw", headers=headers)
    assert withdrawn.json()["status"] == "withdrawn"
    for response in (
        await api.client.post(f"{base}/resume", headers=headers),
        await api.client.post(f"{base}/pause", headers=headers),
        await api.client.post(f"{base}/withdraw", headers=headers),
        await put_listing(api, headers, machine_id, listing(9800)),
        await api.client.post(f"{base}/enrollment", headers=headers),
        await api.client.post(f"{base}/scans", headers=headers),
    ):
        assert response.status_code == 409
    assert (await api.client.get(base, headers=headers)).json()["listing"] is not None
    # a withdrawn machine's agent is locked out
    assert (await agent.claim()).status_code == 401


async def test_a_smaller_rescan_pauses_a_listing_that_no_longer_fits(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_downgrade")
    machine_id, agent = await scanned_machine(api, headers)
    await put_listing(api, headers, machine_id, listing(9800))
    base = f"/v1/provider/machines/{machine_id}"

    same = await run_scan(api, headers, agent)
    assert same.json()["listing_paused"] is False
    assert (await api.client.get(base, headers=headers)).json()["status"] == "listed"

    smaller = mutated(["cpu", "logical_cores"], 4)  # cannot supply 8 cores any more
    smaller["cpu"]["physical_cores"] = 4
    result = await run_scan(api, headers, agent, smaller)
    assert result.json()["listing_paused"] is True
    assert (await api.client.get(base, headers=headers)).json()["status"] == "paused"
    blocked = await api.client.post(f"{base}/resume", headers=headers)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (
        422,
        "allocation_exceeds_capacity",
    )


async def test_a_rescan_that_changes_the_gpu_price_band_pauses_an_out_of_band_listing(
    api: ClientHandle, tokens: TokenFactory
) -> None:
    headers = await provider(api, tokens, "user_band")
    machine_id, agent = await scanned_machine(api, headers)
    await put_listing(api, headers, machine_id, listing(CEILING))
    body = json.loads(json.dumps(EXAMPLE))
    body["gpus"][0]["memory_total_bytes"] = 8 * GIB  # base falls, old ceiling price is too high
    result = await run_scan(api, headers, agent, body)
    assert result.json()["listing_paused"] is True
