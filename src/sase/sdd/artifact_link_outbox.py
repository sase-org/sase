"""Machine-local operation journal for artifact-link mutations.

Queue records, JSONL persistence, sidecar index writes, and drain
orchestration live in sibling modules so this file stays the public API.
"""

from sase.sdd._artifact_link_outbox_drain import drain_artifact_link_outbox
from sase.sdd._artifact_link_outbox_io import (
    append_artifact_link_outbox_entry,
    append_artifact_link_outbox_event,
    inspect_artifact_link_outbox,
)
from sase.sdd._artifact_link_outbox_types import (
    ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME,
    ARTIFACT_LINK_OUTBOX_FILENAME,
    ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
)

__all__ = [
    "ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME",
    "ARTIFACT_LINK_OUTBOX_FILENAME",
    "ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION",
    "append_artifact_link_outbox_event",
    "append_artifact_link_outbox_entry",
    "drain_artifact_link_outbox",
    "inspect_artifact_link_outbox",
]
