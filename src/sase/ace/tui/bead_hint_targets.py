"""Canonical bead-hint targets for the Agents tab.

Bead hints are artifact refs (``bead:<id>``), not file paths. The generated
bead page path (``pages/<root>/<id>.md``) is sidecar-repo-relative and may not
be published yet, so handing it to the view pipeline fails its existence check
against the TUI process's CWD. The ``bead:`` scheme prefix is itself the
discriminator: real hint targets are absolute (or ``~``) filesystem paths, so
they never parse as ``bead:`` refs.
"""

from __future__ import annotations

from sase.ace.tui.bead_touches import BEAD_READ_REF_PREFIX
from sase.artifact_ref_operations import parse_artifact_ref

__all__ = ["bead_hint_target", "bead_id_from_hint_target"]


def bead_hint_target(bead_id: str) -> str | None:
    """Return the canonical ``bead:<id>`` ref, or ``None`` when unparseable."""
    try:
        return parse_artifact_ref(f"bead:{bead_id.strip()}").rendered
    except ValueError:
        return None


def bead_id_from_hint_target(target: str) -> str | None:
    """Return the bead ID carried by a ``bead:`` hint target, if any."""
    if not target.startswith(BEAD_READ_REF_PREFIX):
        return None
    try:
        parsed = parse_artifact_ref(target)
    except ValueError:
        return None
    if parsed.kind_type != "bead":
        return None
    bead_id = parsed.payload.id
    if bead_id is None or not bead_id.strip():
        return None
    return bead_id
