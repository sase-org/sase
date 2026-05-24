"""Inventory and rendering for ``sase amd list``."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Literal

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.config import core as config_core

from .constants import (
    AGENTS_FILENAME,
    LONG_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
    SHORT_MEMORY_END_MARKER,
    SHORT_MEMORY_START_MARKER,
)

AmdScope = Literal["home", "chezmoi", "project", "project-subdir"]
AmdManagement = Literal["managed", "custom", "missing marker blocks"]
ProviderShimState = Literal["exact_shim", "shim", "custom", "missing"]

_PRUNED_DIR_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".sase",
        ".tox",
        ".venv",
        "__pycache__",
        "__pypackages__",
        "artifacts",
        "build",
        "coverage",
        "dist",
        "generated",
        "htmlcov",
        "node_modules",
        "site",
        "target",
        "venv",
    }
)
_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_MEMORY_REF_RE = re.compile(
    r"@?(?P<path>memory/(?P<tier>short|long)/[A-Za-z0-9_./-]+?\.md)"
)
_MARKERS = (
    SHORT_MEMORY_START_MARKER,
    SHORT_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    LONG_MEMORY_END_MARKER,
)
_SCOPE_ORDER: dict[AmdScope, int] = {
    "project": 0,
    "project-subdir": 1,
    "home": 2,
    "chezmoi": 3,
}


@dataclass(frozen=True)
class _ProviderShimStatus:
    """Status for a provider instruction file next to an ``AGENTS.md``."""

    filename: str
    state: ProviderShimState


@dataclass(frozen=True)
class _AmdDocumentEntry:
    """One discovered ``AGENTS.md`` file."""

    scope: AmdScope
    path: Path
    display_path: str
    h1_title: str | None
    management: AmdManagement
    short_memory_refs: int
    long_memory_refs: int
    provider_shims: tuple[_ProviderShimStatus, ...]


@dataclass(frozen=True)
class _AmdInventory:
    """All ``AGENTS.md`` files visible to ``sase amd list``."""

    project_root: Path
    home_root: Path
    chezmoi_root: Path | None
    use_chezmoi: bool
    entries: tuple[_AmdDocumentEntry, ...]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _find_marker_root(cwd: Path) -> Path | None:
    resolved = cwd.resolve(strict=False)
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists() or (candidate / ".hg").exists():
            return candidate
    return None


def _run_vcs_root(cwd: Path) -> Path | None:
    commands = (
        ("git", "-C", str(cwd), "rev-parse", "--show-toplevel"),
        ("hg", "--cwd", str(cwd), "root"),
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve(strict=False)
    return None


def _project_root(cwd: Path) -> Path:
    return _find_marker_root(cwd) or _run_vcs_root(cwd) or cwd.resolve(strict=False)


def _iter_project_agents(root: Path) -> tuple[Path, ...]:
    agents: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _PRUNED_DIR_NAMES)
        if AGENTS_FILENAME in filenames:
            agents.append(Path(dirpath) / AGENTS_FILENAME)
    return tuple(sorted(agents, key=lambda path: path.as_posix()))


def _h1_title(text: str | None) -> str | None:
    if text is None:
        return None
    match = _H1_RE.search(text)
    if match is None:
        return None
    return " ".join(match.group(1).split()) or None


def _management_state(text: str | None) -> AmdManagement:
    if text is None:
        return "custom"
    marker_presence = tuple(marker in text for marker in _MARKERS)
    if all(marker_presence):
        return "managed"
    if any(marker_presence):
        return "missing marker blocks"
    return "custom"


def _memory_reference_counts(text: str | None) -> tuple[int, int]:
    if text is None:
        return 0, 0
    refs_by_tier: dict[str, set[str]] = {"short": set(), "long": set()}
    for match in _MEMORY_REF_RE.finditer(text):
        refs_by_tier[match.group("tier")].add(match.group("path"))
    return len(refs_by_tier["short"]), len(refs_by_tier["long"])


def _provider_shims(directory: Path) -> tuple[_ProviderShimStatus, ...]:
    statuses: list[_ProviderShimStatus] = []
    for filename in PROVIDER_SHIM_FILES:
        path = directory / filename
        if not path.exists():
            statuses.append(_ProviderShimStatus(filename=filename, state="missing"))
            continue
        text = _read_text(path)
        if text == PROVIDER_SHIM_CONTENT:
            state: ProviderShimState = "exact_shim"
        elif text is not None and text.strip() == PROVIDER_SHIM_CONTENT.strip():
            state = "shim"
        else:
            state = "custom"
        statuses.append(_ProviderShimStatus(filename=filename, state=state))
    return tuple(statuses)


def _project_display_path(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _home_display_path(home_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(home_root)
    except ValueError:
        return path.as_posix()
    if relative.as_posix() == ".":
        return "~"
    return f"~/{relative.as_posix()}"


def _entry_for_agents(
    path: Path,
    *,
    scope: AmdScope,
    project_root: Path,
    home_root: Path,
) -> _AmdDocumentEntry:
    text = _read_text(path)
    short_count, long_count = _memory_reference_counts(text)
    if scope in {"project", "project-subdir"}:
        display_path = _project_display_path(project_root, path)
    else:
        display_path = _home_display_path(home_root, path)
    return _AmdDocumentEntry(
        scope=scope,
        path=path,
        display_path=display_path,
        h1_title=_h1_title(text),
        management=_management_state(text),
        short_memory_refs=short_count,
        long_memory_refs=long_count,
        provider_shims=_provider_shims(path.parent),
    )


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _build_amd_inventory(
    root: Path | None = None,
    *,
    home_root: Path | None = None,
    chezmoi_root: Path | None = None,
    include_chezmoi: bool | None = None,
) -> _AmdInventory:
    """Build the read-only AMD inventory for the current launch context."""
    cwd = Path.cwd() if root is None else root
    project_root = _project_root(cwd)
    live_home_root = _resolved(Path.home() if home_root is None else home_root)
    use_chezmoi = bool(config_core.get_use_chezmoi())
    source_root = _resolved(
        config_core.CHEZMOI_HOME if chezmoi_root is None else chezmoi_root
    )
    include_source = (
        include_chezmoi
        if include_chezmoi is not None
        else (use_chezmoi or source_root.exists())
    )

    entries: list[_AmdDocumentEntry] = []
    seen: set[Path] = set()

    for agents_path in _iter_project_agents(project_root):
        resolved_path = _resolved(agents_path)
        seen.add(resolved_path)
        scope: AmdScope = (
            "project"
            if agents_path.parent.resolve(strict=False) == project_root
            else "project-subdir"
        )
        entries.append(
            _entry_for_agents(
                agents_path,
                scope=scope,
                project_root=project_root,
                home_root=live_home_root,
            )
        )

    home_agents = live_home_root / AGENTS_FILENAME
    if home_agents.is_file():
        resolved_path = _resolved(home_agents)
        if resolved_path not in seen:
            seen.add(resolved_path)
            entries.append(
                _entry_for_agents(
                    home_agents,
                    scope="home",
                    project_root=project_root,
                    home_root=live_home_root,
                )
            )

    source_agents = source_root / AGENTS_FILENAME
    if include_source and source_agents.is_file():
        resolved_path = _resolved(source_agents)
        if resolved_path not in seen:
            seen.add(resolved_path)
            entries.append(
                _entry_for_agents(
                    source_agents,
                    scope="chezmoi",
                    project_root=project_root,
                    home_root=live_home_root,
                )
            )

    entries.sort(
        key=lambda entry: (
            _SCOPE_ORDER[entry.scope],
            entry.display_path,
        )
    )
    return _AmdInventory(
        project_root=project_root,
        home_root=live_home_root,
        chezmoi_root=source_root if include_source else None,
        use_chezmoi=use_chezmoi,
        entries=tuple(entries),
    )


def _management_text(state: AmdManagement) -> Text:
    styles: dict[AmdManagement, str] = {
        "managed": "green",
        "custom": "dim",
        "missing marker blocks": "yellow",
    }
    return Text(state, style=styles[state])


def _shim_summary(shims: tuple[_ProviderShimStatus, ...]) -> Text:
    ok = tuple(shim for shim in shims if shim.state in {"exact_shim", "shim"})
    custom = tuple(shim.filename for shim in shims if shim.state == "custom")
    missing = tuple(shim.filename for shim in shims if shim.state == "missing")
    loose = tuple(shim.filename for shim in shims if shim.state == "shim")

    if len(ok) == len(PROVIDER_SHIM_FILES) and not loose:
        return Text("all shims", style="green")

    text = Text()
    if ok:
        text.append(f"{len(ok)} shim{'s' if len(ok) != 1 else ''}", style="green")
    if loose:
        if text:
            text.append("; ", style="dim")
        text.append("noncanonical whitespace: ", style="yellow")
        text.append(", ".join(loose))
    if custom:
        if text:
            text.append("; ", style="dim")
        text.append("custom: ", style="yellow")
        text.append(", ".join(custom))
    if missing:
        if text:
            text.append("; ", style="dim")
        text.append("missing: ", style="red")
        text.append(", ".join(missing))
    return text or Text("missing all", style="red")


def _summary_panel(inventory: _AmdInventory) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Project root", str(inventory.project_root))
    summary.add_row("Home root", str(inventory.home_root))
    if inventory.chezmoi_root is not None:
        summary.add_row("Chezmoi source", str(inventory.chezmoi_root))
    summary.add_row("Use chezmoi", "yes" if inventory.use_chezmoi else "no")
    summary.add_row("AGENTS.md files", str(len(inventory.entries)))
    return Panel(summary, title="AMD Inventory", border_style="cyan")


def _documents_panel(inventory: _AmdInventory) -> Panel:
    if not inventory.entries:
        return Panel(
            Text(
                "No AGENTS.md files found in the project, home, or chezmoi roots.",
                style="dim",
            ),
            title="Agent Markdown Documents",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Scope", no_wrap=True)
    table.add_column("Path")
    table.add_column("H1")
    table.add_column("State", no_wrap=True)
    table.add_column("Memory", no_wrap=True)
    table.add_column("Provider shims")

    for entry in inventory.entries:
        table.add_row(
            entry.scope,
            entry.display_path,
            entry.h1_title or "-",
            _management_text(entry.management),
            f"short {entry.short_memory_refs} / long {entry.long_memory_refs}",
            _shim_summary(entry.provider_shims),
        )
    return Panel(table, title="Agent Markdown Documents", border_style="cyan")


def _build_amd_inventory_dashboard(inventory: _AmdInventory) -> Group:
    return Group(_summary_panel(inventory), _documents_panel(inventory))


def _render_amd_inventory(
    inventory: _AmdInventory, *, console: Console | None = None
) -> None:
    target = console or Console()
    target.print(_build_amd_inventory_dashboard(inventory))


def run_amd_list(args: argparse.Namespace, *, console: Console | None = None) -> int:
    """Render the AMD inventory and return a process exit code."""
    _ = args
    _render_amd_inventory(_build_amd_inventory(), console=console)
    return 0


__all__ = ["run_amd_list"]
