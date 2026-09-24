"""Proc attribution helpers shared by CLI and hand-off launch."""

from __future__ import annotations

import re
from pathlib import Path


def infer_proc_attribution(
    cwd: Path, project: str | None
) -> tuple[str | None, int | None]:
    """Return the project and workspace number a proc should be attributed to."""

    name = project
    if not name:
        try:
            from sase.bead.project_name import infer_project_name_from_cwd

            name = infer_project_name_from_cwd(str(cwd))
        except Exception:
            name = None
    if not name:
        return None, None
    match = re.search(rf"(?:^|/){re.escape(name)}_(\d+)(?:/|$)", str(cwd))
    return name, int(match.group(1)) if match else None


__all__ = ["infer_proc_attribution"]
