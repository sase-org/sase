"""Placement, pre-publication upload, and outbox drain for attachments.

Placement uses the core ``attachment_placement`` policy with the single git
tier; Python owns I/O. Uploads run after the bead commit and before bead
publication (``bead_store_mutation``), with a durable outbox that
``attachment push`` and bead sync drain.
"""

from __future__ import annotations

from sase.bead.attachments.upload.discovery import (
    clone_has_remote,
    describe_label,
    discover_large_store,
    discover_shared_store,
    discover_shared_store_with_meta,
    discover_stores,
    hidden_clone_path,
    resolve_project_key,
)
from sase.bead.attachments.upload.echo import (
    rewrite_echo_for_local,
    rewrite_echo_for_public_pending,
    rewrite_echo_for_upload,
)
from sase.bead.attachments.upload.errors import (
    AttachmentStoreMissingError,
    AttachmentTooLargeError,
)
from sase.bead.attachments.upload.placement import (
    decide_placement,
    placement_tiers,
    prepare_placement,
    split_wires_by_tier,
)
from sase.bead.attachments.upload.protocol import (
    drain_before_upload,
    post_write_queue,
    pre_write_upload,
    promote_local_only,
)
from sase.bead.attachments.upload.transfer import (
    queue_pending_upload,
    run_pending_uploads,
    upload_wires_now,
)

__all__ = [
    "AttachmentStoreMissingError",
    "AttachmentTooLargeError",
    "clone_has_remote",
    "decide_placement",
    "describe_label",
    "discover_large_store",
    "discover_shared_store",
    "discover_shared_store_with_meta",
    "discover_stores",
    "drain_before_upload",
    "hidden_clone_path",
    "placement_tiers",
    "post_write_queue",
    "pre_write_upload",
    "prepare_placement",
    "promote_local_only",
    "queue_pending_upload",
    "resolve_project_key",
    "rewrite_echo_for_local",
    "rewrite_echo_for_public_pending",
    "rewrite_echo_for_upload",
    "run_pending_uploads",
    "split_wires_by_tier",
    "upload_wires_now",
]
