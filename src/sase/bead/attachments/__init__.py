"""Local content-addressed store for bead attachment bytes.

Note: :mod:`sase.attachments` (top level) is unrelated — it serves agent
file attachments for prompts. This package is the ``~/.sase/attachments``
content-addressed store from the bead-note-attachments epic.
"""

from sase.bead.attachments.blob_store import BlobStore, BlobStoreError, ProgressCallback
from sase.bead.attachments.images import ImageDims, probe_image
from sase.bead.attachments.ingest import (
    IngestedBlob,
    IngestError,
    ingest_path,
    ingest_stream,
)
from sase.bead.attachments.store import (
    LocalAttachmentStore,
    default_store_root,
    validate_sha256,
)

__all__ = [
    "BlobStore",
    "BlobStoreError",
    "ImageDims",
    "IngestedBlob",
    "IngestError",
    "LocalAttachmentStore",
    "ProgressCallback",
    "default_store_root",
    "ingest_path",
    "ingest_stream",
    "probe_image",
    "validate_sha256",
]
