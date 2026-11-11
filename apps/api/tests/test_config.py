from collections.abc import Callable

import pytest
from pydantic import ValidationError

from auren_api.config import Environment, RateLimitRule, Settings


def test_rate_limits_parse_from_environment_form(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("AUREN_RATE_LIMIT_UPLOAD", "7/90")
    base = make_settings()
    settings = Settings(  # pyright: ignore[reportCallIssue]
        environment=base.environment,
        database_url=base.database_url,
        redis_url=base.redis_url,
        clerk_issuer=base.clerk_issuer,
    )
    assert settings.rate_limit_upload == RateLimitRule(limit=7, window_seconds=90)


@pytest.mark.parametrize("value", ["", "10", "10/", "/60", "a/b", "0/60", "10/0", "-1/60"])
def test_invalid_rate_limit_is_rejected(make_settings: Callable[..., Settings], value: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(rate_limit_anonymous=value)


def test_origins_accept_comma_separated_and_normalise(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        cors_allowed_origins="https://a.example.com, http://localhost:5173/",
    )
    assert settings.cors_allowed_origins == ["https://a.example.com", "http://localhost:5173"]


@pytest.mark.parametrize(
    "origin", ["*", "https://*.example.com", "https://a.example.com/path", "ftp://a.example.com"]
)
def test_unsafe_origins_are_rejected(make_settings: Callable[..., Settings], origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(cors_allowed_origins=[origin])


@pytest.mark.parametrize(
    "url", ["postgresql://u:p@h/db", "postgres://u:p@h/db", "mysql+aiomysql://u:p@h/db"]
)
def test_database_url_requires_asyncpg_driver(
    make_settings: Callable[..., Settings], url: str
) -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url=url)


def test_redis_url_requires_redis_scheme(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(redis_url="http://localhost:6379")


@pytest.mark.parametrize("issuer", ["http://clerk.example.com", "clerk.example.com", "https://"])
def test_issuer_must_be_https_url(make_settings: Callable[..., Settings], issuer: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(clerk_issuer=issuer)


def test_issuer_trailing_slash_is_removed_and_jwks_url_derived(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(clerk_issuer="https://clerk.example.com/")
    assert settings.clerk_issuer == "https://clerk.example.com"
    assert settings.clerk_jwks_url == "https://clerk.example.com/.well-known/jwks.json"


def test_production_requires_authorized_parties(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="clerk_authorized_parties"):
        make_settings(environment=Environment.PRODUCTION, clerk_authorized_parties=[])
    assert make_settings(environment=Environment.PRODUCTION).is_production


def test_empty_audience_means_not_configured(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(clerk_audience="").clerk_audience is None


def test_secrets_are_not_exposed_in_repr(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.database_url.get_secret_value() not in repr(settings)
    assert settings.redis_url.get_secret_value() not in repr(settings)


def test_unknown_setting_is_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(not_a_setting=1)
