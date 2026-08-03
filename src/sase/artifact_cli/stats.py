"""Implementation of ``sase artifact stats``."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.config import (
    get_artifact_retention_keep_per_label,
    get_artifact_retention_max_age_days,
)
from sase.core.artifact_file_economics import (
    ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ArtifactFileEconomics,
    ArtifactFileEconomicsGroup,
    artifact_file_store_economics,
)
from sase.core.artifact_file_protection import (
    ProtectedArtifactIds,
    collect_protected_artifact_ids,
)
from sase.core.artifact_file_retention import (
    RetentionPlan,
    RetentionPolicy,
    plan_artifact_file_retention,
)
from sase.core.artifact_file_types import default_artifact_files_root
from sase.core.rust import require_rust_binding
from sase.core.time import get_timezone
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


ARTIFACT_STATS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _TrashOccupancy:
    """Current occupancy of the restorable artifact trash."""

    entries: int
    bytes: int
    unreadable_entries: int


def handle_stats(args: argparse.Namespace) -> int:
    """Render a read-only artifact-store economics report."""

    projects = load_project_ref_display_snapshot()
    raw_project = getattr(args, "project", None)
    project = None if raw_project is None else projects.project_key_for_ref(raw_project)
    if raw_project is not None and project is None:
        print(f"Error: unknown project reference: {raw_project}", file=sys.stderr)
        return 2

    economics = artifact_file_store_economics(
        project=project,
        top_n=getattr(args, "top", 10),
    )
    protections = collect_protected_artifact_ids()
    keep_per_label = get_artifact_retention_keep_per_label()
    max_age_days = get_artifact_retention_max_age_days()
    policy = RetentionPolicy(
        now=datetime.now(get_timezone()).isoformat(),
        keep_per_label=keep_per_label,
        before=None if max_age_days == 0 else f"{max_age_days}d",
        project=project,
        protected_ids=protections.ids,
    )
    retention = plan_artifact_file_retention(policy)
    trash = _trash_occupancy()

    payload = _stats_payload(
        economics=economics,
        protections=protections,
        retention=retention,
        trash=trash,
        keep_per_label=keep_per_label,
        max_age_days=max_age_days,
    )
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    _print_stats(
        economics=economics,
        protections=protections,
        retention=retention,
        trash=trash,
        keep_per_label=keep_per_label,
        max_age_days=max_age_days,
        projects=projects,
    )
    return 0


def _stats_payload(
    *,
    economics: ArtifactFileEconomics,
    protections: ProtectedArtifactIds,
    retention: RetentionPlan,
    trash: _TrashOccupancy,
    keep_per_label: int,
    max_age_days: int,
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_STATS_SCHEMA_VERSION,
        "economics": economics.to_json_dict(),
        "protections": {
            "explicit_rows": economics.explicit_rows,
            "referenced_ids": len(protections.referenced_ids),
            "consumed_ids": len(protections.consumed_ids),
            "overlap_ids": len(protections.overlap_ids),
            "total_ids": len(protections.ids),
            "ids": sorted(protections.ids),
            "sources_scanned": list(protections.sources_scanned),
            "sources_unavailable": list(protections.sources_unavailable),
        },
        "trash": asdict(trash),
        "default_policy": {
            "keep_per_label": keep_per_label,
            "max_age_days": max_age_days,
            "plan": retention.to_json_dict(),
        },
    }


def _trash_occupancy() -> _TrashOccupancy:
    binding = require_rust_binding("artifact_file_trash_list")
    trash_root = default_artifact_files_root() / "trash"
    raw = binding(str(trash_root.expanduser().resolve(strict=False)))
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file trash listing: "
            "expected an object"
        )
    data = cast(Mapping[str, Any], raw)
    schema_version = _nonnegative_int(data.get("schema_version"), "schema_version")
    if schema_version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file trash listing: "
            f"schema_version must be {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}"
        )
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file trash listing: "
            "entries must be a list"
        )
    total_bytes = 0
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, Mapping):
            raise RuntimeError(
                "sase_core_rs returned an incompatible artifact-file trash listing: "
                f"entries[{index}] must be an object"
            )
        size_bytes = raw_entry.get("size_bytes")
        if size_bytes is not None:
            total_bytes += _nonnegative_int(
                size_bytes,
                f"entries[{index}].size_bytes",
            )
    return _TrashOccupancy(
        entries=len(raw_entries),
        bytes=total_bytes,
        unreadable_entries=_nonnegative_int(
            data.get("unreadable_entries"),
            "unreadable_entries",
        ),
    )


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file trash listing: "
            f"{field} must be a non-negative integer"
        )
    return value


def _print_stats(
    *,
    economics: ArtifactFileEconomics,
    protections: ProtectedArtifactIds,
    retention: RetentionPlan,
    trash: _TrashOccupancy,
    keep_per_label: int,
    max_age_days: int,
    projects: ProjectRefDisplaySnapshot,
) -> None:
    console = Console()
    totals = _plain_table()
    totals.add_row("Rows", str(economics.total_rows))
    totals.add_row("Recorded bytes", _human_size(economics.total_bytes))
    totals.add_row(
        "Explicit",
        f"{economics.explicit_rows} / {_human_size(economics.explicit_bytes)}",
    )
    totals.add_row(
        "Automatic",
        f"{economics.automatic_rows} / {_human_size(economics.automatic_bytes)}",
    )
    totals.add_row(
        "VCS-backed",
        f"{economics.vcs_backed_rows} / {_human_size(economics.vcs_backed_bytes)}",
    )
    totals.add_row("Rows missing size", str(economics.rows_missing_size))
    console.print(Panel(totals, title="Artifact Store Totals", border_style="cyan"))

    window = _plain_table()
    window.add_row("First capture", economics.first_created_at or "-")
    window.add_row("Last capture", economics.last_created_at or "-")
    window.add_row("Observed window", f"{economics.window_days} days")
    window.add_row("Observed rows/day", f"{economics.rows_per_day:.1f}")
    window.add_row(
        "Observed bytes/day",
        _human_size(round(economics.bytes_per_day)),
    )
    console.print(
        Panel(window, title="Window and Observed Growth", border_style="cyan")
    )

    _print_group_panel(console, "By Kind", economics.by_kind)
    _print_group_panel(
        console,
        "By Project",
        economics.by_project,
        key_label=projects.display_snapshot.label_for,
    )
    _print_group_panel(
        console,
        "Top Agents",
        economics.by_agent,
        truncated_groups=economics.by_agent_truncated_groups,
        truncated_bytes=economics.by_agent_truncated_bytes,
    )

    economics_detail = _plain_table()
    economics_detail.add_row(
        "Duplicate digest groups",
        str(economics.duplicate_digest_groups),
    )
    economics_detail.add_row(
        "Redundant rows / bytes",
        (
            f"{economics.redundant_digest_rows} / "
            f"{_human_size(economics.redundant_digest_bytes)}"
        ),
    )
    economics_detail.add_row("Distinct labels", str(economics.distinct_labels))
    for projection in economics.label_generation_projections:
        economics_detail.add_row(
            f"Keep newest {projection.keep_per_label} / label",
            (
                f"{projection.rows_freed} rows / "
                f"{_human_size(projection.bytes_freed)} freed"
            ),
        )
    economics_detail.add_row(
        "Reclaimable upper bound",
        (
            f"{economics.source_inside_workspace_rows} rows / "
            f"{_human_size(economics.source_inside_workspace_bytes)}"
        ),
    )
    console.print(
        Panel(
            economics_detail,
            title="Redundancy and Projections",
            border_style="cyan",
        )
    )

    protection_table = _plain_table()
    protection_table.add_row("Explicit rows", str(economics.explicit_rows))
    protection_table.add_row("Referenced ids", str(len(protections.referenced_ids)))
    protection_table.add_row("Consumed ids", str(len(protections.consumed_ids)))
    protection_table.add_row("Overlap ids", str(len(protections.overlap_ids)))
    protection_table.add_row("Total protected ids", str(len(protections.ids)))
    protection_table.add_row(
        "Sources scanned",
        str(len(protections.sources_scanned)),
    )
    if protections.sources_unavailable:
        protection_table.add_row(
            "[yellow]Unavailable sources[/yellow]",
            "[yellow]" + "\n".join(protections.sources_unavailable) + "[/yellow]",
        )
    else:
        protection_table.add_row("Unavailable sources", "[green]none[/green]")
    console.print(Panel(protection_table, title="Protections", border_style="cyan"))

    trash_table = _plain_table()
    trash_table.add_row("Entries", str(trash.entries))
    trash_table.add_row("Stored bytes", _human_size(trash.bytes))
    trash_table.add_row("Unreadable entries", str(trash.unreadable_entries))
    console.print(Panel(trash_table, title="Trash Occupancy", border_style="cyan"))

    default_table = _plain_table()
    default_table.add_row("Keep per label", str(keep_per_label))
    default_table.add_row(
        "Maximum age",
        "disabled" if max_age_days == 0 else f"{max_age_days} days",
    )
    default_table.add_row("Candidates", str(retention.counts.candidates))
    default_table.add_row("Selected", str(retention.counts.selected))
    default_table.add_row(
        "Byte-backed / byte-free",
        (
            f"{retention.counts.byte_backed_selected} / "
            f"{retention.counts.byte_free_selected}"
        ),
    )
    default_table.add_row(
        "Reclaimable",
        _human_size(retention.reclaimable_bytes),
    )
    default_table.add_row("Truncated", str(retention.truncated))
    console.print(
        Panel(
            default_table,
            title="What the Default Policy Would Select",
            border_style="magenta",
        )
    )


def _plain_table() -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Measure", style="bold")
    table.add_column("Value")
    return table


def _print_group_panel(
    console: Console,
    title: str,
    groups: tuple[ArtifactFileEconomicsGroup, ...],
    *,
    key_label: Callable[[str], str] = lambda value: value,
    truncated_groups: int = 0,
    truncated_bytes: int = 0,
) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("GROUP")
    table.add_column("ROWS", justify="right")
    table.add_column("BYTES", justify="right")
    for group in groups:
        table.add_row(key_label(group.key), str(group.rows), _human_size(group.bytes))
    if truncated_groups:
        table.add_row(
            f"[dim]{truncated_groups} more groups[/dim]",
            "-",
            f"[dim]{_human_size(truncated_bytes)}[/dim]",
        )
    if not groups and not truncated_groups:
        table.add_row("[dim]none[/dim]", "-", "-")
    console.print(Panel(table, title=title, border_style="cyan"))


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = [
    "ARTIFACT_STATS_SCHEMA_VERSION",
    "handle_stats",
]
