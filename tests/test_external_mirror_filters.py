"""Tests for the external-mirror glob-criterion filter evaluator."""

from __future__ import annotations

from typing import Any

from sase.external_mirror.filters import IssueFilters, PullRequestFilters
from sase.vcs_provider._types import IssueWire, PullRequestWire


def _issue(**overrides: Any) -> IssueWire:
    defaults: dict[str, Any] = {"number": 1, "title": "Issue", "state": "open"}
    defaults.update(overrides)
    return IssueWire(**defaults)


def _pr(**overrides: Any) -> PullRequestWire:
    defaults: dict[str, Any] = {"number": 1, "title": "PR", "state": "open"}
    defaults.update(overrides)
    return PullRequestWire(**defaults)


def test_empty_criterion_accepts_everything() -> None:
    assert IssueFilters().matches(_issue())
    assert IssueFilters().matches(_issue(labels=("bug",), author="anyone"))
    assert PullRequestFilters().matches(_pr(author="anyone", head_ref="anything"))


def test_positive_only_glob_requires_a_match() -> None:
    filters = IssueFilters(author_globs=("alice",))
    assert filters.matches(_issue(author="alice"))
    assert not filters.matches(_issue(author="bob"))


def test_negative_only_glob_rejects_a_match_and_accepts_otherwise() -> None:
    filters = IssueFilters(author_globs=("!bob",))
    assert filters.matches(_issue(author="alice"))
    assert not filters.matches(_issue(author="bob"))


def test_mixed_positive_and_negative_globs() -> None:
    filters = IssueFilters(author_globs=("al*", "!alice-bot"))
    assert filters.matches(_issue(author="alice"))
    assert not filters.matches(_issue(author="alice-bot"))
    assert not filters.matches(_issue(author="bob"))


def test_matching_is_case_folded() -> None:
    filters = IssueFilters(author_globs=("Alice",))
    assert filters.matches(_issue(author="ALICE"))
    assert not filters.matches(_issue(author="bob"))


def test_multivalued_label_globs_one_label_does_not_clear_the_negative() -> None:
    """A per-value NEGATE pass OR-ed across labels would wrongly accept this."""
    filters = IssueFilters(label_globs=("!question",))
    assert not filters.matches(_issue(labels=("bug", "question")))
    assert filters.matches(_issue(labels=("bug",)))


def test_no_labels_positive_only_rejects_negative_only_accepts() -> None:
    positive_only = IssueFilters(label_globs=("bug",))
    negative_only = IssueFilters(label_globs=("!question",))
    assert not positive_only.matches(_issue(labels=()))
    assert negative_only.matches(_issue(labels=()))


def test_empty_string_value_clears_negative_only_but_not_positive_only() -> None:
    positive_only = PullRequestFilters(head_ref_globs=("release-please--*",))
    negative_only = PullRequestFilters(head_ref_globs=("!release-please--*",))
    empty_head_ref_pr = _pr(head_ref="")
    assert not positive_only.matches(empty_head_ref_pr)
    assert negative_only.matches(empty_head_ref_pr)


def test_states_criterion_is_case_folded_exact_membership() -> None:
    filters = IssueFilters(states=("OPEN",))
    assert filters.matches(_issue(state="open"))
    assert not filters.matches(_issue(state="closed"))
    assert IssueFilters().matches(_issue(state="closed"))


_DEFAULT_HEAD_REF_GLOBS = (
    "!release-please--*",
    "!release-please/*",
    "!release-plz-*",
    "!release-plz/*",
)


def test_default_pr_head_ref_globs_exclude_release_bots_and_accept_humans() -> None:
    filters = PullRequestFilters(head_ref_globs=_DEFAULT_HEAD_REF_GLOBS)
    assert not filters.matches(_pr(head_ref="release-please--branches--master"))
    assert not filters.matches(_pr(head_ref="release-plz-1.2.3"))
    assert filters.matches(_pr(head_ref="feature/human-branch"))


def test_fingerprint_is_stable_across_equal_models() -> None:
    a = IssueFilters(label_globs=("!question",))
    b = IssueFilters(label_globs=("!question",))
    assert a.fingerprint() == b.fingerprint()

    pr_a = PullRequestFilters(head_ref_globs=_DEFAULT_HEAD_REF_GLOBS)
    pr_b = PullRequestFilters(head_ref_globs=_DEFAULT_HEAD_REF_GLOBS)
    assert pr_a.fingerprint() == pr_b.fingerprint()


def test_fingerprint_differs_across_unequal_models() -> None:
    assert (
        IssueFilters(label_globs=("!question",)).fingerprint()
        != IssueFilters(label_globs=("!bug",)).fingerprint()
    )
    assert (
        IssueFilters().fingerprint()
        != IssueFilters(label_globs=("!question",)).fingerprint()
    )
    assert (
        PullRequestFilters(head_ref_globs=("!a",)).fingerprint()
        != PullRequestFilters(head_ref_globs=("!b",)).fingerprint()
    )
    # Different criteria populated with the same values must not collide.
    assert (
        IssueFilters(author_globs=("x",)).fingerprint()
        != IssueFilters(title_globs=("x",)).fingerprint()
    )
