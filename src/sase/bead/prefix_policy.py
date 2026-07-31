"""Issue-prefix derivation policy for bead stores.

Resolution is deliberately keyed off the process CWD, not ``root_dir``:
sidecar bead stores materialize under ``~/.sase/...`` or
``<workspace>/sase/repos/beads``, whose own path says nothing about the
owning project, while cwd-based project inference still resolves correctly.
Do not "fix" this to use ``root_dir``-based inference instead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead.project_name import infer_project_name_from_cwd


def _is_safe_bead_prefix(prefix: str) -> bool:
    """Return whether *prefix* is safe to use as a bead issue prefix.

    Bead IDs must keep matching ``^[^\\s.]+-[0-9a-z]+(?:\\.\\d+)*$`` so agent
    names launched by ``sase bead work`` still resolve back to their bead, and
    ``--`` is the reserved agent-family separator, so a prefix containing it
    would make bead-named agents parse as family members.
    """
    if not prefix:
        return False
    if any(char.isspace() for char in prefix):
        return False
    if "." in prefix or "/" in prefix or "\\" in prefix:
        return False
    if "--" in prefix:
        return False
    if prefix.endswith("-"):
        return False
    return True


def default_issue_prefix(root_dir: Path) -> str:
    """Return the default issue prefix for a bead store rooted at *root_dir*."""
    key = infer_project_name_from_cwd()
    if key:
        from sase.project_display_names import project_display_name_for

        label = project_display_name_for(key)
        if _is_safe_bead_prefix(label):
            return label
        if _is_safe_bead_prefix(key):
            return key

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            cwd=root_dir,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            # Extract repo name from URL (handles both HTTPS and SSH)
            name = url.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except FileNotFoundError:
        pass
    return root_dir.resolve().name


def stale_key_prefix_report(beads_dir: Path) -> tuple[str, str] | None:
    """Return ``(stored_prefix, corrected_prefix)`` for a key-leaked store.

    Returns ``None`` in every other case, including a deliberately customized
    prefix (``beads``, ``gold``, a legacy name): it cannot be distinguished
    from an intentional choice, so it must not be flagged.
    """
    from sase.bead.config import load_config

    stored = load_config(beads_dir).get("issue_prefix")
    if not isinstance(stored, str) or not stored:
        return None

    key = infer_project_name_from_cwd()
    if key is None or stored != key:
        return None

    from sase.project_display_names import project_display_name_for

    label = project_display_name_for(key)
    if label == key or not _is_safe_bead_prefix(label):
        return None

    return stored, label
