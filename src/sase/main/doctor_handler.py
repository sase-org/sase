"""Handler for the ``sase doctor`` top-level command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sase.diagnostics import (
    UnknownCheckSelection,
    diagnostic_report_to_json,
    render_diagnostic_report,
)
from sase.doctor.runner import build_doctor_registry, default_doctor_context, run_doctor


def handle_doctor_command(args: argparse.Namespace) -> int:
    """Run or list top-level SASE doctor checks."""
    selections = tuple(getattr(args, "check", ()) or ())
    context = default_doctor_context(
        project=getattr(args, "project", None),
        verbose=bool(getattr(args, "verbose", False)),
    )
    registry = build_doctor_registry(context)

    if getattr(args, "list_checks", False):
        return _handle_list_checks(args, registry, selections)

    try:
        report = run_doctor(
            context=context,
            registry=registry,
            selections=selections,
            deep=bool(getattr(args, "deep", False)),
            strict=bool(getattr(args, "strict", False)),
        )
    except UnknownCheckSelection as exc:
        # A selection can be registered but deep-only; `-L` lists those, so
        # calling them "unknown" would be wrong. Point at -D/--deep instead.
        deep_only = _deep_only_selections(registry, exc.selections)
        unknown = [item for item in exc.selections if item not in set(deep_only)]
        if unknown:
            print(f"error: {UnknownCheckSelection(unknown)}", file=sys.stderr)
        if deep_only:
            joined = ", ".join(deep_only)
            print(
                f"error: {joined} selects deep checks only; "
                "rerun with -D/--deep to include them",
                file=sys.stderr,
            )
            return 2
        return 2

    if getattr(args, "json", False):
        print(diagnostic_report_to_json(report))
    else:
        from sase.project_display_names import load_project_display_snapshot

        render_diagnostic_report(
            report,
            verbose=bool(getattr(args, "verbose", False)),
            project_display_snapshot=load_project_display_snapshot(),
        )
    return report.exit_code()


def _deep_only_selections(
    registry: Any,
    selections: tuple[str, ...],
) -> list[str]:
    """Return selections that resolve to deep-only check ids or groups."""
    deep_specs = registry.list_deep_checks()
    default_specs = registry.list_default_checks()
    deep_names = {spec.id for spec in deep_specs} | {spec.group for spec in deep_specs}
    default_names = {spec.id for spec in default_specs} | {
        spec.group for spec in default_specs
    }
    return [item for item in selections if item in deep_names - default_names]


def _handle_list_checks(
    args: argparse.Namespace,
    registry: Any,
    selections: tuple[str, ...],
) -> int:
    try:
        specs = (
            registry.select(selections, include_deep=True)
            if selections
            else registry.list_checks(include_deep=True)
        )
    except UnknownCheckSelection as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows = [
        {
            "id": spec.id,
            "group": spec.group,
            "title": spec.title,
            "deep": spec.deep,
        }
        for spec in specs
    ]
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "doctor",
                    "checks": rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for row in rows:
            mode = "deep" if row["deep"] else "default"
            print(f"{row['id']}\t{row['group']}\t{mode}\t{row['title']}")
    return 0


__all__ = ["handle_doctor_command"]
