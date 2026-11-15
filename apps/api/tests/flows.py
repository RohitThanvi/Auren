"""Shared end-to-end flows for API tests: provider setup, agent enrolment and platform scans."""

import json
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from tests.agent_client import TestAgent
from tests.conftest import ClientHandle
from tests.support import TokenFactory

GIB = 1024**3
EXAMPLE = json.loads(
    (Path(__file__).resolve().parents[3] / "packages/contracts/examples/inventory.json").read_text()
)
# Example machine: 32 cores, 64 GiB RAM, one 24 GiB GPU, 1000 GiB storage.
# Rates in tests/support.py -> base for the offer below is 9800; band is 6860..14700.
OFFER: dict[str, Any] = {
    "cpu_cores": 8,
    "memory_bytes": 16 * GIB,
    "gpu_indices": [0],
    "storage_bytes": 200 * GIB,
}
FLOOR, CEILING = 6860, 14700


def auth(tokens: TokenFactory, subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.token(subject)}"}


async def provider(api: ClientHandle, tokens: TokenFactory, subject: str) -> dict[str, str]:
    headers = auth(tokens, subject)
    response = await api.client.post("/v1/provider/enable", headers=headers)
    assert response.status_code == 200, response.text
    return headers


async def machine(api: ClientHandle, headers: dict[str, str], name: str = "rig-1") -> str:
    response = await api.client.post("/v1/provider/machines", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def enrolled_agent(api: ClientHandle, headers: dict[str, str], machine_id: str) -> TestAgent:
    issued = await api.client.post(
        f"/v1/provider/machines/{machine_id}/enrollment", headers=headers
    )
    assert issued.status_code == 200, issued.text
    agent = TestAgent(api, machine_id)
    enrolled = await agent.enroll(issued.json()["enrollment_token"])
    assert enrolled.status_code == 200, enrolled.text
    return agent


async def run_scan(
    api: ClientHandle,
    headers: dict[str, str],
    agent: TestAgent,
    report: dict[str, Any] = EXAMPLE,
) -> httpx.Response:
    """Provider requests a scan; the agent claims, answers the challenge and submits."""
    requested = await api.client.post(
        f"/v1/provider/machines/{agent.machine_id}/scans", headers=headers
    )
    assert requested.status_code == 201, requested.text
    claimed = await agent.claim()
    assert claimed.status_code == 200, claimed.text
    return await agent.submit(claimed.json()["scan_id"], report, TestAgent.answer(claimed.json()))


async def scanned_machine(
    api: ClientHandle, headers: dict[str, str], name: str = "rig-1"
) -> tuple[str, TestAgent]:
    machine_id = await machine(api, headers, name)
    agent = await enrolled_agent(api, headers, machine_id)
    result = await run_scan(api, headers, agent)
    assert result.status_code == 200, result.text
    return machine_id, agent


def listing(price: int, tier: str = "standard", **overrides: Any) -> dict[str, Any]:
    return {
        **OFFER,
        "tier": tier,
        "price_per_hour_minor": price,
        "max_hosting_hours": 24,
        **overrides,
    }


async def put_listing(
    api: ClientHandle, headers: dict[str, str], machine_id: str, body: dict[str, Any]
) -> httpx.Response:
    return await api.client.put(
        f"/v1/provider/machines/{machine_id}/listing", json=body, headers=headers
    )


async def set_db(api: ClientHandle, sql: str, **params: Any) -> None:
    async with api.app.state.container.engine.begin() as connection:
        await connection.execute(text(sql), params)
