"""Implementation of ``sase artifact doctor``."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.core.artifact_file_facade import (
    ArtifactFileBackfillReport,
    ArtifactFileIndexInspection,
    ArtifactFileVerifyReport,
    backfill_artifact_file_index,
    inspect_artifact_file_index,
    verify_artifact_file_index,
)


def handle_doctor(args: argparse.Namespace) -> int:
    """Inspect, optionally repair, and optionally verify the artifact index."""

    backfill = (
        backfill_artifact_file_index() if bool(getattr(args, "fix", False)) else None
    )
    inspection = inspect_artifact_file_index()
    verification = (
        verify_artifact_file_index() if bool(getattr(args, "verify", False)) else None
    )
    healthy = _inspection_healthy(inspection) and (
        verification is None or _verification_healthy(verification)
    )
    _print_report(
        inspection,
        backfill=backfill,
        verification=verification,
        healthy=healthy,
    )
    return 0 if healthy else 1


def _inspection_healthy(report: ArtifactFileIndexInspection) -> bool:
    return not any(
        (
            report.missing_enrichment_ids,
            report.missing_stored_path_ids,
            report.duplicate_ids,
            report.unrecognized_schema_versions,
            report.malformed_rows,
        )
    )


def _verification_healthy(report: ArtifactFileVerifyReport) -> bool:
    return not any(
        (
            report.missing_sha256_ids,
            report.missing_stored_path_ids,
            report.mismatches,
            report.unrecognized_schema_versions,
        )
    )


def _print_report(
    inspection: ArtifactFileIndexInspection,
    *,
    backfill: ArtifactFileBackfillReport | None,
    verification: ArtifactFileVerifyReport | None,
    healthy: bool,
) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_row(
        "Status", "[green]healthy[/green]" if healthy else "[red]unhealthy[/red]"
    )
    table.add_row("Rows", str(inspection.total_rows))
    table.add_row("Supported rows", str(inspection.supported_rows))
    _add_ids(table, "Missing enrichment", inspection.missing_enrichment_ids)
    _add_ids(table, "Missing stored files", inspection.missing_stored_path_ids)
    _add_ids(
        table,
        "Missing source files (informational)",
        inspection.missing_source_path_ids,
        healthy=True,
    )
    _add_ids(table, "Duplicate ids", inspection.duplicate_ids)
    _add_values(
        table,
        "Unsupported schema versions",
        inspection.unrecognized_schema_versions,
    )
    table.add_row(
        "Malformed rows",
        _count_markup(
            inspection.malformed_rows, healthy=inspection.malformed_rows == 0
        ),
    )
    if backfill is not None:
        _add_ids(table, "Backfilled ids", backfill.updated_ids, healthy=True)
    if verification is not None:
        _add_ids(table, "Verified ids", verification.verified_ids, healthy=True)
        _add_ids(
            table,
            "Missing verification digests",
            verification.missing_sha256_ids,
        )
        _add_ids(
            table,
            "Verification missing files",
            verification.missing_stored_path_ids,
        )
        _add_ids(
            table,
            "Digest mismatches",
            tuple(mismatch.id for mismatch in verification.mismatches),
        )

    Console().print(
        Panel(
            table,
            title="Artifact Index Doctor",
            border_style="green" if healthy else "red",
        )
    )


def _add_ids(
    table: Table,
    label: str,
    values: tuple[str, ...],
    *,
    healthy: bool | None = None,
) -> None:
    if healthy is None:
        healthy = not values
    rendered = ", ".join(values) if values else "none"
    style = "green" if healthy else "red"
    table.add_row(label, f"[{style}]{rendered}[/{style}]")


def _add_values(
    table: Table,
    label: str,
    values: tuple[int, ...],
) -> None:
    _add_ids(table, label, tuple(str(value) for value in values))


def _count_markup(value: int, *, healthy: bool) -> str:
    style = "green" if healthy else "red"
    return f"[{style}]{value}[/{style}]"


__all__ = ["handle_doctor"]
