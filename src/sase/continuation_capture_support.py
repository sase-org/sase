"""Compatibility shim for continuation capture storage helpers."""

from __future__ import annotations

from sase.continuation_capture._storage import (
    continuation_root,
    json_safe,
    local_ref,
    optional_float,
    optional_int,
    optional_str,
    read_json_object,
    record_capture_error,
    required_text,
    safe_identifier,
    sha_json,
    sha_text,
    source_ref,
    unique_identifiers,
    unique_refs,
    update_agent_meta_fields,
    wire_reference,
    wire_reference_or_none,
    write_json_atomic,
    write_text_blob,
)
from sase.continuation_capture.checkpoints import publish_handoff_checkpoint


__all__ = [
    "continuation_root",
    "json_safe",
    "local_ref",
    "optional_float",
    "optional_int",
    "optional_str",
    "publish_handoff_checkpoint",
    "read_json_object",
    "record_capture_error",
    "required_text",
    "safe_identifier",
    "sha_json",
    "sha_text",
    "source_ref",
    "unique_identifiers",
    "unique_refs",
    "update_agent_meta_fields",
    "wire_reference",
    "wire_reference_or_none",
    "write_json_atomic",
    "write_text_blob",
]
