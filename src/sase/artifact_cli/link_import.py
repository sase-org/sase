"""CLI handler for legacy artifact-link index import."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
import sys

from sase.sdd._artifact_link_cutover_state import artifact_link_cutover_attestation
from sase.sdd.artifact_link_import_indexes import (
    ArtifactLinkIndexImportReport,
    import_artifact_link_indexes,
)
from sase.sdd.artifact_link_store import (
    resolve_artifact_link_store,
    resolve_machine_artifact_link_store,
)


def handle_link_import_indexes(args: argparse.Namespace) -> int:
    """Preview or apply the legacy ``links/`` to event-store import."""

    try:
        current_store = resolve_artifact_link_store(cwd=Path.cwd())
        store = resolve_machine_artifact_link_store(
            current_store.project_key, Path.cwd()
        )
        applying = bool(getattr(args, "apply", False))
        attestation = getattr(args, "attestation", None)
        preview = import_artifact_link_indexes(store, apply=False)
        expected = artifact_link_cutover_attestation(preview.plan.fenced_marker)
        if applying and attestation != expected:
            _emit_report(preview, json_output=bool(getattr(args, "json", False)))
            print(
                "Error: refusing to apply artifact-link index import without "
                f"matching fleet capability attestation: expected {expected}",
                file=sys.stderr,
            )
            return 1
        report = (
            import_artifact_link_indexes(store, apply=True) if applying else preview
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _emit_report(report, json_output=bool(getattr(args, "json", False)))
    return 0


def _emit_report(report: ArtifactLinkIndexImportReport, *, json_output: bool) -> None:
    if json_output:
        json.dump(report.to_json_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    _print_report(report)


def _print_report(report: ArtifactLinkIndexImportReport) -> None:
    data = report.to_json_dict()
    plan = data["plan"]
    applied = bool(data["applied"])
    action = "applied" if applied else "preview"
    print(f"artifact-link legacy index import {action}")
    print(f"project: {plan['project_key']}")
    print("roles:")
    for role in plan["roles"]:
        print(
            f"  {role['role']} ({role['kind']}): "
            f"head {role['head']}; links {role['links_tree']}; "
            f"{role['row_count']} rows"
        )
    print(f"unique rows: {plan['unique_rows']}")
    print(f"duplicate rows: {plan['duplicate_rows']}")
    print(f"queued legacy outbox lines: {data['queued_legacy_outbox_entries']}")
    print(f"queued invalid outbox lines: {data['queued_invalid_outbox_entries']}")
    baseline = plan["baseline_event"]
    print(f"baseline event: {baseline['path']}")
    print("fleet machines attested:")
    for machine in _fleet_machine_names():
        print(f"  {machine}")
    token = artifact_link_cutover_attestation(report.plan.fenced_marker)
    print(f"attestation: {token}")
    if applied:
        print(f"converted outbox entries: {data['converted_outbox_entries']}")
        print(f"covered outbox entries: {data['covered_outbox_entries']}")
        print(f"event files touched: {len(data['event_paths'])}")
        print(f"aggregate rows: {data['aggregate_rows']}")
        if data["already_imported"]:
            print("state: already imported")
    else:
        print(
            "state: preview only; rerun with "
            f"`sase artifact link import-indexes --apply {token}`"
        )
    print(
        "warning: the cutover marker fences current SASE binaries only; "
        "older binaries do not understand link-events/STORE.json"
    )


def _fleet_machine_names() -> tuple[str, ...]:
    names: list[str] = []
    try:
        from sase.dispatch.machine_service import MachineService

        names.extend(machine.alias for machine in MachineService().list_machines())
    except Exception as exc:  # noqa: BLE001 - preview must remain available.
        names.append(f"machine registry unavailable: {exc}")
    local = platform.node() or "this-machine"
    names.append(local)
    return tuple(dict.fromkeys(names))


__all__ = ["handle_link_import_indexes"]
