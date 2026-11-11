"""Run the API: ``python -m auren_api``."""

import uvicorn

from auren_api.config import get_settings
from auren_api.main import create_app


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,  # logging is configured by the application (structlog)
        access_log=False,  # requests are logged by RequestContextMiddleware
        proxy_headers=False,  # X-Forwarded-For is handled explicitly via TRUSTED_PROXY_COUNT
    )


if __name__ == "__main__":
    main()
