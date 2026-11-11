"""Cross-cutting HTTP behaviour: errors, headers, CORS, body limits, health, docs exposure."""

import dataclasses
from collections.abc import AsyncIterator, Callable

from redis.asyncio import Redis

from auren_api.config import Environment, Settings
from tests.conftest import ClientHandle
from tests.support import AUTHORIZED_PARTY


async def test_health_live(api: ClientHandle) -> None:
    response = await api.client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_ready_reports_dependencies(api: ClientHandle) -> None:
    response = await api.client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_ready_fails_when_redis_is_unreachable(api: ClientHandle) -> None:
    container = api.app.state.container
    unreachable = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2
    )
    api.app.state.container = dataclasses.replace(container, redis=unreachable)
    response = await api.client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "redis": "failed"},
    }
    await unreachable.aclose()


async def test_ready_fails_when_database_is_unreachable(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(
        make_settings(database_url="postgresql+asyncpg://nobody:nopass@127.0.0.1:1/none")
    ).start(reset_database=False)
    response = await handle.client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"
    assert response.json()["checks"]["redis"] == "ok"


async def test_unknown_route_uses_the_error_format(api: ClientHandle) -> None:
    response = await api.client.get("/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["details"] == []


async def test_wrong_method_uses_the_error_format(api: ClientHandle) -> None:
    response = await api.client.post("/health/live")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_security_headers_are_present_on_success_and_errors(api: ClientHandle) -> None:
    for path in ("/health/live", "/v1/me", "/does-not-exist"):
        headers = (await api.client.get(path)).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert headers["Cache-Control"] == "no-store"
        assert "Strict-Transport-Security" not in headers


async def test_hsts_and_hidden_schema_in_production(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings(environment=Environment.PRODUCTION)).start()
    response = await handle.client.get("/health/live")
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
    assert (await handle.client.get("/openapi.json")).status_code == 404
    assert (await handle.client.get("/docs")).status_code == 404


async def test_openapi_schema_is_available_outside_production(api: ClientHandle) -> None:
    response = await api.client.get("/openapi.json")
    assert response.status_code == 200
    assert "/v1/me" in response.json()["paths"]


async def test_request_id_is_generated_and_safe_values_are_echoed(api: ClientHandle) -> None:
    generated = await api.client.get("/health/live")
    assert len(generated.headers["X-Request-ID"]) == 32

    echoed = await api.client.get("/health/live", headers={"X-Request-ID": "trace-abc.123_XYZ"})
    assert echoed.headers["X-Request-ID"] == "trace-abc.123_XYZ"

    unsafe = await api.client.get("/health/live", headers={"X-Request-ID": "bad id\r\ninjected"})
    assert unsafe.headers["X-Request-ID"] != "bad id\r\ninjected"
    assert len(unsafe.headers["X-Request-ID"]) == 32


async def test_cors_allows_only_configured_origins(api: ClientHandle) -> None:
    preflight = await api.client.options(
        "/v1/me",
        headers={
            "Origin": AUTHORIZED_PARTY,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == AUTHORIZED_PARTY
    assert "access-control-allow-credentials" not in preflight.headers

    denied = await api.client.get("/health/live", headers={"Origin": "https://evil.example.test"})
    assert "access-control-allow-origin" not in denied.headers


async def test_cors_is_off_without_configured_origins(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings(cors_allowed_origins=[])).start()
    response = await handle.client.get("/health/live", headers={"Origin": AUTHORIZED_PARTY})
    assert "access-control-allow-origin" not in response.headers


async def test_oversized_declared_body_is_rejected(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings(max_request_body_bytes=100)).start()
    response = await handle.client.post("/health/live", content=b"x" * 101)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_oversized_streamed_body_is_rejected(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings(max_request_body_bytes=100)).start()

    @handle.app.post("/echo-test-route")
    async def echo(payload: dict[str, str]) -> dict[str, str]:
        return payload

    async def body() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 40

    response = await handle.client.post(
        "/echo-test-route", content=body(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_invalid_content_length_is_rejected(api: ClientHandle) -> None:
    response = await api.client.post("/health/live", content=b"", headers={"Content-Length": "abc"})
    assert response.status_code == 400


async def test_validation_errors_use_the_error_format_without_echoing_input(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings()).start()

    @handle.app.post("/validated-test-route")
    async def validated(payload: dict[str, int]) -> dict[str, int]:
        return payload

    response = await handle.client.post(
        "/validated-test-route", json={"secret-field": "not-an-int-sensitive"}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["location"][0] == "body"
    assert "not-an-int-sensitive" not in response.text


async def test_unhandled_exceptions_return_a_generic_500(
    make_settings: Callable[..., Settings], make_client: Callable[[Settings], ClientHandle]
) -> None:
    handle = await make_client(make_settings()).start()

    @handle.app.get("/boom-test-route")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    response = await handle.client.get("/boom-test-route")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
