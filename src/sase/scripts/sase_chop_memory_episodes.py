#!/usr/bin/env python3
"""Automatic memory episode builder chop script."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from sase.axe.chop_script_context import read_chop_context
from sase.main.init_memory.config import project_memory_name
from sase.memory.episodes.auto_build import (
    DEFAULT_AUTO_BUILD_LIMIT,
    run_episode_auto_build,
)

PROJECT_ENV = "SASE_MEMORY_EPISODES_PROJECT"
REPO_ROOT_ENV = "SASE_MEMORY_EPISODES_REPO_ROOT"


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_configured_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(expanded).resolve(strict=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", help="Axe chop context JSON path")
    parser.add_argument("-p", "--project", help="Project memory name")
    parser.add_argument(
        "-r",
        "--repo-root",
        help=f"Source repository root (default: ${REPO_ROOT_ENV} or current directory)",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=DEFAULT_AUTO_BUILD_LIMIT,
        help="Maximum new done markers to seed this cycle",
    )
    parser.add_argument(
        "-D",
        "--dry-run",
        action="store_true",
        help="Plan and build reports without writing episodes, state, or metrics",
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

    repo_root_value = _nonempty(args.repo_root) or _nonempty(
        os.environ.get(REPO_ROOT_ENV)
    )
    repo_root = (
        _resolve_configured_path(repo_root_value)
        if repo_root_value is not None
        else Path.cwd()
    )
    project = (
        _nonempty(args.project)
        or _nonempty(os.environ.get(PROJECT_ENV))
        or project_memory_name(repo_root)
    )
    report = run_episode_auto_build(
        project,
        repo_root=repo_root,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if args.json:
        payload = report.to_json_dict()
        payload["target_repo_root"] = str(repo_root)
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(
            "memory_episodes:",
            f"status={report.status}",
            f"project={report.project}",
            f"repo_root={repo_root}",
            f"built={report.built_count}",
            f"changed={report.changed_count}",
            f"checkpoint={report.checkpoint_after or '-'}",
        )
    if report.status in {"error", "state_corrupt"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
