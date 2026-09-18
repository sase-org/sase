"""Public façade for the isolated visual candidate-capture protocol.

``tools/fix_tui_screenshots`` enables this protocol through the governed
visual runner, then compares and applies candidate goldens.
"""

from __future__ import annotations

from tests.ace.tui.visual._visual_capture_paths import (
    ACE_TEST_PREFIX as ACE_TEST_PREFIX,
    DEFAULT_ACE_ROOT as DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT as DEFAULT_PAGER_ROOT,
    PAGER_TEST_PREFIX as PAGER_TEST_PREFIX,
    PLUGIN_NAME as PLUGIN_NAME,
    SCHEMA_VERSION as SCHEMA_VERSION,
    VisualCaptureError as VisualCaptureError,
    VisualCaptureRoots as VisualCaptureRoots,
    capture_artifact_id as capture_artifact_id,
    canonical_golden_path as canonical_golden_path,
    hash_file_tree as hash_file_tree,
    png_dimensions as png_dimensions,
    sanitize_worker_id as sanitize_worker_id,
    sha256_bytes as sha256_bytes,
    visual_root_for_nodeid as visual_root_for_nodeid,
    worker_directory as worker_directory,
)
from tests.ace.tui.visual._visual_capture_store import (
    CaptureRecord as CaptureRecord,
    ComparisonSettings as ComparisonSettings,
    InventoryReport as InventoryReport,
    VisualCaptureSession as VisualCaptureSession,
    WorkerSessionRecord as WorkerSessionRecord,
    evaluate_inventory as evaluate_inventory,
    load_inventory as load_inventory,
    merge_capture_dir as merge_capture_dir,
    write_inventory as write_inventory,
)


__all__ = [
    "ACE_TEST_PREFIX",
    "DEFAULT_ACE_ROOT",
    "DEFAULT_PAGER_ROOT",
    "PAGER_TEST_PREFIX",
    "PLUGIN_NAME",
    "SCHEMA_VERSION",
    "CaptureRecord",
    "ComparisonSettings",
    "InventoryReport",
    "VisualCaptureError",
    "VisualCaptureRoots",
    "VisualCaptureSession",
    "WorkerSessionRecord",
    "capture_artifact_id",
    "canonical_golden_path",
    "evaluate_inventory",
    "hash_file_tree",
    "load_inventory",
    "merge_capture_dir",
    "png_dimensions",
    "sanitize_worker_id",
    "sha256_bytes",
    "visual_root_for_nodeid",
    "worker_directory",
    "write_inventory",
]
