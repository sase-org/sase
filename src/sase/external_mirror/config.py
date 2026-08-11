"""Configuration accessors for the external tracker mirror."""

from __future__ import annotations


def excluded_issue_labels() -> frozenset[str]:
    """Return the case-folded ``external_mirror.exclude_labels`` set.

    Empty by default, which keeps the mirrored bead list a strict superset of
    the tracker's issue list.
    """
    return _casefolded_string_list("exclude_labels")


def mirrored_pr_authors() -> frozenset[str]:
    """Return the case-folded ``external_mirror.pr_authors`` set.

    Empty by default, which adopts every remote pull request SASE did not
    create rather than only self-authored ones.
    """
    return _casefolded_string_list("pr_authors")


def _casefolded_string_list(key: str) -> frozenset[str]:
    try:
        from sase.config import load_merged_config

        data = load_merged_config()
        if not isinstance(data, dict):
            return frozenset()
        section = data.get("external_mirror", {}) or {}
        values = section.get(key, []) if isinstance(section, dict) else []
    except Exception:
        return frozenset()
    if not isinstance(values, list):
        return frozenset()
    return frozenset(
        value.casefold() for value in values if isinstance(value, str) and value
    )


__all__ = ["excluded_issue_labels", "mirrored_pr_authors"]
