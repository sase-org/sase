"""Detect a foreign ``sase`` build silently answering a workspace's own check."""

from __future__ import annotations

from pathlib import Path
import sys

_WARNING_TEMPLATE = (
    "this check ran under {running_python}, not this workspace's own "
    "{pinned_sase} -- a foreign sase build can silently answer a "
    "memory-drift check with different generator templates. Re-run with "
    "the pinned build, e.g. `{pinned_sase} memory init --check`, or `just check`."
)


def workspace_pinned_sase_mismatch_warning(project_root: Path) -> str | None:
    """Warn when *project_root* has its own ``sase`` build we are not running.

    A workspace that carries its own editable ``sase`` install (an ephemeral
    ``sase_<N>`` dev checkout, for example) should always be checked by that
    build, ``{project_root}/.venv/bin/sase`` -- the one ``just check``'s
    ``validate`` recipe invokes. A bare ``sase`` on ``PATH`` can resolve to a
    completely different checkout (a separate ``uv tool install``), which
    then answers this workspace's memory-drift check with its own,
    independently versioned generator templates.
    """
    pinned_sase = project_root / ".venv" / "bin" / "sase"
    pinned_python = project_root / ".venv" / "bin" / "python"
    if not pinned_sase.is_file() or not pinned_python.is_file():
        return None
    running_python = Path(sys.executable).resolve()
    if running_python == pinned_python.resolve():
        return None
    return _WARNING_TEMPLATE.format(
        running_python=running_python, pinned_sase=pinned_sase
    )


__all__ = ["workspace_pinned_sase_mismatch_warning"]
