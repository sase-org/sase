"""Import-graph construction for the diff-scoped test selector.

Split out of :mod:`tests._test_selection` so neither half grows past the
repository's per-file line budget. This half knows only how to turn the
repository's Python files into a reverse-resolvable import graph; the selection
policy lives next door.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


GRAPH_CACHE_SCHEMA = 1

# Excluding the visual lane keeps the scoped runner Pillow-free: visual test
# files import shared helpers, so the closure reaches them, but every test they
# contain carries the `visual` marker and is deselected anyway. `just
# test-scoped` therefore depends on `_setup` rather than `_setup-visual`. If
# this exclusion is ever removed, that recipe must go back to `_setup-visual`.
VISUAL_EXCLUDED_PREFIX = "tests/ace/tui/visual/"


class SelectionError(RuntimeError):
    """Raised when the selector cannot produce a trustworthy answer."""


@dataclass(frozen=True)
class ImportGraph:
    """Reverse-resolvable in-repo import graph over ``src/`` and ``tests/``."""

    modules: dict[str, str]
    """Dotted module name -> repository-relative path."""

    paths: dict[str, str]
    """Repository-relative path -> dotted module name."""

    importers: dict[str, tuple[str, ...]]
    """Dotted module name -> the modules that import it."""

    stats: dict[str, Any] = field(default_factory=dict)

    def module_for(self, path: str) -> str | None:
        return self.paths.get(path)

    def path_for(self, module: str) -> str | None:
        return self.modules.get(module)


def is_test_file(path: str) -> bool:
    """Return whether ``path`` is a terminal node (a collectable test file)."""
    return (
        path.startswith("tests/")
        and path.endswith(".py")
        and path.rsplit("/", 1)[-1].startswith("test_")
    )


def is_visual_path(path: str) -> bool:
    return path.startswith(VISUAL_EXCLUDED_PREFIX)


def module_name_for_path(path: str) -> str:
    """Map a repository-relative Python path to its dotted module name."""
    parts = path[: -len(".py")].split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SelectionError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _is_graph_python_file(path: str) -> bool:
    return path.endswith(".py") and (
        path.startswith("src/") or path.startswith("tests/")
    )


def discover_python_files(root: Path) -> list[str]:
    """Enumerate tracked and untracked ``src/`` and ``tests/`` Python files.

    Untracked-but-not-ignored files participate so that a brand-new test file
    an agent has just written is selectable before it is ever committed.
    """
    listings = [
        run_git(root, "ls-files", "-z", "--", "src", "tests"),
        run_git(
            root,
            "ls-files",
            "-z",
            "--others",
            "--exclude-standard",
            "--",
            "src",
            "tests",
        ),
    ]
    discovered = {
        entry
        for listing in listings
        for entry in listing.split("\0")
        if entry and _is_graph_python_file(entry)
    }
    return sorted(discovered)


def _resolve_relative_package(module: str, is_package: bool, level: int) -> str | None:
    package = module if is_package else module.rpartition(".")[0]
    parts = [part for part in package.split(".") if part]
    ascend = level - 1
    if ascend > len(parts):
        return None
    return ".".join(parts[: len(parts) - ascend]) if ascend else package


def parse_import_targets(source: str, path: str) -> list[str]:
    """Return the dotted import targets named by ``source``.

    ``from sase.core import paths`` names both ``sase.core`` and
    ``sase.core.paths``; both are emitted because either may be the in-repo
    module and only the caller knows which names exist.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    module = module_name_for_path(path)
    is_package = path.endswith("/__init__.py") or path == "__init__.py"
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = _resolve_relative_package(module, is_package, node.level)
                if anchor is None:
                    continue
                base = f"{anchor}.{node.module}" if node.module else anchor
            else:
                base = node.module or ""
            if base:
                targets.add(base)
            for alias in node.names:
                targets.add(f"{base}.{alias.name}" if base else alias.name)
    return sorted(targets)


def parser_fingerprint() -> str:
    """Digest this module's own source.

    The cache stores parsed import targets, so it is only valid for the parser
    that produced them. Keying on the schema constant alone is not enough: a
    parser fix that nobody remembers to pair with a schema bump would otherwise
    keep serving edges the current code would never produce, and a selector
    quietly missing edges under-selects tests.
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def _load_graph_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != GRAPH_CACHE_SCHEMA
        or payload.get("parser") != parser_fingerprint()
    ):
        return {}
    entries = payload.get("entries")
    return entries if isinstance(entries, dict) else {}


def _write_graph_cache(cache_path: Path, entries: Mapping[str, Any]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema": GRAPH_CACHE_SCHEMA,
                    "parser": parser_fingerprint(),
                    "entries": entries,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(cache_path)
    except OSError:
        # A cache we cannot write is a performance problem, never a
        # correctness one.
        pass


def build_import_graph(
    root: Path,
    *,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> ImportGraph:
    """Build (or incrementally refresh) the in-repo import graph.

    A cold build AST-parses every file and costs seconds; the cache is keyed
    per file by ``(size, mtime_ns)`` so a warm build only reparses what
    actually changed.
    """
    started = time.monotonic()
    files = discover_python_files(root)
    cached = _load_graph_cache(cache_path) if cache_path and use_cache else {}

    entries: dict[str, dict[str, Any]] = {}
    reparsed = 0
    for path in files:
        try:
            file_stat = (root / path).stat()
        except OSError:
            continue
        previous = cached.get(path)
        if (
            isinstance(previous, dict)
            and previous.get("size") == file_stat.st_size
            and previous.get("mtime_ns") == file_stat.st_mtime_ns
            and isinstance(previous.get("imports"), list)
        ):
            entries[path] = previous
            continue
        reparsed += 1
        try:
            source = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entries[path] = {
            "size": file_stat.st_size,
            "mtime_ns": file_stat.st_mtime_ns,
            "imports": parse_import_targets(source, path),
        }

    if cache_path is not None and (reparsed or entries.keys() != cached.keys()):
        _write_graph_cache(cache_path, entries)

    modules: dict[str, str] = {}
    paths: dict[str, str] = {}
    for path in sorted(entries):
        module = module_name_for_path(path)
        paths[path] = module
        modules.setdefault(module, path)

    importers: dict[str, set[str]] = {}
    edges = 0
    for path, entry in entries.items():
        importer = paths[path]
        for target in entry["imports"]:
            if target == importer or target not in modules:
                continue
            importers.setdefault(target, set()).add(importer)
            edges += 1

    return ImportGraph(
        modules=modules,
        paths=paths,
        importers={key: tuple(sorted(value)) for key, value in importers.items()},
        stats={
            "modules": len(entries),
            "edges": edges,
            "build_seconds": round(time.monotonic() - started, 3),
            "cache_hit": reparsed == 0 and bool(cached),
        },
    )
