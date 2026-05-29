#!/usr/bin/env python3
"""Automatic memory episode builder chop script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sase.axe.chop_script_context import read_chop_context
from sase.main.init_memory.config import project_memory_name
from sase.memory.episodes.auto_build import (
    DEFAULT_AUTO_BUILD_LIMIT,
    run_episode_auto_build,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", help="Axe chop context JSON path")
    parser.add_argument("-p", "--project", help="Project memory name")
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=DEFAULT_AUTO_BUILD_LIMIT,
        help="Maximum new done markers to seed this cycle",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )
    args = parser.parse_args()

    if args.context:
        read_chop_context(args.context)

    project = args.project or project_memory_name(Path.cwd())
    report = run_episode_auto_build(
        project,
        repo_root=Path.cwd(),
        limit=args.limit,
    )
    if args.json:
        json.dump(report.to_json_dict(), sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(
            "memory_episodes:",
            f"status={report.status}",
            f"project={report.project}",
            f"built={report.built_count}",
            f"changed={report.changed_count}",
            f"checkpoint={report.checkpoint_after or '-'}",
        )
    if report.status in {"error", "state_corrupt"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
