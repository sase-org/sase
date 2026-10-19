"""Handler for ``sase stats project``."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.stats.envelope import project_stats_envelope, stats_runtime_versions
from sase.stats.project import (
    ProjectStatsQuery,
    ProjectStatsUnavailableError,
    ProjectStatsUsageError,
    load_project_stats,
)
from sase.stats.project.models import ProjectStatsIssue
from sase.stats.project.query import ProjectStatsGrouping
from sase.stats.project.request import build_project_stats_request
from sase.stats.project.view import ProjectStatsView
from sase.stats.ranges import DEFAULT_PRESET, PRESET_ORDER, parse_stats_range
from sase.stats.render import (
    RenderContext,
    render_project_stats,
    render_project_stats_markdown,
)
from sase.workspace_provider.utils import non_interactive_git_env

_SPINNER_DELAY_SECONDS = 1.5
_FETCH_TIMEOUT_SECONDS = 30
_GIT_SCRUB_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)
_USAGE_PREFIX = "sase stats project"


def handle_stats_project(
    args: argparse.Namespace,
    *,
    argv: Sequence[str] | None = None,
) -> int:
    """Load, optionally fetch, and render the Projects report."""
    try:
        output_format = _resolve_format(args)
    except ProjectStatsUsageError as exc:
        return _usage_error(str(exc))
    range_text = args.range or DEFAULT_PRESET
    try:
        stats_range = parse_stats_range(range_text)
    except ValueError as exc:
        return _usage_error(str(exc))
    grouping = args.group_by
    query = ProjectStatsQuery(
        range=stats_range,
        project_refs=tuple(args.project or ()),
        preset=range_text if range_text in PRESET_ORDER else None,
        include_disabled=bool(args.include_disabled),
        group_by=grouping,
        fetch=bool(args.fetch),
    )
    try:
        view = _with_spinner(lambda: _load_view(query))
    except ProjectStatsUsageError as exc:
        return _usage_error(str(exc))
    except ProjectStatsUnavailableError as exc:
        print(f"{_USAGE_PREFIX}: {exc}", file=sys.stderr)
        return 1
    return _render(view, output_format, grouping, argv=argv)


def _resolve_format(args: argparse.Namespace) -> str:
    json_flag = bool(args.json)
    fmt = args.format
    if json_flag and fmt is not None and fmt != "json":
        raise ProjectStatsUsageError(
            "-j/--json cannot be combined with a non-JSON --format"
        )
    if json_flag or fmt == "json":
        return "json"
    if fmt is None:
        return "rich"
    return str(fmt)


def _load_view(query: ProjectStatsQuery) -> ProjectStatsView:
    fetch_issues: tuple[ProjectStatsIssue, ...] = ()
    if query.fetch:
        fetch_issues = _fetch_code_repos(query)
    view = load_project_stats(query)
    if fetch_issues:
        return replace(view, issues=(*view.issues, *fetch_issues))
    return view


def _fetch_code_repos(query: ProjectStatsQuery) -> tuple[ProjectStatsIssue, ...]:
    """Fetch each code repo's origin; failures become issues and use local refs."""
    request = build_project_stats_request(
        query,
        now_ts=query.range.end_ts,
    )
    issues: list[ProjectStatsIssue] = []
    seen: set[str] = set()
    for project in request.data["projects"]:
        for repo in project.get("code_repos") or ():
            path = str(repo.get("path") or "")
            if not path or path in seen:
                continue
            seen.add(path)
            issue = _fetch_one(path, project["key"], str(repo.get("name") or path))
            if issue is not None:
                issues.append(issue)
    return tuple(issues)


def _fetch_one(path: str, project: str, repo: str) -> ProjectStatsIssue | None:
    if not Path(path).is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "fetch", "--quiet", "--prune", "origin"],
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
            timeout=_FETCH_TIMEOUT_SECONDS,
            env=_fetch_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return ProjectStatsIssue(
            code="fetch_failed",
            message=f"Fetch timed out for {repo!r}",
            project=project,
            repo=repo,
            hint="Using local refs",
        )
    except OSError as exc:
        return ProjectStatsIssue(
            code="fetch_failed",
            message=f"Fetch failed for {repo!r}: {exc}",
            project=project,
            repo=repo,
            hint="Using local refs",
        )
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or "git fetch failed").strip()
    return ProjectStatsIssue(
        code="fetch_failed",
        message=f"Fetch failed for {repo!r}: {detail}",
        project=project,
        repo=repo,
        hint="Using local refs",
    )


def _fetch_env() -> dict[str, str]:
    env = non_interactive_git_env()
    for key in _GIT_SCRUB_KEYS:
        env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_NO_LAZY_FETCH"] = "1"
    return env


def _with_spinner(work: Callable[[], ProjectStatsView]) -> ProjectStatsView:
    console = Console(file=sys.stderr, stderr=True, highlight=False)
    if not console.is_terminal:
        return work()
    lock = threading.Lock()
    done = False
    status: Any = None

    def _start() -> None:
        nonlocal status, done
        with lock:
            if done:
                return
            status = console.status("Measuring project statistics…", spinner="dots")
            status.start()

    timer = threading.Timer(_SPINNER_DELAY_SECONDS, _start)
    timer.daemon = True
    timer.start()
    try:
        return work()
    finally:
        timer.cancel()
        with lock:
            done = True
            if status is not None:
                status.stop()
                status = None


def _render(
    view: ProjectStatsView,
    output_format: str,
    grouping: ProjectStatsGrouping | None,
    *,
    argv: Sequence[str] | None,
) -> int:
    if output_format == "json":
        print(json.dumps(project_stats_envelope(view), indent=2))
        return 0
    console = Console()
    generated = datetime.fromisoformat(view.generated_at)
    ctx = RenderContext.from_console(console, now=generated, machine=view.machine)
    if output_format == "markdown":
        command_line = "sase " + shlex.join(
            list(argv if argv is not None else sys.argv[1:])
        )
        versions = stats_runtime_versions(view)
        markdown = render_project_stats_markdown(
            view,
            grouping,
            command_line=command_line,
            versions={
                "sase": str(versions["sase"]),
                "sase_core": str(versions["sase_core"]),
            },
            ctx=ctx,
        )
        sys.stdout.write(markdown)
        if not markdown.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    console.print(render_project_stats(view, grouping, ctx))
    return 0


def _usage_error(message: str) -> int:
    print(f"{_USAGE_PREFIX}: {message}", file=sys.stderr)
    return 2


__all__ = ["handle_stats_project"]
