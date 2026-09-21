"""Stable executable resolution for axe daemon startup."""

import re
import shutil
import sys
from pathlib import Path


_EPHEMERAL_WORKSPACE_RE = re.compile(r"^sase_\d+$")


def _path_is_ephemeral_workspace(path: Path) -> bool:
    """Return True when *path* is inside a numbered SASE workspace clone."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return any(_EPHEMERAL_WORKSPACE_RE.fullmatch(part) for part in resolved.parts)


def _resolve_primary_workspace_sase() -> str | None:
    """Resolve a non-ephemeral primary workspace ``sase`` executable."""
    try:
        from sase.bead.workspace import resolve_primary_workspace

        primary = resolve_primary_workspace()
    except Exception:
        return None
    if primary is None or _path_is_ephemeral_workspace(primary):
        return None
    candidate = primary / ".venv" / "bin" / "sase"
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_sase_executable(*, prefer_canonical: bool) -> str | None:
    """Find the best ``sase`` executable for launching long-lived daemons."""
    current_bin = Path(sys.executable).parent / "sase"
    current = str(current_bin) if current_bin.exists() else None
    path_sase = shutil.which("sase")

    candidates: list[str | None]
    if prefer_canonical:
        candidates = [
            str(Path.home() / ".local" / "bin" / "sase"),
            path_sase,
            _resolve_primary_workspace_sase(),
            current,
        ]
    else:
        candidates = [
            current,
            path_sase,
            str(Path.home() / ".local" / "bin" / "sase"),
        ]

    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate != path_sase and not candidate_path.exists():
            continue
        if prefer_canonical and _path_is_ephemeral_workspace(candidate_path):
            continue
        return str(candidate_path)
    return None


def canonical_axe_start_command() -> str | None:
    """Return a stable ``sase`` executable for axe daemon startup."""
    return _resolve_sase_executable(prefer_canonical=True)
