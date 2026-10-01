"""Scope assembly for memory history.

A scope is one owning repository plus the paths that hold memory in it
(epic design ``plan:202609/memory_history.md`` §3):

- ``project:<name>`` is the project checkout, with ``sase/memory``,
  legacy ``memory``, and every ``AGENTS.md`` plus its shims.
- ``home`` is the chezmoi source repo, with ``home/sase/memory``,
  ``home/memory``, and the ``home/*.md.tmpl`` instruction templates.
  Without chezmoi there is no home history (``NO VCS``).

Python supplies exactly these inputs; everything else (lineage,
classification, snapshots) is computed in ``sase-core``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.amd._agents_doc import is_managed_agents_document
from sase.amd.constants import AGENTS_TEMPLATE_FILENAME, PROVIDER_SHIM_FILES
from sase.amd.inventory import discover_project_agent_docs
from sase.core.memory_history_wire import (
    MemoryHistoryInstructionFile,
    MemoryHistoryScope,
)
from sase.main.init_memory.root_rendering_notes import (
    generated_memory_note_relative_paths,
)

#: Canonical and legacy memory roots inside a project checkout.
PROJECT_MEMORY_ROOTS: tuple[str, ...] = ("sase/memory", "memory")

#: Canonical and legacy memory roots inside the chezmoi source repo.
HOME_MEMORY_ROOTS: tuple[str, ...] = ("home/sase/memory", "home/memory")

#: Render directory of the home instruction templates, repo-relative.
HOME_INSTRUCTION_DIR = "home"

#: Repo-relative home instruction template and its shim templates.
HOME_AGENTS_TEMPLATE = "home/AGENTS.md.tmpl"

#: Project config file whose co-change marks an instruction version
#: config-driven. Stays out of the git walk (cause attribution only).
PROJECT_CONFIG_PATH = "sase/sase.yml"

#: Renderer source prefix. Non-empty only for the sase repo itself.
#: No trailing slash: core matches ``path == base`` or a ``base + "/"``
#: prefix.
AMD_RENDERER_PREFIX = "src/sase/amd"

#: Snapshot root under the home directory (core appends ``v<schema>``).
MEMORY_HISTORY_CACHE_SUBDIR = Path(".sase") / "cache" / "memory_history"


class HistoryScopeError(RuntimeError):
    """Raised when a requested history scope cannot be built."""


def _default_cache_dir(home: Path | None = None) -> Path:
    """Return the caller-supplied snapshot root for history scopes."""
    root = Path.home() if home is None else home
    return root / MEMORY_HISTORY_CACHE_SUBDIR


def git_repo_root(start: Path) -> Path | None:
    """Return the git toplevel containing *start*, or ``None``."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    toplevel = proc.stdout.decode("utf-8", "replace").strip()
    if not toplevel:
        return None
    return Path(toplevel)


def _instruction_entry_for_agents(
    repo_root: Path,
    agents_path: Path,
) -> MemoryHistoryInstructionFile | None:
    """Build one scope instruction entry for an ``AGENTS.md`` path."""
    try:
        relative = agents_path.relative_to(repo_root).as_posix()
    except ValueError:
        return None
    parent = agents_path.parent
    try:
        dir_rel = parent.relative_to(repo_root).as_posix()
    except ValueError:
        return None
    directory = "." if dir_rel == "." else dir_rel
    prefix = "" if directory == "." else f"{directory}/"
    try:
        text = agents_path.read_text(encoding="utf-8")
    except OSError:
        text = None
    return MemoryHistoryInstructionFile(
        dir=directory,
        agents_path=relative,
        shim_paths=tuple(f"{prefix}{shim}" for shim in PROVIDER_SHIM_FILES),
        template=agents_path.name == AGENTS_TEMPLATE_FILENAME,
        managed=(is_managed_agents_document(text) if text is not None else False),
    )


