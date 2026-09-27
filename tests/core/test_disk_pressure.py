"""Tests for disk-pressure filesystem observation helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_pressure import collect_filesystem_observations
from sase.scripts.sase_chop_disk_pressure import _unattributed_lead_line


def _report(*rows: DiskFootprintRow):
    return SimpleNamespace(rows=rows)


def _row(owner: str, size: int, path: str = "/somewhere") -> DiskFootprintRow:
    return DiskFootprintRow(
        section="filesystem" if owner == "unattributed" else "managed_tmp",
        name=owner,
        path="" if owner == "unattributed" else path,
        size_bytes=size,
        owner=owner,
        horizon="test",
        exclusive_size_bytes=size,
    )


def test_unattributed_lead_line_dominates_only_when_largest() -> None:
    report = _report(_row("unattributed", 90), _row("managed_tmp_reaper", 50))
    top = (
        {"owner": "managed_tmp_reaper", "size_bytes": 50, "path": "/a"},
        {"owner": "tool_run_retention", "size_bytes": 30, "path": "/b"},
    )

    lead = _unattributed_lead_line(report, top)

    assert lead is not None
    assert "Unattributed" in lead
    assert "sase disk list" in lead


def test_unattributed_lead_line_quiet_when_attributed_is_largest() -> None:
    report = _report(_row("unattributed", 10), _row("managed_tmp_reaper", 50))
    top = ({"owner": "managed_tmp_reaper", "size_bytes": 50, "path": "/a"},)

    assert _unattributed_lead_line(report, top) is None


def test_unattributed_lead_line_quiet_without_unattributed_row() -> None:
    report = _report(_row("managed_tmp_reaper", 50))
    top = ({"owner": "managed_tmp_reaper", "size_bytes": 50, "path": "/a"},)

    assert _unattributed_lead_line(report, top) is None


def test_collect_filesystem_observations_deduplicates_before_sampling(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    sampled: list[str] = []

    def disk_usage(path: str) -> SimpleNamespace:
        sampled.append(path)
        return SimpleNamespace(total=100, used=60, free=40)

    observations = collect_filesystem_observations(
        (
            {"label": "left", "role": "owner", "path": str(left)},
            {"label": "right", "role": "owner", "path": str(right)},
        ),
        disk_usage_fn=disk_usage,
        filesystem_identity_fn=lambda _path: "same-fs",
    )

    assert len(observations) == 1
    assert observations[0]["label"] == "left"
    assert sampled == [str(left)]
