"""Payment gateway abstraction.

No gateway is selected yet (see docs/DECISIONS.md, ADR-0006). A concrete adapter must be added
only after the gateway's API and account requirements are verified. The platform never handles
card numbers, UPI PINs, or bank credentials; the gateway does.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from auren_api.domain.money import Money


class InvalidWebhookSignatureError(Exception):
    """Raised when a webhook cannot be authenticated. Such events must be discarded."""


@dataclass(frozen=True, slots=True)
class ProviderOrder:
    provider_order_id: str
    amount: Money


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """An authenticated gateway event. ``provider_event_id`` is the deduplication key."""

    provider_event_id: str
    event_type: str
    provider_order_id: str | None
    amount: Money | None


class PaymentProvider(Protocol):
    name: str

    async def create_order(
        self, *, amount: Money, idempotency_key: str, reference: str
    ) -> ProviderOrder:
        """Create a payment order. The amount is computed server-side, never taken from clients."""
        ...

    def verify_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verify the signature over the raw body and parse the event.

        Raises ``InvalidWebhookSignatureError`` if authentication fails.
        """
        ...
