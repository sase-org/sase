"""Compatibility facade for immutable incoming-cache operations."""

from sase.agents_sync.incoming_cache_legacy import (
    legacy_family_count,
    legacy_group_digest,
    legacy_group_machine_hood,
    legacy_manifest_groups,
)
from sase.agents_sync.incoming_cache_metadata import (
    cache_id_for as _cache_id_for,
    captured_incoming_hood_from_json,
    receipt_matches,
    with_cache_id,
)
from sase.agents_sync.incoming_cache_receipts import (
    read_project_receipts,
    receipt_for_item,
    write_import_receipt,
)
from sase.agents_sync.incoming_cache_storage import (
    cached_item_is_available,
    find_cached_evidence,
    load_validated_cache_item,
    prune_project_cache,
    publish_cache_object,
    reconcile_pending_items,
    validate_unpublished_cache_payload,
)

__all__ = [
    "cached_item_is_available",
    "captured_incoming_hood_from_json",
    "find_cached_evidence",
    "legacy_family_count",
    "legacy_group_digest",
    "legacy_group_machine_hood",
    "legacy_manifest_groups",
    "load_validated_cache_item",
    "prune_project_cache",
    "publish_cache_object",
    "read_project_receipts",
    "receipt_for_item",
    "receipt_matches",
    "reconcile_pending_items",
    "validate_unpublished_cache_payload",
    "with_cache_id",
    "write_import_receipt",
]
