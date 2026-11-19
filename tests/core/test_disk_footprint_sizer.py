"""Tests for bounded tree-size measurement states."""

from __future__ import annotations

from pathlib import Path

from sase.core.disk_footprint_utils import DISK_SIZE_LOWER_BOUND
from sase.core.disk_footprint_utils import DISK_SIZE_MEASURED
from sase.core.disk_footprint_utils import DISK_SIZE_UNMEASURED
from sase.core.disk_footprint_utils import BoundedTreeSizer
from sase.core.disk_footprint_utils import _TreeSizeMeasurement
from sase.core.disk_footprint_utils import _coerce_tree_size
from sase.core.disk_footprint_utils import format_measured_bytes
from sase.core.disk_footprint_utils import measured_row_fields

from tests.core._disk_footprint_helpers import _write


def test_exhausted_budget_returns_unmeasured_not_zero_complete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    _write(root / "file", "payload")
    sizer = BoundedTreeSizer(max_nodes=1, max_seconds=0)

    result = sizer.size(root)

    assert result.state == DISK_SIZE_UNMEASURED
    assert result.size_bytes == 0
    assert result.diagnostics
    fields = measured_row_fields(sizer.size, root)
    assert fields["coverage"] == "partial"
    assert fields["size_state"] == DISK_SIZE_UNMEASURED
    assert format_measured_bytes(result.size_bytes, result.state) == "unmeasured"


def test_du_timeout_with_truncated_walk_is_lower_bound(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "tree"
    for index in range(12):
        _write(root / f"dir-{index}" / "blob", "x" * 64)
    monkeypatch.setattr(
        "sase.core.disk_footprint_utils.du_size",
        lambda *_args, **_kwargs: None,
    )
    sizer = BoundedTreeSizer(max_nodes=3, max_seconds=60.0)

    result = sizer.size(root)

    assert result.state == DISK_SIZE_LOWER_BOUND
    assert result.size_bytes >= 0
    assert any("truncated" in item for item in result.diagnostics)
    assert format_measured_bytes(result.size_bytes, result.state).startswith("≥")


def test_plain_int_tree_size_fn_is_measured() -> None:
    measurement = _coerce_tree_size(42)

    assert measurement == _TreeSizeMeasurement(size_bytes=42, state=DISK_SIZE_MEASURED)
    assert format_measured_bytes(42, DISK_SIZE_MEASURED) == "42 B"
