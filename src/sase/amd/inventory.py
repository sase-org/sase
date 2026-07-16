"""Inventory and rendering for ``sase memory agent-docs list``."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Literal, cast

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.config import core as config_core

from ._agents_doc import parse_amd_agents_document
from ._shared import provider_shim_specs, provider_status_for_spec
from .constants import (
    AGENTS_FILENAME,
    PROVIDER_SHIM_FILES,
)

AmdScope = Literal["home", "chezmoi", "project", "project-subdir"]
AmdManagement = Literal["managed", "custom", "incomplete managed structure"]
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
    r"(?P<loaded>@)?(?P<path>(?:sase/)?memory/[A-Za-z0-9_.-]+\.md)"
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
    """All ``AGENTS.md`` files visible to ``sase memory agent-docs list``."""

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
    linked_repo_parent = root.resolve(strict=False) / "sase"
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath).resolve(strict=False)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _PRUNED_DIR_NAMES
            and not (current == linked_repo_parent and name == "repos")
        )
        if AGENTS_FILENAME in filenames:
            agents.append(Path(dirpath) / AGENTS_FILENAME)
    return tuple(sorted(agents, key=lambda path: path.as_posix()))


def discover_project_agent_docs(root: Path) -> tuple[Path, ...]:
    """Return project ``AGENTS.md`` files using agent-docs inventory pruning."""
    return _iter_project_agents(root)


def _h1_title(text: str | None) -> str | None:
    if text is None:
        return None
    match = _H1_RE.search(text)
    if match is None:
        return None
    return " ".join(match.group(1).split()) or None


def _broad_memory_reference_counts(text: str | None) -> tuple[int, int]:
    if text is None:
        return 0, 0
    loaded_refs: set[str] = set()
    plain_refs: set[str] = set()
    for match in _MEMORY_REF_RE.finditer(text):
        path = match.group("path")
        if match.group("loaded"):
            loaded_refs.add(path)
        else:
            plain_refs.add(path)
    return len(loaded_refs), len(plain_refs)


def _management_state_and_memory_counts(
    text: str | None,
) -> tuple[AmdManagement, int, int]:
    parsed = parse_amd_agents_document(text)
    if parsed.has_short_section and parsed.has_long_section:
        management: AmdManagement = "managed"
    elif parsed.has_memory_structure:
        management = "incomplete managed structure"
    else:
        short_count, long_count = _broad_memory_reference_counts(text)
        return "custom", short_count, long_count

    short_count = len(set(parsed.short_memory_paths))
    long_count = len({entry.path for entry in parsed.long_memory_entries})
    return management, short_count, long_count


def _provider_shims(
    directory: Path,
    *,
    agents_content: str,
    chezmoi_home_roots: tuple[Path, ...] = (),
) -> tuple[_ProviderShimStatus, ...]:
    statuses: list[_ProviderShimStatus] = []
    for spec in provider_shim_specs(
        directory,
        agents_content=agents_content,
        chezmoi_home_roots=chezmoi_home_roots,
    ):
        state, _error = provider_status_for_spec(spec)
        statuses.append(
            _ProviderShimStatus(
                filename=spec.filename,
                state=cast(ProviderShimState, state),
            )
        )
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
    chezmoi_home_roots: tuple[Path, ...] = (),
) -> _AmdDocumentEntry:
    text = _read_text(path)
    management, short_count, long_count = _management_state_and_memory_counts(text)
    if scope in {"project", "project-subdir"}:
        display_path = _project_display_path(project_root, path)
    else:
        display_path = _home_display_path(home_root, path)
    return _AmdDocumentEntry(
        scope=scope,
        path=path,
        display_path=display_path,
        h1_title=_h1_title(text),
        management=management,
        short_memory_refs=short_count,
        long_memory_refs=long_count,
        provider_shims=_provider_shims(
            path.parent,
            agents_content=text or "",
            chezmoi_home_roots=chezmoi_home_roots,
        ),
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
    chezmoi_home_roots = (source_root,)

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
                chezmoi_home_roots=chezmoi_home_roots,
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
                    chezmoi_home_roots=chezmoi_home_roots,
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
                    chezmoi_home_roots=chezmoi_home_roots,
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
        "incomplete managed structure": "yellow",
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
    return Panel(summary, title="Agent Documents", border_style="cyan")


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
