"""Helpers for uv dependency override files used by editable tool installs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.core.paths import ensure_sase_directory
from sase.uv_tool.receipt import Requirement
from sase.version._models import CORE_DISTRIBUTION_NAME, HOST_DISTRIBUTION_NAME
from sase.version._utils import normalize_distribution_name

_DEFAULT_FILENAME = "editable-overrides.txt"
_HOST_KEY = normalize_distribution_name(HOST_DISTRIBUTION_NAME)


def editable_override_lines(requirements: Iterable[Requirement]) -> tuple[str, ...]:
    """Return uv override lines for editable requirements.

    One ``-e <path>`` line is emitted per normalized distribution name. The
    first editable entry wins, preserving the receipt or reconstructed-set
    order passed by the caller.

    When the host ``sase`` package itself is editable (a dev install), an
    unconstrained ``sase-core-rs`` override is appended so the published
    version window in the host's pyproject never applies: dev installs build
    ``sase_core_rs`` from the local checkout, and uv must not downgrade or
    replace that build just because the checkout version is outside the
    window published for wheel installs.
    """
    seen: set[str] = set()
    lines: list[str] = []
    host_editable = False
    for requirement in requirements:
        if requirement.editable is None:
            continue
        key = requirement.normalized_name
        if key == _HOST_KEY:
            host_editable = True
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"-e {requirement.editable}")
    if host_editable:
        lines.append(CORE_DISTRIBUTION_NAME)
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
