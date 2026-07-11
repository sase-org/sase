"""SDD path, date, and directory resolution helpers."""

from datetime import datetime
from pathlib import Path

_SDD_PROMPT_KINDS = {"prompts", "specs"}
SDD_CANONICAL_DIRS = (
    "beads",
    "plans",
    "prompts",
    "research",
)
_SDD_CANONICAL_DIRS = set(SDD_CANONICAL_DIRS)


def get_yyyymm(dt: datetime | None = None) -> str:
    """Return a YYYYMM string for SDD subdirectory organization.

    Uses the configured timezone (same as ``add_create_time_frontmatter``).
    """
    if dt is None:
        from sase.core.time import get_timezone

        dt = datetime.now(get_timezone())
    return dt.strftime("%Y%m")


def sdd_kind_roots(base_dir: Path, kind: str) -> list[Path]:
    """Return lookup roots for an SDD kind, including legacy prompt aliases."""
    aliases: tuple[str, ...]
    if kind in _SDD_PROMPT_KINDS:
        aliases = ("prompts", "specs")
    else:
        aliases = (kind,)
    roots: list[Path] = []
    seen: set[Path] = set()
    for alias in aliases:
        for root in (base_dir / "sdd" / alias, base_dir / alias):
            if root not in seen:
                roots.append(root)
                seen.add(root)
    return roots


def find_sdd_file(base_dir: Path, kind: str, name: str) -> Path | None:
    """Search for an SDD file in canonical in-tree or companion layouts.

    Version-controlled paths live under ``sdd/{kind}``. Local SDD mode passes
    ``.sase/sdd`` as ``base_dir``, where ``{kind}`` is the child directory.

    Returns the first match, or ``None`` if not found.
    """
    for root in sdd_kind_roots(base_dir, kind):
        flat = root / name
        if flat.exists():
            return flat
        matches = sorted(root.glob(f"*/{name}"))
        if matches:
            return matches[0]
    return None


def resolve_sdd_readme_path(
    path: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the generated SDD README target.

    ``path`` may point at either a project root or an SDD root. Existing SDD
    roots and paths named ``sdd`` are treated as SDD roots; other paths are
    treated as project roots so init can create a missing ``sdd/`` directory.
    """
    base = Path.cwd() if cwd is None else cwd
    if path is None:
        return (base / "sdd" / "README.md").resolve()

    target = Path(path).expanduser()
    if not target.is_absolute():
        target = base / target

    if looks_like_sdd_root(target):
        return (target / "README.md").resolve()
    return (target / "sdd" / "README.md").resolve()


def resolve_sdd_asset_path(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve the generated SDD directory map target."""
    from sase.sdd._init_files import SDD_DIRECTORY_MAP_RELATIVE_PATH

    return (
        resolve_sdd_readme_path(path, cwd=cwd).parent / SDD_DIRECTORY_MAP_RELATIVE_PATH
    )


def looks_like_sdd_root(path: Path) -> bool:
    if path.name == "sdd":
        return True
    if not path.is_dir():
        return False
    return any((path / dirname).is_dir() for dirname in _SDD_CANONICAL_DIRS)


def get_primary_workspace_dir(
    workspace_dir: str,
    workspace_num: int,
    *,
    project_home: Path | None = None,
) -> str:
    """Derive primary workspace dir from current workspace.

    Prefer the project's configured WORKSPACE_DIR (source of truth).
    Fall back to suffix-stripping based on workspace_num.

    For workspace_num == 1, returns workspace_dir as-is.
    For workspace_num > 1, strips the ``_{workspace_num}`` suffix.
    """
    configured_primary = resolve_primary_from_project(
        workspace_dir,
        project_home=project_home,
    )
    if configured_primary:
        return configured_primary

    marker_primary = _resolve_primary_from_marker(workspace_dir)
    if marker_primary:
        return marker_primary

    if workspace_num <= 1:
        return workspace_dir
    suffix = f"_{workspace_num}"
    stripped = workspace_dir.rstrip("/")
    parts = stripped.split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith(suffix):
            parts[i] = parts[i][: -len(suffix)]
            return "/".join(parts)
    return workspace_dir


def resolve_primary_from_project(
    workspace_dir: str,
    *,
    project_home: Path | None = None,
) -> str | None:
    """Resolve primary workspace from the project's WORKSPACE_DIR field.

    Returns ``None`` if project/workspace metadata cannot be resolved.
    """
    try:
        from sase.workspace_provider import get_workspace_name
        from sase.workspace_provider.utils import parse_workspace_dir

        project_name = get_workspace_name(workspace_dir)
        if not project_name:
            return None

        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        home = Path.home() if project_home is None else project_home
        project_dir = home / ".sase" / "projects" / project_name
        project_file = preferred_project_spec_path(str(project_dir), project_name)
        primary = parse_workspace_dir(project_file)
        if not primary:
            return None
        return primary.rstrip("/")
    except Exception:
        return None


def _resolve_primary_from_marker(workspace_dir: str) -> str | None:
    """Resolve the primary workspace from a managed checkout marker.

    Managed (non-adjacent) checkouts carry a ``.sase/checkout.json`` marker
    recording the primary workspace they were cloned from. Reading it recovers
    the primary directly, which suffix-stripping cannot do when the managed
    checkout lives under a state root far from the primary (e.g. an ephemeral
    clone under ``~/.local/state/sase/workspaces``). Returns ``None`` when no
    readable marker is found.
    """
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(Path(workspace_dir).expanduser()))
        if found is None:
            return None
        primary = found[1].primary_workspace_dir
        if not primary:
            return None
        return primary.rstrip("/")
    except Exception:
        return None


_sdd_kind_roots = sdd_kind_roots
