"""Implementation for ``sase patch current``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from sase.ace.patch import Patch
from sase.core.patch import (
    patch_name_to_branch,
    patch_name_to_branch_with_suffix,
    strip_reverted_suffix,
)
from sase.main.patch_common import (
    command_prefix,
    file_location,
)
from sase.project_display_names import humanize_cl_name, project_display_name_for
from sase.vcs_provider import VCSProvider


@dataclass(frozen=True)
class CurrentContext:
    project: str | None
    project_file: str | None
    branch: str | None
    change_url: str | None


def get_current_provider(
    cwd: str,
    *,
    get_vcs_provider_fn: Callable[[str], VCSProvider],
) -> VCSProvider | None:
    """Best-effort VCS provider lookup."""
    try:
        return get_vcs_provider_fn(cwd)
    except Exception:
        return None


def get_current_branch(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current branch/bookmark lookup."""
    if provider is None:
        return None
    try:
        ok, branch = provider.get_branch_name(cwd)
    except Exception:
        return None
    return branch if ok and branch else None


def get_current_change_url(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current PR URL lookup."""
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


def _branch_candidates_for_patch(cs: Patch, provider: VCSProvider | None) -> set[str]:
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
        patch_name_to_branch(cs.name, project),
        patch_name_to_branch_with_suffix(cs.name, project),
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


def _scoped_patches(patches: list[Patch], project: str | None) -> list[Patch]:
    """Limit Patches to the current project when one is known."""
    if not project:
        return patches
    return [cs for cs in patches if cs.project_basename == project]


def _dedupe_patches(patches: list[Patch]) -> list[Patch]:
    """Deduplicate matched Patches without changing order."""
    seen: set[tuple[str, str, int]] = set()
    deduped: list[Patch] = []
    for cs in patches:
        key = (cs.name, cs.file_path, cs.line_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cs)
    return deduped


def find_current_patch(
    patches: list[Patch],
    context: CurrentContext,
    provider: VCSProvider | None,
) -> list[Patch]:
    """Resolve the current checkout to matching Patches."""
    scoped = _scoped_patches(patches, context.project)

    if context.change_url:
        url_matches = [cs for cs in scoped if cs.pr_url == context.change_url]
        if url_matches:
            return _dedupe_patches(url_matches)

    if context.branch:
        branch = _normalize_branch_name(context.branch)
        branch_matches = [
            cs for cs in scoped if branch in _branch_candidates_for_patch(cs, provider)
        ]
        if branch_matches:
            return _dedupe_patches(branch_matches)

    return []


def _patch_payload(cs: Patch) -> dict[str, object]:
    """Stable JSON-serializable representation for ``patch current``."""
    return {
        "name": cs.name,
        "project": cs.project_basename,
        "status": cs.status,
        "parent": cs.parent,
        "cl": cs.pr_url,
        "refs": list(cs.refs or ()),
        "file_path": cs.file_path,
        "line_number": cs.line_number,
    }


def _display_current_markdown(cs: Patch) -> None:
    """Print one Patch in compact agent-friendly markdown."""
    print("# Current Patch")
    print("")
    print(f"## {humanize_cl_name(cs.name)}")
    print("")
    print(f"- **Project:** {project_display_name_for(cs.project_basename)}")
    print(f"- **Status:** {cs.status}")
    print(f"- **Parent:** {humanize_cl_name(cs.parent) if cs.parent else 'None'}")
    print(f"- **PR:** {cs.pr_url or 'None'}")
    print(f"- **Location:** `{file_location(cs)}`")
    if cs.refs:
        print("")
        print("## References")
        print("")
        for reference in cs.refs:
            print(f"- `{reference}`")


def _display_current_plain(cs: Patch) -> None:
    """Print one Patch as stable key/value lines."""
    print(f"NAME: {humanize_cl_name(cs.name)}")
    print(f"PROJECT: {project_display_name_for(cs.project_basename)}")
    print(f"STATUS: {cs.status}")
    print(f"PARENT: {humanize_cl_name(cs.parent) if cs.parent else 'None'}")
    print(f"PR: {cs.pr_url or 'None'}")
    if cs.refs:
        print("REFS:")
        for reference in cs.refs:
            print(f"  {reference}")
    print(f"FILE: {cs.file_path}")
    print(f"LINE: {cs.line_number}")


def _display_current_json(cs: Patch) -> None:
    """Print one Patch as JSON."""
    print(json.dumps(_patch_payload(cs), sort_keys=True))


def _diagnostic_lines(context: CurrentContext) -> list[str]:
    """Diagnostic context for resolver failures."""
    return [
        f"project: {project_display_name_for(context.project) if context.project else 'unknown'}",
        f"project_file: {context.project_file or 'unknown'}",
        f"branch: {context.branch or 'unknown'}",
        f"change_url: {context.change_url or 'unknown'}",
    ]


def handle_current(
    args: argparse.Namespace,
    *,
    find_all_patches_fn: Callable[[], list[Patch]],
    resolve_project_context_fn: Callable[[str | None], tuple[str | None, str | None]],
    get_current_provider_fn: Callable[[str], VCSProvider | None],
    get_current_branch_fn: Callable[[VCSProvider | None, str], str | None],
    get_current_change_url_fn: Callable[[VCSProvider | None, str], str | None],
    find_current_patch_fn: Callable[
        [list[Patch], CurrentContext, VCSProvider | None], list[Patch]
    ],
) -> int:
    """Handle ``sase patch current``."""
    project, project_file = resolve_project_context_fn(args.project_file)
    cwd = os.getcwd()
    provider = get_current_provider_fn(cwd)
    context = CurrentContext(
        project=project,
        project_file=project_file,
        branch=get_current_branch_fn(provider, cwd),
        change_url=get_current_change_url_fn(provider, cwd),
    )

    matches = find_current_patch_fn(find_all_patches_fn(), context, provider)
    if not matches:
        print(
            f"[{command_prefix(args, 'current')}] could not find a Patch "
            "for the current checkout.",
            file=sys.stderr,
        )
        for line in _diagnostic_lines(context):
            print(f"  {line}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(
            f"[{command_prefix(args, 'current')}] multiple Patches match "
            "the current checkout:",
            file=sys.stderr,
        )
        for cs in matches:
            print(
                f"  {humanize_cl_name(cs.name)} ({file_location(cs)})",
                file=sys.stderr,
            )
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


__all__ = [
    "_add_if_present",
    "_branch_candidates_for_patch",
    "_dedupe_patches",
    "_display_current_json",
    "_display_current_markdown",
    "_display_current_plain",
    "_normalize_branch_name",
    "_patch_payload",
    "_scoped_patches",
    "CurrentContext",
    "find_current_patch",
    "get_current_branch",
    "get_current_change_url",
    "get_current_provider",
    "handle_current",
]
