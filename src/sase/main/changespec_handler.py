"""Handler for the ``sase changespec`` subcommands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import ChangeSpec, find_all_changespecs
from sase.ace.deltas import refresh_deltas_for_changespec
from sase.core.changespec import (
    changespec_name_to_branch,
    changespec_name_to_branch_with_suffix,
    strip_reverted_suffix,
)
from sase.vcs_provider import VCSProvider, get_vcs_provider
from sase.workflows.utils import get_project_file_path, get_project_from_workspace


@dataclass(frozen=True)
class _CurrentContext:
    project: str | None
    project_file: str | None
    branch: str | None
    change_url: str | None


def _resolve_project_file(explicit: str | None) -> str | None:
    """Resolve the project file path from --project-file or workspace inference."""
    if explicit:
        return os.path.expanduser(explicit)
    project = get_project_from_workspace()
    if not project:
        return None
    return get_project_file_path(project)


def _project_from_project_file(project_file: str | None) -> str | None:
    """Return the project basename for a main or archive project file path."""
    if not project_file:
        return None
    stem = Path(project_file).expanduser().stem
    if stem.endswith("-archive"):
        return stem[: -len("-archive")]
    return stem


def _resolve_project_context(explicit: str | None) -> tuple[str | None, str | None]:
    """Resolve project and project-file context for ``changespec current``."""
    if explicit:
        explicit_project_file = os.path.expanduser(explicit)
        return _project_from_project_file(explicit_project_file), explicit_project_file
    project = get_project_from_workspace()
    project_file: str | None = get_project_file_path(project) if project else None
    return project, project_file


def _get_current_provider(cwd: str) -> VCSProvider | None:
    """Best-effort VCS provider lookup."""
    try:
        return get_vcs_provider(cwd)
    except Exception:
        return None


def _get_current_branch(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current branch/bookmark lookup."""
    if provider is None:
        return None
    try:
        ok, branch = provider.get_branch_name(cwd)
    except Exception:
        return None
    return branch if ok and branch else None