def build_project_scope(
    project_root: Path,
    *,
    project_name: str | None = None,
    cache_dir: Path | None = None,
) -> MemoryHistoryScope:
    """Build the ``project:<name>`` scope for a project checkout."""
    from sase.main.init_memory.config import project_memory_name

    root = project_root.expanduser()
    repo_root = git_repo_root(root)
    if repo_root is None:
        raise HistoryScopeError(
            f"project checkout {root} is not inside a git work tree "
            "(NO VCS: commit the checkout to start its history)"
        )
    name = project_name or project_memory_name(root)
    entries: list[MemoryHistoryInstructionFile] = []
    for agents_path in discover_project_agent_docs(repo_root):
        entry = _instruction_entry_for_agents(repo_root, agents_path)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: entry.dir)
    generated = tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=True)
    )
    config_paths: tuple[str, ...] = (
        (PROJECT_CONFIG_PATH,) if (repo_root / PROJECT_CONFIG_PATH).exists() else ()
    )
    renderer_prefixes: tuple[str, ...] = (
        (AMD_RENDERER_PREFIX,) if (repo_root / "src" / "sase" / "amd").is_dir() else ()
    )
    return MemoryHistoryScope(
        scope_key=f"project:{name}",
        scope_kind="project",
        repo_root=repo_root.as_posix(),
        memory_roots=PROJECT_MEMORY_ROOTS,
        instruction_files=tuple(entries),
        generated_notes=generated,
        renderer_prefixes=renderer_prefixes,
        config_paths=config_paths,
        cache_dir=(cache_dir or _default_cache_dir()).as_posix(),
    )


def _home_source_repo_root() -> Path | None:
    """Return the chezmoi source repo toplevel, or ``None``."""
    from sase.config.core import CHEZMOI_HOME

    return git_repo_root(CHEZMOI_HOME.expanduser())


def _chezmoi_enabled() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    from sase.config import get_use_chezmoi

    return bool(get_use_chezmoi())


def build_home_scope(
    *,
    cache_dir: Path | None = None,
) -> MemoryHistoryScope | None:
    """Build the ``home`` scope, or ``None`` when home has no history.

    Returns ``None`` when chezmoi is disabled or the chezmoi source is
    not in git (``NO VCS``): deployed ``~/sase/memory/*`` files then
    have no history to read.
    """
    if not _chezmoi_enabled():
        return None
    repo_root = _home_source_repo_root()
    if repo_root is None:
        return None
    try:
        agents_template = repo_root / HOME_AGENTS_TEMPLATE
        managed = is_managed_agents_document(
            agents_template.read_text(encoding="utf-8")
        )
    except OSError:
        managed = False
    generated = tuple(
        path.as_posix()
        for path in generated_memory_note_relative_paths(include_project_memory=False)
    )
    return MemoryHistoryScope(
        scope_key="home",
        scope_kind="home",
        repo_root=repo_root.as_posix(),
        memory_roots=HOME_MEMORY_ROOTS,
        instruction_files=(
            MemoryHistoryInstructionFile(
                dir=HOME_INSTRUCTION_DIR,
                agents_path=HOME_AGENTS_TEMPLATE,
                shim_paths=tuple(
                    f"{HOME_INSTRUCTION_DIR}/{shim}.tmpl"
                    for shim in PROVIDER_SHIM_FILES
                ),
                template=True,
                managed=managed,
            ),
        ),
        generated_notes=generated,
        renderer_prefixes=(),
        config_paths=(),
        cache_dir=(cache_dir or _default_cache_dir()).as_posix(),
    )


def map_deployed_home_path(path: Path) -> str | None:
    """Map a deployed home path to its chezmoi source subject path.

    ``~/sase/memory/*`` maps into ``home/sase/memory/*`` and
    ``~/AGENTS.md`` (plus its shims) maps to the ``home/*.md.tmpl``
    instruction templates. Returns ``None`` when *path* has no source
    subject. Used by the pager provider; the CLI accepts these spellings
    directly.
    """
    home = Path.home()
    try:
        relative = path.expanduser().relative_to(home)
    except (ValueError, RuntimeError):
        return None
    parts = relative.parts
    if not parts:
        return None
    if parts[0] == "AGENTS.md" and len(parts) == 1:
        return HOME_AGENTS_TEMPLATE
    if len(parts) == 1 and parts[0] in PROVIDER_SHIM_FILES:
        stem = parts[0]
        return f"{HOME_INSTRUCTION_DIR}/{stem}.tmpl"
    if parts[0] == "sase" and len(parts) >= 3 and parts[1] == "memory":
        return "/".join(("home", *parts))
    return None


__all__ = [
    "AMD_RENDERER_PREFIX",
    "HistoryScopeError",
    "HOME_AGENTS_TEMPLATE",
    "HOME_INSTRUCTION_DIR",
    "HOME_MEMORY_ROOTS",
    "MEMORY_HISTORY_CACHE_SUBDIR",
    "PROJECT_CONFIG_PATH",
    "PROJECT_MEMORY_ROOTS",
    "build_home_scope",
    "build_project_scope",
    "git_repo_root",
    "map_deployed_home_path",
]
