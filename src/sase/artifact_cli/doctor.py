"""Implementation of ``sase artifact doctor``."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.artifact_cli.link_health import (
    ArtifactLinkHealthReport,
    inspect_artifact_link_health,
)
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
    try:
        link_report = inspect_artifact_link_health(
            fix=bool(getattr(args, "fix", False))
        )
    except Exception as exc:  # noqa: BLE001 - doctor still reports the file index
        link_report = ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))
    healthy = (
        _inspection_healthy(inspection)
        and (verification is None or _verification_healthy(verification))
        and link_report.healthy
    )
    _print_report(
        inspection,
        backfill=backfill,
        verification=verification,
        link_report=link_report,
        healthy=healthy,
    )
    return 0 if healthy else 1


def _inspection_healthy(report: ArtifactFileIndexInspection) -> bool:
    return not any(
        (
            report.missing_enrichment_ids,
            report.missing_stored_path_ids,
            report.vcs_provenance_incomplete_ids,
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
            report.unresolvable_vcs_ids,
            report.mismatches,
            report.unrecognized_schema_versions,
        )
    )


def _print_report(
    inspection: ArtifactFileIndexInspection,
    *,
    backfill: ArtifactFileBackfillReport | None,
    verification: ArtifactFileVerifyReport | None,
    link_report: ArtifactLinkHealthReport,
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
    table.add_row("VCS reference rows", str(inspection.vcs_reference_rows))
    _add_ids(table, "Missing enrichment", inspection.missing_enrichment_ids)
    _add_ids(table, "Missing stored files", inspection.missing_stored_path_ids)
    _add_ids(
        table,
        "Incomplete VCS provenance",
        inspection.vcs_provenance_incomplete_ids,
    )
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
            "Unresolvable VCS references",
            verification.unresolvable_vcs_ids,
        )
        _add_ids(
            table,
            "Digest mismatches",
            tuple(mismatch.id for mismatch in verification.mismatches),
        )
    if link_report.skipped:
        table.add_row("Artifact links", "[dim]skipped (no store)[/dim]")
    else:
        _add_ids(table, "Artifact link errors", link_report.errors)
        _add_ids(table, "Dangling link refs", link_report.dangling)
        _add_ids(table, "Stale Links tables", link_report.stale_tables)
        _add_ids(table, "Missing companions", link_report.missing_companions)
        _add_ids(
            table,
            "Rendered block missing links/ JSON in HEAD",
            link_report.missing_head_indexes,
        )
        table.add_row("Recorded reads", str(link_report.read_events))
        if link_report.rebuilt:
            table.add_row("Link aggregate", "[green]rebuilt[/green]")

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
