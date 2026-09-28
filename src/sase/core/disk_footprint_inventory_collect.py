"""Top-level disk-footprint collection and report classification."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core._disk_footprint_inventory_shared import STRAY_MAX_DEPTH
from sase.core._disk_footprint_inventory_shared import STRAY_MAX_VISITED
from sase.core._disk_footprint_inventory_shared import STRAY_SCAN_SECONDS
from sase.core._disk_footprint_inventory_shared import UNRESOLVED_PATH
from sase.config import get_disk_pressure_warn_free_percent
from sase.core.disk_footprint_inventory_rows import managed_tmp_rows
from sase.core.disk_footprint_inventory_rows import sase_state_rows
from sase.core.disk_footprint_inventory_rows import workspace_rows
from sase.core.disk_footprint_inventory_strays import cargo_stray_rows
from sase.core.disk_footprint_inventory_strays import rust_target_rows
from sase.core.disk_pressure import ABSOLUTE_WARN_FREE_BYTES
from sase.core.disk_footprint_models import DISK_COVERAGE_COMPLETE
from sase.core.disk_footprint_models import DISK_COVERAGE_PARTIAL
from sase.core.disk_footprint_models import DiskFootprintReport
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_footprint_utils import BoundedTreeSizer
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_inventory import classify_disk_inventory
from sase.core.paths import sase_home
from sase.core.time import local_now
from sase.workspace_provider.inventory import collect_workspace_inventory

_UNATTRIBUTED_OWNER = "unattributed"


def collect_disk_footprint(
    *,
    include_strays: bool = True,
    home: Path | None = None,
    tree_size_fn: Callable[[Path], int] | None = None,
    workspace_inventory_fn: Callable[..., Any] = collect_workspace_inventory,
    now: datetime | None = None,
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> DiskFootprintReport:
    """Collect SASE-owned and SASE-shaped disk usage rows.

    SASE-known heavy locations (managed roots, state, workspaces, rust
    targets) are always sized before the generic stray walk, so an
    exhausted shared scan budget can only clip the stray walk. When the
    scan is partial or the ``SASE_HOME`` filesystem is under pressure, an
    ``unattributed`` row accounts for ``df`` used minus attributed bytes.
    """

    rows: list[DiskFootprintRow] = []
    diagnostics: list[str] = []
    budget = InventoryScanBudget(
        max_nodes=STRAY_MAX_VISITED,
        max_seconds=STRAY_SCAN_SECONDS,
    )
    size_fn: Callable[[Path], int]
    if tree_size_fn is None:
        bounded_sizer = BoundedTreeSizer(budget=budget)
        size_fn = bounded_sizer.size
    else:
        bounded_sizer = None
        size_fn = tree_size_fn
    generated = (now or local_now()).isoformat()
    rows.extend(
        managed_tmp_rows(tree_size_fn=size_fn, budget=budget, diagnostics=diagnostics)
    )
    rows.extend(
        sase_state_rows(tree_size_fn=size_fn, budget=budget, diagnostics=diagnostics)
    )
    rows.extend(
        workspace_rows(
            tree_size_fn=size_fn,
            workspace_inventory_fn=workspace_inventory_fn,
            diagnostics=diagnostics,
        )
    )
    core_targets = rust_target_rows(tree_size_fn=size_fn)
    rows.extend(core_targets)

    stray_truncated = False
    stray_visited = 0
    if include_strays:
        excludes = [
            Path(row.path)
            for row in rows
            if row.status == "owned" and row.path and Path(row.path).is_absolute()
        ]
        strays, stray_visited, stray_truncated = cargo_stray_rows(
            home or Path.home(),
            excludes=excludes,
            tree_size_fn=size_fn,
            budget=budget,
        )
        rows.extend(strays)
        if stray_truncated:
            diagnostics.append(
                "stray cargo-target scan clipped before exhausting the home tree; "
                "unowned content may exist outside visited paths"
            )
        if stray_visited:
            diagnostics.append(
                f"stray cargo-target scan only descends {STRAY_MAX_DEPTH} "
                "levels below the scan root; deeper targets are excluded from proof"
            )

    diagnostics.extend(tuple(bounded_sizer.diagnostics) if bounded_sizer else ())
    report = _classified_report(
        rows,
        generated_at=generated,
        stray_scan_visited=stray_visited,
        stray_scan_truncated=stray_truncated or budget.truncated,
        scan_diagnostics=diagnostics,
    )
    unattributed = _unattributed_row(
        report,
        disk_usage_fn=disk_usage_fn or shutil.disk_usage,
    )
    if unattributed is not None:
        diagnostics.append(
            f"unattributed {unattributed.size_bytes} bytes on the SASE_HOME "
            "filesystem fall outside inventoried rows"
        )
        report = _classified_report(
            (*rows, unattributed),
            generated_at=generated,
            stray_scan_visited=stray_visited,
            stray_scan_truncated=stray_truncated or budget.truncated,
            scan_diagnostics=diagnostics,
        )
    return report


def largest_unowned_rows(
    *,
    min_bytes: int,
    limit: int = 3,
    report: DiskFootprintReport | None = None,
) -> tuple[DiskFootprintRow, ...]:
    """Return the largest unowned rows above *min_bytes*."""

    current = report or collect_disk_footprint(include_strays=True)
    rows = [
        row
        for row in current.rows
        if row.status == "unowned" and row.size_bytes >= min_bytes
    ]
    rows.sort(key=lambda row: (-row.size_bytes, row.path))
    return tuple(rows[: max(0, limit)])


def _classified_report(
    rows: Sequence[DiskFootprintRow],
    *,
    generated_at: str,
    stray_scan_visited: int,
    stray_scan_truncated: bool,
    scan_diagnostics: Sequence[str],
) -> DiskFootprintReport:
    classified = classify_disk_inventory(
        (row.to_json_dict() for row in rows),
        scan_diagnostics=scan_diagnostics,
        stray_scan_visited=stray_scan_visited,
        stray_scan_truncated=stray_scan_truncated,
    )
    classified_rows = [_row_from_wire(row) for row in classified["rows"]]
    classified_rows.sort(
        key=lambda row: (-row.size_bytes, row.section, row.name, row.path)
    )
    return DiskFootprintReport(
        rows=tuple(classified_rows),
        generated_at=generated_at,
        stray_scan_truncated=bool(classified["stray_scan_truncated"]),
        stray_scan_visited=int(classified["stray_scan_visited"]),
        scan_diagnostics=tuple(str(value) for value in classified["scan_diagnostics"]),
        physical_total_bytes=int(classified["total_bytes"]),
        logical_total_bytes=int(classified["logical_total_bytes"]),
        owned_total_bytes=int(classified["owned_total_bytes"]),
        unowned_total_bytes=int(classified["unowned_total_bytes"]),
        coverage_status=str(classified["coverage_status"]),
        unresolved_owner_coverage=tuple(
            str(value) for value in classified["unresolved_owner_coverage"]
        ),
    )


def _unattributed_row(
    report: DiskFootprintReport,
    *,
    disk_usage_fn: Callable[[str], Any],
) -> DiskFootprintRow | None:
    """Explain ``df`` used bytes that no inventoried row attributes.

    The row is emitted only when coverage is partial or the filesystem
    holding ``SASE_HOME`` is under pressure; otherwise attribution already
    accounts for the disk. It carries an empty path so the classifier
    cannot nest it under (or over) inventoried rows and double-count.
    """

    try:
        home = sase_home()
    except Exception:  # noqa: BLE001 - inventory must stay fail-open.
        return None
    try:
        usage = disk_usage_fn(str(home))
        total_bytes = int(usage.total)
        used_bytes = int(usage.used)
        free_bytes = int(usage.free)
    except Exception:  # noqa: BLE001 - inventory must stay fail-open.
        return None
    unattributed_bytes = used_bytes - _attributed_bytes_on(report, home)
    if unattributed_bytes <= 0:
        return None
    warn_threshold = max(
        ABSOLUTE_WARN_FREE_BYTES,
        int(total_bytes * get_disk_pressure_warn_free_percent() / 100.0),
    )
    partial = report.coverage_status != DISK_COVERAGE_COMPLETE
    if not partial and free_bytes > warn_threshold:
        return None
    return DiskFootprintRow(
        section="filesystem",
        name=_UNATTRIBUTED_OWNER,
        path=UNRESOLVED_PATH,
        size_bytes=unattributed_bytes,
        owner=_UNATTRIBUTED_OWNER,
        horizon=(
            f"{'partial inventory coverage' if partial else 'filesystem pressure'}"
            "; bytes on the SASE_HOME filesystem outside inventoried rows"
        ),
        reclaim="sase disk list",
        coverage=(DISK_COVERAGE_PARTIAL if partial else DISK_COVERAGE_COMPLETE),
        diagnostics=(
            f"filesystem used {used_bytes} bytes; inventoried rows on this "
            f"filesystem attribute {used_bytes - unattributed_bytes} bytes",
        ),
    )


def _attributed_bytes_on(report: DiskFootprintReport, home: Path) -> int:
    """Sum attributed physical bytes residing on *home*'s filesystem."""

    try:
        home_dev = home.stat().st_dev
    except OSError:
        home_dev = None
    attributed = 0
    for row in report.rows:
        size = (
            row.exclusive_size_bytes
            if row.exclusive_size_bytes is not None
            else row.size_bytes
        )
        if not row.path or home_dev is None:
            attributed += size
            continue
        try:
            same_filesystem = Path(row.path).stat().st_dev == home_dev
        except OSError:
            same_filesystem = True
        if same_filesystem:
            attributed += size
    return attributed


def _row_from_wire(raw: Mapping[str, Any]) -> DiskFootprintRow:
    return DiskFootprintRow(
        section=str(raw["section"]),
        name=str(raw["name"]),
        path=str(raw["path"]),
        size_bytes=int(raw["size_bytes"]),
        owner=str(raw["owner"]),
        horizon=str(raw["horizon"]),
        status=str(raw.get("status") or "owned"),
        reclaim=raw.get("reclaim"),
        physical_path=raw.get("physical_path"),
        exclusive_size_bytes=int(raw["exclusive_size_bytes"]),
        coverage=str(raw.get("coverage") or DISK_COVERAGE_COMPLETE),
        diagnostics=tuple(str(value) for value in raw.get("diagnostics") or ()),
        overlap_parent_path=raw.get("overlap_parent_path"),
        overlap_paths=tuple(str(value) for value in raw.get("overlap_paths") or ()),
    )


__all__ = [
    "collect_disk_footprint",
    "largest_unowned_rows",
]
