"""Configuration accessors for the external tracker mirror."""

from __future__ import annotations


def excluded_issue_labels() -> frozenset[str]:
    """Return the case-folded ``external_mirror.exclude_labels`` set.

    Empty by default, which keeps the mirrored bead list a strict superset of
    the tracker's issue list.
    """
    try:
        from sase.config import load_merged_config

        data = load_merged_config()
        if not isinstance(data, dict):
            return frozenset()
        section = data.get("external_mirror", {}) or {}
        labels = section.get("exclude_labels", []) if isinstance(section, dict) else []
    except Exception:
        return frozenset()
    if not isinstance(labels, list):
        return frozenset()
    return frozenset(
        label.casefold() for label in labels if isinstance(label, str) and label
    )


__all__ = ["excluded_issue_labels"]
