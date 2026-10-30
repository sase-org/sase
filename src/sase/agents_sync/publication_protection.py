"""Private state and fail-closed scanner adapter for agents publication."""

from __future__ import annotations

from sase.agents_sync._publication_protection_ledger import (
    lookup_publication_content_record,
    publication_content_retry_allowed,
    read_publication_protection_ledger_from_path,
    record_publication_bytes_scan,
    record_publication_push_rejection,
    record_publication_scan,
)
from sase.agents_sync._publication_protection_models import (
    AGENT_PUBLICATION_PROTECTION_FILENAME,
    MAX_PUBLICATION_SCAN_BYTES,
    PRIVATE_SCAN_STAGING_DIRECTORY,
    PublicationBytesVerdict,
    PublicationProtectionScope,
)
from sase.agents_sync._publication_protection_scan import (
    ScannedPublicationCandidate,
    scan_publication_bytes,
    scan_publication_candidate,
)

__all__ = [
    "AGENT_PUBLICATION_PROTECTION_FILENAME",
    "MAX_PUBLICATION_SCAN_BYTES",
    "PRIVATE_SCAN_STAGING_DIRECTORY",
    "PublicationBytesVerdict",
    "PublicationProtectionScope",
    "ScannedPublicationCandidate",
    "lookup_publication_content_record",
    "publication_content_retry_allowed",
    "read_publication_protection_ledger_from_path",
    "record_publication_bytes_scan",
    "record_publication_push_rejection",
    "record_publication_scan",
    "scan_publication_bytes",
    "scan_publication_candidate",
]
