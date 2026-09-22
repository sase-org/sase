"""Backward-compatible re-exports for the split capture store.

The implementation now lives in :mod:`_visual_capture_records` (versioned
record dataclasses and dict serde), :mod:`_visual_capture_session`
(worker-local candidate writes), and :mod:`_visual_capture_inventory`
(inventory merge and completeness evaluation). This module re-exports the
public names so existing imports keep working.
"""

from __future__ import annotations

from tests.ace.tui.visual._visual_capture_inventory import (
    evaluate_inventory as evaluate_inventory,
    load_inventory as load_inventory,
    merge_capture_dir as merge_capture_dir,
    write_inventory as write_inventory,
)
from tests.ace.tui.visual._visual_capture_records import (
    CaptureRecord as CaptureRecord,
    ComparisonSettings as ComparisonSettings,
    InventoryReport as InventoryReport,
    WorkerSessionRecord as WorkerSessionRecord,
)
from tests.ace.tui.visual._visual_capture_session import (
    VisualCaptureSession as VisualCaptureSession,
)
