"""Shared probes for recognizing canonical bead-store state."""

from pathlib import Path


def has_bead_state(root: Path) -> bool:
    """Return whether *root* contains trusted canonical bead-store markers."""
    return (root / "config.json").is_file() or (root / "events").is_dir()
