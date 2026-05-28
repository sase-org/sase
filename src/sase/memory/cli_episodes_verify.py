"""Verify handler for ``sase memory episodes verify``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.core.episode_facade import episode_wire_schema_version
from sase.core.episode_wire import episode_wire_to_json_dict
from sase.memory.cli_episodes_common import (
    all_episode_dirs,
    fail,
    print_json,
    project_from_args,
    resolve_episode_dir,
    verify_episode_dir,
)


def handle_episode_verify(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = project_from_args(args)
    if args.episode_id and args.all:
        fail("sase memory episodes verify: specify an episode id or --all, not both")

    episode_dirs = (
        [
            resolve_episode_dir(
                project,
                args.episode_id,
                projects_root,
                report_alias=True,
            )
        ]
        if args.episode_id
        else all_episode_dirs(project, projects_root)
    )
    reports = [verify_episode_dir(path) for path in episode_dirs]

    if getattr(args, "json", False):
        print_json(
            {
                "project": project,
                "reports": [episode_wire_to_json_dict(report) for report in reports],
                "schema_version": episode_wire_schema_version(),
            }
        )
    elif not reports:
        print(f"No episodes stored for project {project}.")
    else:
        for report in reports:
            status = "ok" if report.ok else "drift"
            print(
                f"{report.episode_id}  {status}  "
                f"{report.ok_count} ok, {report.missing_count} missing, "
                f"{report.changed_count} changed"
            )
            for result in report.results:
                if result.status != "ok":
                    print(f"  {result.status}: {result.source_id} {result.path}")

    if any(not report.ok for report in reports):
        sys.exit(1)
