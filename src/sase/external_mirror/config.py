"""Configuration accessors for the external tracker mirror."""

from __future__ import annotations

from .filters import IssueFilters, PullRequestFilters


def issue_filters() -> IssueFilters:
    """Return the effective ``external_mirror.issues.filters``.

    The deprecated ``external_mirror.exclude_labels`` list folds into
    ``label_globs`` as negated globs, but only when ``label_globs`` itself is
    empty: a criterion that is empty after merge is indistinguishable from
    unset, and the legacy key defaults to ``[]`` too, so "modern wins" has to
    mean "modern wins when it says something".
    """
    section = _issues_filters_section()
    label_globs = _string_tuple(section, "label_globs")
    if not label_globs:
        label_globs = tuple(f"!{label}" for label in sorted(_legacy_excluded_labels()))
    return IssueFilters(
        author_globs=_string_tuple(section, "author_globs"),
        label_globs=label_globs,
        title_globs=_string_tuple(section, "title_globs"),
        states=_string_tuple(section, "states"),
    )


def pull_request_filters() -> PullRequestFilters:
    """Return the effective ``external_mirror.pull_requests.filters``.

    The deprecated ``external_mirror.pr_authors`` list folds into
    ``author_globs`` as plain (non-negated) globs, but only when
    ``author_globs`` itself is empty; see :func:`issue_filters` for why.
    """
    section = _pull_requests_filters_section()
    author_globs = _string_tuple(section, "author_globs")
    if not author_globs:
        author_globs = tuple(sorted(_legacy_pr_authors()))
    return PullRequestFilters(
        author_globs=author_globs,
        base_ref_globs=_string_tuple(section, "base_ref_globs"),
        head_ref_globs=_string_tuple(section, "head_ref_globs"),
        title_globs=_string_tuple(section, "title_globs"),
        states=_string_tuple(section, "states"),
    )


def _legacy_excluded_labels() -> frozenset[str]:
    """Return the case-folded ``external_mirror.exclude_labels`` set.

    Deprecated; kept only to feed the ``label_globs`` fold in
    :func:`issue_filters`.
    """
    return _casefolded_string_list("exclude_labels")


def _legacy_pr_authors() -> frozenset[str]:
    """Return the case-folded ``external_mirror.pr_authors`` set.

    Deprecated; kept only to feed the ``author_globs`` fold in
    :func:`pull_request_filters`.
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


def _issues_filters_section() -> dict:
    return _dict_at(("external_mirror", "issues", "filters"))


def _pull_requests_filters_section() -> dict:
    return _dict_at(("external_mirror", "pull_requests", "filters"))


def _dict_at(path: tuple[str, ...]) -> dict:
    try:
        from sase.config import load_merged_config

        node: object = load_merged_config()
        for key in path:
            if not isinstance(node, dict):
                return {}
            node = node.get(key, {})
        return node if isinstance(node, dict) else {}
    except Exception:
        return {}


def _string_tuple(section: dict, key: str) -> tuple[str, ...]:
    values = section.get(key, []) if isinstance(section, dict) else []
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


__all__ = ["issue_filters", "pull_request_filters"]
