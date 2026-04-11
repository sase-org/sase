"""Bootstrap logic for seeding initial memory by exploring a codebase."""

from __future__ import annotations

import os
from pathlib import Path

# Files commonly found at the root of a project that provide useful context.
_KEY_FILENAMES = [
    "README.md",
    "README.rst",
    "README",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "AGENTS.md",
    "CLAUDE.md",
    "Makefile",
    "justfile",
    "Taskfile.yml",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "build.gradle",
    "pom.xml",
    "Gemfile",
    "docker-compose.yml",
    "Dockerfile",
    ".editorconfig",
]

# Maximum characters to read from any single file.
_MAX_FILE_CHARS = 8_000

# Maximum depth when building the directory overview.
_DIR_TREE_MAX_DEPTH = 3


def gather_project_context(project_root: str | None = None) -> str:
    """Gather a structured summary of a project for memory bootstrapping.

    Returns a markdown-formatted string containing:
    - Directory tree (shallow)
    - Contents of key project files (README, config, etc.)
    """
    root = Path(project_root or os.getcwd()).resolve()

    sections: list[str] = []
    sections.append(f"# Project Context: {root.name}\n")
    sections.append(f"Root: `{root}`\n")

    # --- Directory tree ---
    tree = _build_dir_tree(root, max_depth=_DIR_TREE_MAX_DEPTH)
    if tree:
        sections.append("## Directory Structure\n")
        sections.append("```")
        sections.append(tree)
        sections.append("```\n")

    # --- Key files ---
    found_files = _find_key_files(root)
    if found_files:
        sections.append("## Key Files\n")
        for rel_path, content in found_files:
            sections.append(f"### {rel_path}\n")
            sections.append("```")
            sections.append(content)
            sections.append("```\n")

    return "\n".join(sections)


def _find_key_files(root: Path) -> list[tuple[str, str]]:
    """Find and read key project files, returning (relative_path, content) pairs."""
    results: list[tuple[str, str]] = []
    for name in _KEY_FILENAMES:
        filepath = root / name
        if filepath.is_file():
            try:
                text = filepath.read_text(errors="replace")
                if len(text) > _MAX_FILE_CHARS:
                    text = text[:_MAX_FILE_CHARS] + "\n... (truncated)"
                results.append((name, text))
            except OSError:
                continue
    return results


def _build_dir_tree(root: Path, max_depth: int) -> str:
    """Build a shallow directory tree string."""
    lines: list[str] = [root.name + "/"]
    _walk(root, lines, prefix="", depth=0, max_depth=max_depth)
    return "\n".join(lines)


_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "venv",
    ".eggs",
    "dist",
    "build",
    ".next",
    "target",
}


def _walk(
    directory: Path,
    lines: list[str],
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    """Recursively build tree lines up to *max_depth*."""
    if depth >= max_depth:
        return

    try:
        entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name))
    except PermissionError:
        return

    # Filter out hidden dirs and known noisy dirs
    entries = [
        e
        for e in entries
        if not (e.is_dir() and (e.name in _SKIP_DIRS or e.name.startswith(".")))
    ]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            _walk(entry, lines, prefix + extension, depth + 1, max_depth)
        else:
            lines.append(f"{prefix}{connector}{entry.name}")
