"""Client IP resolution that cannot be spoofed through X-Forwarded-For."""

from starlette.requests import Request

_UNKNOWN = "unknown"


def resolve_client_ip(request: Request, trusted_proxy_count: int) -> str:
    """Return the client address as seen by the outermost trusted proxy.

    With N trusted proxies each appending to X-Forwarded-For, the real client is the Nth entry
    from the right; anything further left is client-controlled and is ignored. With zero trusted
    proxies the header is ignored entirely and the socket peer address is used.
    """
    peer = request.client.host if request.client else _UNKNOWN
    if trusted_proxy_count == 0:
        return peer
    forwarded = [
        entry.strip()
        for value in request.headers.getlist("x-forwarded-for")
        for entry in value.split(",")
        if entry.strip()
    ]
    if len(forwarded) < trusted_proxy_count:
        return peer
    return forwarded[-trusted_proxy_count]
