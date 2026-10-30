"""Shared constants and types for agents publication protection."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agents_sync.v2_validation import MAX_TEXT_BYTES

AGENT_PUBLICATION_PROTECTION_FILENAME = "agents-publication-protection.json"
PRIVATE_SCAN_STAGING_DIRECTORY = "agents-publication-scans"

# Bound for one in-memory publication candidate. Matches the v2 text limit so
# oversized text is withheld as unverified instead of raising scanner limits.
MAX_PUBLICATION_SCAN_BYTES = MAX_TEXT_BYTES


@dataclass(frozen=True, slots=True)
class PublicationBytesVerdict:
    """One in-memory candidate's digest and scan decision.

    Callers must only publish the exact bytes this verdict was computed from
    after checking :attr:`is_publishable`.
    """

    sha256: str | None
    byte_count: int | None
    disposition: dict[str, object] | None

    @property
    def is_publishable(self) -> bool:
        return (
            self.sha256 is not None
            and self.disposition is not None
            and self.disposition.get("status") == "clean"
        )


@dataclass(frozen=True, slots=True)
class PublicationProtectionScope:
    """Project-scoped identity for protection ledger reads and writes."""

    project_key: str
    repository_identity: str
    max_bytes: int = MAX_PUBLICATION_SCAN_BYTES
