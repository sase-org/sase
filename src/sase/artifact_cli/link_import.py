"""CLI handler for legacy artifact-link index import."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

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
        report = import_artifact_link_indexes(
            store,
            apply=bool(getattr(args, "apply", False)),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bool(getattr(args, "json", False)):
        json.dump(report.to_json_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    _print_report(report)
    return 0


def _print_report(report: ArtifactLinkIndexImportReport) -> None:
    data = report.to_json_dict()
    plan = data["plan"]
    applied = bool(data["applied"])
    action = "applied" if applied else "preview"
    print(f"artifact-link legacy index import {action}")
    print(f"project: {plan['project_key']}")
    print(f"roles: {len(plan['roles'])}")
    print(f"unique rows: {plan['unique_rows']}")
    print(f"duplicate rows: {plan['duplicate_rows']}")
    baseline = plan["baseline_event"]
    print(f"baseline event: {baseline['path']}")
    if applied:
        print(f"converted outbox entries: {data['converted_outbox_entries']}")
        print(f"event files touched: {len(data['event_paths'])}")
        print(f"aggregate rows: {data['aggregate_rows']}")
        if data["already_imported"]:
            print("state: already imported")
    else:
        print("state: preview only; rerun with --apply to publish the cutover")
    print(
        "warning: the cutover marker fences current SASE binaries only; "
        "older binaries do not understand link-events/STORE.json"
    )


__all__ = ["handle_link_import_indexes"]
