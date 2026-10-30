"""Completed-provider evidence for deferred finalizer completion.

A reviewed workflow prompt step obtains its provider result first and runs
finalizer settlement later through the host-owned workflow completion seam.
The evidence below proves a provider turn actually completed at this step:
it is recorded by the deferred :func:`invoke_agent` branch from the live
turn nonce and the completed response bytes, and the seam takes it exactly
once under an explicit caller-supplied token. Agent steps cannot stage a
host review without it; script steps carry no provider evidence.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderEvidence:
    """Proof that one provider turn completed for a reviewed prompt step."""

    agent_type: str
    turn_nonce: str
    response_sha256: str
    response_chars: int

    def to_wire(self) -> str:
        """Render the evidence as one admission wire string."""
        return (
            f"agent:{self.agent_type} "
            f"nonce:{self.turn_nonce} "
            f"sha256:{self.response_sha256} "
            f"chars:{self.response_chars}"
        )


def digest_response(content: str) -> tuple[str, int]:
    """Return the ``(sha256, chars)`` identity of a completed response."""
    encoded = content.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(content)


_lock = threading.Lock()
_pending: dict[str, ProviderEvidence] = {}


def record_deferred_provider_evidence(
    token: str,
    evidence: ProviderEvidence,
) -> None:
    """Stash *evidence* under *token* until the completion seam takes it."""
    with _lock:
        _pending[token] = evidence


def take_deferred_provider_evidence(token: str) -> ProviderEvidence | None:
    """Take and clear the evidence stashed under *token*, if any."""
    with _lock:
        return _pending.pop(token, None)


__all__ = [
    "ProviderEvidence",
    "digest_response",
    "record_deferred_provider_evidence",
    "take_deferred_provider_evidence",
]
