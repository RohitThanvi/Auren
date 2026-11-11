import pytest
from starlette.requests import Request

from auren_api.api.client_ip import resolve_client_ip


def make_request(peer: str | None, forwarded: list[str]) -> Request:
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", value.encode()) for value in forwarded],
        "client": (peer, 5000) if peer else None,
    }
    return Request(scope)


def test_header_is_ignored_without_trusted_proxies() -> None:
    request = make_request("10.0.0.9", ["6.6.6.6"])
    assert resolve_client_ip(request, 0) == "10.0.0.9"


@pytest.mark.parametrize(
    ("trusted", "header", "expected"),
    [
        (1, "203.0.113.7", "203.0.113.7"),
        (1, "6.6.6.6, 203.0.113.7", "203.0.113.7"),  # client-supplied prefix is ignored
        (2, "6.6.6.6, 203.0.113.7, 10.1.1.1", "203.0.113.7"),
        (2, " 203.0.113.7 , 10.1.1.1 ", "203.0.113.7"),
    ],
)
def test_nth_entry_from_the_right_is_the_client(trusted: int, header: str, expected: str) -> None:
    request = make_request("10.0.0.9", [header])
    assert resolve_client_ip(request, trusted) == expected


def test_multiple_header_lines_are_combined() -> None:
    request = make_request("10.0.0.9", ["6.6.6.6", "203.0.113.7"])
    assert resolve_client_ip(request, 1) == "203.0.113.7"


def test_short_header_falls_back_to_peer() -> None:
    request = make_request("10.0.0.9", ["203.0.113.7"])
    assert resolve_client_ip(request, 2) == "10.0.0.9"


def test_missing_peer_is_reported_as_unknown() -> None:
    assert resolve_client_ip(make_request(None, []), 0) == "unknown"
