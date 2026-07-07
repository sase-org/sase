"""Helpers for uv dependency override files used by editable tool installs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.core.paths import ensure_sase_directory
from sase.uv_tool.receipt import Requirement

_DEFAULT_FILENAME = "editable-overrides.txt"


def editable_override_lines(requirements: Iterable[Requirement]) -> tuple[str, ...]:
    """Return ``-e <path>`` override lines for editable requirements.

    One line is emitted per normalized distribution name. The first editable
    entry wins, preserving the receipt or reconstructed-set order passed by the
    caller.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for requirement in requirements:
        if requirement.editable is None:
            continue
        key = requirement.normalized_name
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"-e {requirement.editable}")
    return tuple(lines)


def write_editable_overrides(
    requirements: Iterable[Requirement],
    *,
    path: str | Path | None = None,
) -> Path | None:
    """Write editable uv overrides and return the path, or ``None`` if unused.

    Write failures degrade to ``None`` so callers can fall back to the same uv
    command shape they used before editable overrides existed.
    """
    lines = editable_override_lines(requirements)
    if not lines:
        return None

    try:
        target = (
            Path(path)
            if path is not None
            else Path(ensure_sase_directory("uv")) / _DEFAULT_FILENAME
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    return target


__all__ = ["editable_override_lines", "write_editable_overrides"]
