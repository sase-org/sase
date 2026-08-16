"""Whether the current checkout may create first-party feature flags."""

from __future__ import annotations

from pathlib import Path

from sase.content_layout import (
    discover_project_root,
    resolve_project_config_read_path,
)
from sase.project_management import project_management_status


def project_is_sase_managed(cwd: Path | None = None) -> bool:
    """Return whether *cwd*'s project opts into SASE-managed first-party work.

    The feature-flag registry lives in this repo's ``src/sase/``. ``sase flag
    new`` therefore only belongs in a checkout whose local config sets
    ``is_sase_managed: true``.
    """
    start = cwd if cwd is not None else Path.cwd()
    root = discover_project_root(start) or start
    try:
        config_path = resolve_project_config_read_path(root)
    except Exception:  # noqa: BLE001 - a missing or colliding layout is "not managed".
        return False
    if config_path is None:
        return False
    return project_management_status(config_path).is_sase_managed is True


__all__ = ["project_is_sase_managed"]
