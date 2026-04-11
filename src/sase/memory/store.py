"""Memory file CRUD operations."""

from datetime import date
from pathlib import Path

from sase.memory.models import MemoryFile, MemoryType
from sase.memory.repo import auto_commit, get_repo_path, repo_exists


def _require_repo() -> Path:
    """Return repo path or raise with a helpful message."""
    if not repo_exists():
        raise RuntimeError("Memory repo not initialized. Run: sase memory init")
    return get_repo_path()


def _resolve_dir(project: str | None, system: bool) -> Path:
    """Resolve the target directory for a memory file."""
    repo = _require_repo()
    if project:
        base = repo / "projects" / project
    else:
        base = repo / "global"
    if system:
        return base / "system"
    return base


def _slugify(name: str) -> str:
    """Convert a memory name to a filename-safe slug."""
    slug = name.lower().replace(" ", "_")
    # Strip anything that's not alphanumeric, underscore, or hyphen
    slug = "".join(c for c in slug if c.isalnum() or c in ("_", "-"))
    return slug


def add(
    name: str,
    description: str,
    memory_type: MemoryType,
    body: str,
    project: str | None = None,
    system: bool = False,
) -> Path:
    """Create a new memory file and auto-commit."""
    target_dir = _resolve_dir(project, system)
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_slugify(name)}.md"
    filepath = target_dir / filename

    if filepath.exists():
        raise FileExistsError(
            f"Memory already exists: {filepath.relative_to(get_repo_path())}"
        )

    mem = MemoryFile(
        name=name,
        description=description,
        memory_type=memory_type,
        created=date.today().isoformat(),
        body=body,
        project=project,
        system=system,
    )
    filepath.write_text(mem.to_markdown())

    scope = f"projects/{project}" if project else "global"
    auto_commit(f"memory: add {name} ({scope})")
    return filepath


def show(name: str, project: str | None = None) -> MemoryFile:
    """Read and parse a memory file by name."""
    filepath = _find_file(name, project)
    if filepath is None:
        scope = f"project '{project}'" if project else "global"
        raise FileNotFoundError(f"Memory '{name}' not found in {scope}")
    return MemoryFile.from_markdown(filepath.read_text(), project=project)


def list_memories(project: str | None = None) -> list[tuple[str, MemoryFile]]:
    """List all memories, returning (relative_path, MemoryFile) tuples.

    If *project* is given, only list that project's memories.
    If *project* is None, list all memories (global + all projects).
    """
    repo = _require_repo()
    results: list[tuple[str, MemoryFile]] = []

    dirs_to_scan: list[tuple[Path, str | None]] = []

    if project:
        proj_dir = repo / "projects" / project
        if proj_dir.is_dir():
            dirs_to_scan.append((proj_dir, project))
    else:
        # Global
        global_dir = repo / "global"
        if global_dir.is_dir():
            dirs_to_scan.append((global_dir, None))
        # All projects
        projects_dir = repo / "projects"
        if projects_dir.is_dir():
            for p in sorted(projects_dir.iterdir()):
                if p.is_dir() and p.name != ".gitkeep":
                    dirs_to_scan.append((p, p.name))

    for base, proj in dirs_to_scan:
        for md_file in sorted(base.rglob("*.md")):
            if md_file.name == ".gitkeep":
                continue
            try:
                mem = MemoryFile.from_markdown(md_file.read_text(), project=proj)
                rel = str(md_file.relative_to(repo))
                results.append((rel, mem))
            except (ValueError, KeyError):
                continue  # Skip malformed files

    return results


def rm(name: str, project: str | None = None) -> Path:
    """Remove a memory file and auto-commit."""
    filepath = _find_file(name, project)
    if filepath is None:
        scope = f"project '{project}'" if project else "global"
        raise FileNotFoundError(f"Memory '{name}' not found in {scope}")

    filepath.unlink()

    # Clean up empty directories (but not the top-level ones)
    _cleanup_empty_dirs(filepath.parent, get_repo_path())

    scope = f"projects/{project}" if project else "global"
    auto_commit(f"memory: remove {name} ({scope})")
    return filepath


def _find_file(name: str, project: str | None) -> Path | None:
    """Find a memory file by name, searching system/ and non-system dirs."""
    repo = _require_repo()
    slug = _slugify(name)
    filename = f"{slug}.md"

    if project:
        base = repo / "projects" / project
    else:
        base = repo / "global"

    # Check system/ first, then base
    candidates = [
        base / "system" / filename,
        base / filename,
    ]

    # Also search subdirectories (decisions/, feedback/, etc.)
    if base.is_dir():
        for sub in sorted(base.iterdir()):
            if sub.is_dir() and sub.name != "system":
                candidates.append(sub / filename)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def _cleanup_empty_dirs(directory: Path, stop_at: Path) -> None:
    """Remove empty directories up to (but not including) stop_at."""
    current = directory
    while current != stop_at and current.is_dir():
        # Don't remove if it still has content (besides .gitkeep)
        remaining = [f for f in current.iterdir() if f.name != ".gitkeep"]
        if remaining:
            break
        # Remove .gitkeep if it's the only thing left
        gitkeep = current / ".gitkeep"
        if gitkeep.exists():
            gitkeep.unlink()
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
