"""Deprecation notices and glossary-web delegation for ``sase glossary``.

`sase glossary` survives one release as a deprecating alias over `sase
memory` once a project migrates its glossary to a memory web: every read-side
subcommand prints a one-line notice naming its `sase memory` equivalent, then
delegates to it when the project has a `glossary` web, or falls back to
today's config-backed behavior when it does not.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sys

from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.web.catalog import GLOSSARY_WEB_SLUG, find_memory_web
from sase.memory.web.models import MemoryWeb


def print_glossary_deprecation_notice(subcommand: str, equivalent: str) -> None:
    """Print the one-line stderr notice naming *subcommand*'s memory equivalent."""
    print(
        f"sase glossary {subcommand}: deprecated, use `{equivalent}` instead",
        file=sys.stderr,
    )


def _glossary_project_root(project_ref: str | None) -> Path:
    """Resolve *project_ref* to a workspace root the same way `sase memory` does."""
    resolved = resolve_memory_cli_project(project_ref)
    return resolved.project_root if resolved is not None else Path.cwd()


def find_glossary_web(project_ref: str | None) -> MemoryWeb | None:
    """Return the project's `glossary` memory web, or ``None`` before migration.

    An unresolvable *project_ref* is treated as "no web": the legacy handler
    re-resolves the same ref and raises the authoritative error message.
    """
    try:
        root = _glossary_project_root(project_ref)
    except MemoryCliProjectError:
        return None
    return find_memory_web(root, GLOSSARY_WEB_SLUG)


@contextmanager
def glossary_project_directory(project_ref: str | None) -> Iterator[None]:
    """Chdir into *project_ref*'s workspace root for a delegated memory command.

    `sase memory log` always reads from the current directory; the legacy
    `sase glossary log -p` accepts an explicit project, so delegation must
    still honor it.
    """
    if not project_ref:
        yield
        return
    previous = Path.cwd()
    os.chdir(_glossary_project_root(project_ref))
    try:
        yield
    finally:
        os.chdir(previous)


def memory_read_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Build the `sase memory read` namespace equivalent to `sase glossary read`."""
    return argparse.Namespace(
        selectors=_term_selectors(args),
        depth=getattr(args, "depth", None),
        format=getattr(args, "format", "rich"),
        project=getattr(args, "project", None),
        reason=args.reason,
    )


def memory_show_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Build the `sase memory show` namespace equivalent to `sase glossary show`."""
    return argparse.Namespace(
        selectors=_term_selectors(args),
        depth=getattr(args, "depth", None),
        format=getattr(args, "format", "rich"),
        project=getattr(args, "project", None),
    )


def memory_all_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Build the `sase memory show` namespace equivalent to `sase glossary all`."""
    return argparse.Namespace(
        selectors=[GLOSSARY_WEB_SLUG],
        depth=None,
        format=getattr(args, "format", "rich"),
        project=getattr(args, "project", None),
    )


def memory_web_show_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Build the `sase memory web show` namespace equivalent to `glossary list`."""
    return argparse.Namespace(
        web=GLOSSARY_WEB_SLUG,
        pattern=getattr(args, "pattern", None),
        bodies=bool(getattr(args, "definitions", False)),
        format=getattr(args, "format", "table"),
        project=getattr(args, "project", None),
    )


def memory_log_namespace(args: argparse.Namespace) -> argparse.Namespace:
    """Build the `sase memory log` namespace equivalent to `sase glossary log`."""
    return argparse.Namespace(
        path=None,
        agent=getattr(args, "agent", None),
        id=getattr(args, "id", None),
        include=["glossary"],
        json=getattr(args, "format", "table") == "json",
    )


def _term_selectors(args: argparse.Namespace) -> list[str]:
    return [f"{GLOSSARY_WEB_SLUG}:{term}" for term in args.term]


__all__ = [
    "find_glossary_web",
    "glossary_project_directory",
    "memory_all_namespace",
    "memory_log_namespace",
    "memory_read_namespace",
    "memory_show_namespace",
    "memory_web_show_namespace",
    "print_glossary_deprecation_notice",
]