def _get_current_change_url(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current PR/CL URL lookup."""
    if provider is None:
        return None
    try:
        ok, url = provider.get_change_url(cwd)
    except Exception:
        return None
    return url if ok and url else None


def _normalize_branch_name(branch: str) -> str:
    """Normalize common ref prefixes for branch candidate comparison."""
    normalized = branch
    for prefix in ("refs/heads/", "refs/remotes/", "origin/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def _add_if_present(values: set[str], value: str | None) -> None:
    """Add a non-empty candidate string."""
    if value:
        values.add(value)


def _branch_candidates_for_changespec(
    cs: ChangeSpec, provider: VCSProvider | None
) -> set[str]:
    """Build branch/name spellings that can identify ``cs``."""
    project = cs.project_basename
    prefix = f"{project}_"
    stripped_prefix = cs.name[len(prefix) :] if cs.name.startswith(prefix) else cs.name
    stripped_suffix = strip_reverted_suffix(cs.name)
    stripped_both = (
        stripped_suffix[len(prefix) :]
        if stripped_suffix.startswith(prefix)
        else stripped_suffix
    )

    candidates: set[str] = set()
    for value in (
        cs.name,
        stripped_prefix,
        stripped_suffix,
        stripped_both,
        stripped_prefix.replace("_", "-"),
        stripped_both.replace("_", "-"),
        changespec_name_to_branch(cs.name, project),
        changespec_name_to_branch_with_suffix(cs.name, project),
    ):
        _add_if_present(candidates, value)

    if provider is not None:
        for method_name in ("derive_branch_name", "derive_branch_name_with_suffix"):
            try:
                derived = getattr(provider, method_name)(cs.name, project)
            except Exception:
                derived = None
            _add_if_present(candidates, derived)

    normalized: set[str] = set()
    for candidate in candidates:
        normalized.add(candidate)
        normalized.add(_normalize_branch_name(candidate))
    return normalized


def _scoped_changespecs(
    changespecs: list[ChangeSpec], project: str | None
) -> list[ChangeSpec]:
    """Limit ChangeSpecs to the current project when one is known."""
    if not project:
        return changespecs
    return [cs for cs in changespecs if cs.project_basename == project]


def _dedupe_changespecs(changespecs: list[ChangeSpec]) -> list[ChangeSpec]:
    """Deduplicate matched ChangeSpecs without changing order."""
    seen: set[tuple[str, str, int]] = set()
    deduped: list[ChangeSpec] = []
    for cs in changespecs:
        key = (cs.name, cs.file_path, cs.line_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cs)
    return deduped


def _find_current_changespec(
    changespecs: list[ChangeSpec],
    context: _CurrentContext,
    provider: VCSProvider | None,
) -> list[ChangeSpec]:
    """Resolve the current checkout to matching ChangeSpecs."""
    scoped = _scoped_changespecs(changespecs, context.project)

    if context.change_url:
        url_matches = [cs for cs in scoped if cs.cl == context.change_url]
        if url_matches:
            return _dedupe_changespecs(url_matches)

    if context.branch:
        branch = _normalize_branch_name(context.branch)
        branch_matches = [
            cs
            for cs in scoped
            if branch in _branch_candidates_for_changespec(cs, provider)
        ]
        if branch_matches:
            return _dedupe_changespecs(branch_matches)

    return []


def _file_location(cs: ChangeSpec) -> str:
    """Return a user-facing file:line location."""
    file_path = cs.file_path.replace(str(Path.home()), "~")
    return f"{file_path}:{cs.line_number}"


def _changespec_payload(cs: ChangeSpec) -> dict[str, object]:
    """Stable JSON-serializable representation for ``changespec current``."""
    return {
        "name": cs.name,
        "project": cs.project_basename,
        "status": cs.status,
        "parent": cs.parent,
        "cl": cs.cl,
        "file_path": cs.file_path,
        "line_number": cs.line_number,
    }


def _display_current_markdown(cs: ChangeSpec) -> None:
    """Print one ChangeSpec in compact agent-friendly markdown."""
    print("# Current ChangeSpec")
    print("")
    print(f"## {cs.name}")
    print("")
    print(f"- **Project:** {cs.project_basename}")
    print(f"- **Status:** {cs.status}")
    print(f"- **Parent:** {cs.parent or 'None'}")
    print(f"- **PR/CL:** {cs.cl or 'None'}")
    print(f"- **Location:** `{_file_location(cs)}`")


def _display_current_plain(cs: ChangeSpec) -> None:
    """Print one ChangeSpec as stable key/value lines."""
    print(f"NAME: {cs.name}")
    print(f"PROJECT: {cs.project_basename}")
    print(f"STATUS: {cs.status}")
    print(f"PARENT: {cs.parent or 'None'}")
    print(f"CL: {cs.cl or 'None'}")
    print(f"FILE: {cs.file_path}")
    print(f"LINE: {cs.line_number}")


def _display_current_json(cs: ChangeSpec) -> None:
    """Print one ChangeSpec as JSON."""
    print(json.dumps(_changespec_payload(cs), sort_keys=True))


def _diagnostic_lines(context: _CurrentContext) -> list[str]:
    """Diagnostic context for resolver failures."""
    return [
        f"project: {context.project or 'unknown'}",
        f"project_file: {context.project_file or 'unknown'}",
        f"branch: {context.branch or 'unknown'}",
        f"change_url: {context.change_url or 'unknown'}",
    ]


def _handle_current(args: argparse.Namespace) -> int:
    project, project_file = _resolve_project_context(args.project_file)
    cwd = os.getcwd()
    provider = _get_current_provider(cwd)
    context = _CurrentContext(
        project=project,
        project_file=project_file,
        branch=_get_current_branch(provider, cwd),
        change_url=_get_current_change_url(provider, cwd),
    )

    matches = _find_current_changespec(find_all_changespecs(), context, provider)
    if not matches:
        print(
            "[sase changespec current] could not find a ChangeSpec for the current checkout.",
            file=sys.stderr,
        )
        for line in _diagnostic_lines(context):
            print(f"  {line}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(
            "[sase changespec current] multiple ChangeSpecs match the current checkout:",
            file=sys.stderr,
        )
        for cs in matches:
            print(f"  {cs.name} ({_file_location(cs)})", file=sys.stderr)
        for line in _diagnostic_lines(context):
            print(f"  {line}", file=sys.stderr)
        return 1

    cs = matches[0]
    if args.format == "json":
        _display_current_json(cs)
    elif args.format == "plain":
        _display_current_plain(cs)
    else:
        _display_current_markdown(cs)
    return 0


def _handle_sync_deltas(args: argparse.Namespace) -> int:
    project_file = _resolve_project_file(args.project_file)
    if not project_file:
        print(
            "[sase changespec sync-deltas] could not infer project file; "
            "pass -p/--project-file or run inside a sase workspace.",
            file=sys.stderr,
        )
        return 1
    if not os.path.isfile(project_file):
        print(
            f"[sase changespec sync-deltas] project file not found: {project_file}",
            file=sys.stderr,
        )
        return 1

    workspace_dir = args.workspace_dir or os.getcwd()
    ok = refresh_deltas_for_changespec(project_file, args.cl_name, workspace_dir)
    if ok:
        print(f"DELTAS refreshed for {args.cl_name} in {project_file}")
        return 0
    print(
        f"[sase changespec sync-deltas] failed to refresh DELTAS for {args.cl_name}; "
        "DELTAS preserved as-is. See logs for details.",
        file=sys.stderr,
    )
    return 1


def handle_changespec_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase changespec`` subcommands."""
    sub = getattr(args, "changespec_subcommand", None)
    if sub == "current":
        sys.exit(_handle_current(args))
    if sub == "sync-deltas":
        sys.exit(_handle_sync_deltas(args))
    print(
        "Usage: sase changespec {current,sync-deltas} [-h]",
        file=sys.stderr,
    )
    sys.exit(1)
