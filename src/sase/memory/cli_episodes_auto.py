"""Automatic builder handlers for ``sase memory episodes``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sase.memory.cli_episodes_common import (
    fail,
    print_json,
    project_from_args,
    validate_limit,
)
from sase.memory.episodes.auto_build import (
    DEFAULT_AUTO_BUILD_LIMIT,
    EpisodeAutoBuildReport,
    EpisodeAutoBuildStatus,
    EpisodeDoctorReport,
    build_episode_auto_doctor_report,
    read_episode_auto_build_status,
    run_episode_auto_build,
)


def handle_episode_auto(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
    repo_root: Path | str | None,
) -> None:
    limit = (
        args.limit
        if getattr(args, "limit", None) is not None
        else DEFAULT_AUTO_BUILD_LIMIT
    )
    validate_limit(limit, "limit")
    project = project_from_args(args)
    try:
        report = run_episode_auto_build(
            project,
            projects_root=projects_root,
            repo_root=repo_root if repo_root is not None else Path.cwd(),
            limit=limit,
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes auto: {exc}")

    if getattr(args, "json", False):
        print_json(report.to_json_dict())
    else:
        _print_auto_report(report)
    if report.status in {"error", "state_corrupt"}:
        sys.exit(1)


def handle_episode_status(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = project_from_args(args)
    try:
        status = read_episode_auto_build_status(project, projects_root=projects_root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes status: {exc}")
    if getattr(args, "json", False):
        print_json(status.to_json_dict())
        return
    _print_auto_status(status)


def handle_episode_doctor(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = project_from_args(args)
    try:
        report = build_episode_auto_doctor_report(
            project,
            projects_root=projects_root,
            repair=bool(getattr(args, "repair", False)),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes doctor: {exc}")
    if getattr(args, "json", False):
        print_json(report.to_json_dict())
    else:
        _print_doctor_report(report)
    if report.status == "ERROR":
        sys.exit(1)


def _print_auto_report(report: EpisodeAutoBuildReport) -> None:
    print(report.message)
    print(f"project: {report.project}")
    print(f"status: {report.status}")
    print(
        f"checkpoint: {report.checkpoint_before or '-'} -> {report.checkpoint_after or '-'}"
    )
    print(
        f"seeds: scanned={report.seeds_scanned} skipped={report.seeds_skipped} "
        f"candidates={len(report.candidates)}"
    )
    if report.component_count:
        print(
            f"components: built={report.built_count} changed={report.changed_count} "
            f"unchanged={report.unchanged_count} aliases={report.aliases_written}"
        )
        for component in report.components:
            changed = "changed" if component.get("changed") else "unchanged"
            print(
                "  "
                f"{component['episode_id']}  {component['importance_band']}  "
                f"{changed}  {component['title']}"
            )
    if report.metrics_path:
        print(f"metrics: {report.metrics_path}")
    if report.warnings:
        print(f"warnings: {len(report.warnings)}")


def _print_auto_status(status: EpisodeAutoBuildStatus) -> None:
    print(f"project: {status.project}")
    print(f"episodes_dir: {status.episodes_dir}")
    print(f"lock_available: {str(status.lock_available).lower()}")
    print(f"state: {status.state_status}")
    if status.state_error:
        print(f"state_error: {status.state_error}")
    if status.state:
        print(f"checkpoint: {status.state.get('checkpoint_timestamp') or '-'}")
        print(f"consecutive_failures: {status.state.get('consecutive_failures', 0)}")
        if status.state.get("backoff_until"):
            print(f"backoff_until: {status.state['backoff_until']}")
        if status.state.get("last_error"):
            print(f"last_error: {status.state['last_error']}")
    print(
        f"episodes: {status.episode_count} canonical, {status.index_row_count} indexed"
    )
    if status.latest_metrics:
        print(
            "latest_metrics: "
            f"{status.latest_metrics.get('status')} "
            f"at {status.latest_metrics.get('finished_at')}"
        )


def _print_doctor_report(report: EpisodeDoctorReport) -> None:
    print(f"Episode auto-build doctor: {report.status}")
    print(f"project: {report.project}")
    for check in report.checks:
        print(f"{check['status']} {check['id']}: {check['summary']}")
        for detail in check.get("details", []):
            print(f"  {detail}")
    if report.repairs:
        print("Repairs:")
        for repair in report.repairs:
            marker = "applied" if repair.get("executed") else "planned"
            print(f"  {marker} {repair['id']}: {repair['summary']}")


__all__ = [
    "handle_episode_auto",
    "handle_episode_doctor",
    "handle_episode_status",
]
