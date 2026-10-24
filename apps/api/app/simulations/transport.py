"""The only transport the simulator has: a deterministic fake (P4.5, ADR-024). No network, token or provider.

`live_transport()` exists so that any attempt to reach a real provider fails loudly. Nothing configures it, and
`HERMECIOUS_LIVE_OUTBOUND_ENABLED` (or any other setting) cannot enable it before P5.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal, NoReturn

MAX_ATTEMPTS = 3


class LiveTransportForbidden(RuntimeError):
    """Raised for any attempt to obtain a real WhatsApp transport in P4.x."""


@dataclass(frozen=True)
class FakeResult:
    status: Literal["accepted", "rate_limited", "timeout"]
    sim_receipt_id: str | None = None


class FakeWhatsAppTransport:
    """Deterministic: the same logical item always yields the same `sim-` receipt, so retries add no effects."""

    name = "fake-whatsapp-v1"

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    def submit(self, *, run_id: str, account_id: str, content_digest: str, attempt: int) -> FakeResult:
        if self.scenario == "transport_timeout_mock":
            return FakeResult("timeout")
        if self.scenario == "provider_429_mock" and attempt == 1:
            return FakeResult("rate_limited")
        logical = hashlib.sha256(f"{run_id}:{account_id}:{content_digest}".encode()).hexdigest()
        return FakeResult("accepted", f"sim-{logical[:24]}")


def live_transport(*_args: object, **_kwargs: object) -> NoReturn:
    raise LiveTransportForbidden("live WhatsApp transport does not exist before P5; the simulator is zero-egress")
