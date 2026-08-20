"""Locate non-test call sites for a registered feature flag."""

from __future__ import annotations

import ast
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sase


_SKIP_DIR_NAMES = frozenset(
    {
        ".eggs",
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)
_EXCLUDED_RELPATHS = frozenset(
    {
        "feature_flags/registry.py",
        "feature_flags/schema.py",
    }
)


@dataclass(frozen=True)
class FlagCallSite:
    """One source location that reads a feature-flag key."""

    path: str
    line: int
    text: str


def _sase_package_root() -> Path:
    """Return the installed ``sase`` package directory."""
    return Path(sase.__file__).resolve().parent


def find_flag_call_sites(
    key: str,
    *,
    root: Path | None = None,
) -> tuple[FlagCallSite, ...]:
    """Return non-test references to *key* under the SASE package tree."""
    search_root = _sase_package_root() if root is None else root
    sites: list[FlagCallSite] = []
    for path in _iter_python_files(search_root):
        if _is_excluded(path, search_root):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError):
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not _node_references_key(node, key):
                continue
            line = getattr(node, "lineno", 1)
            text = lines[line - 1].strip() if 0 < line <= len(lines) else key
            sites.append(
                FlagCallSite(
                    path=_relpath(path, search_root),
                    line=line,
                    text=text,
                )
            )
    return tuple(_normalized_call_sites(sites))


def flag_call_sites_payload(
    sites: Sequence[FlagCallSite],
) -> list[dict[str, Any]]:
    """Return a strictly ordered payload list for persisted call-site evidence."""
    return [
        {"path": site.path, "line": site.line, "text": site.text}
        for site in _normalized_call_sites(sites)
    ]


def _normalized_call_sites(sites: Sequence[FlagCallSite]) -> tuple[FlagCallSite, ...]:
    return tuple(sorted(sites, key=lambda site: (site.path, site.line, site.text)))


def _iter_python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIR_NAMES and not (current / name / ".git").exists()
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(current / filename)
    return sorted(files)


def _is_excluded(path: Path, root: Path) -> bool:
    return _relpath(path, root) in _EXCLUDED_RELPATHS


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _is_feature_flag_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "FeatureFlag"
    return isinstance(node, ast.Attribute) and node.attr == "FeatureFlag"


def _node_references_key(node: ast.AST, key: str) -> bool:
    if (
        isinstance(node, ast.Attribute)
        and node.attr == key
        and _is_feature_flag_expr(node.value)
    ):
        return True
    if (
        isinstance(node, ast.Subscript)
        and _is_feature_flag_expr(node.value)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == key
    ):
        return True
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "enabled"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == key
    )


__all__ = [
    "FlagCallSite",
    "find_flag_call_sites",
    "flag_call_sites_payload",
]
