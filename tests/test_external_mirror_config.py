"""Tests for external-mirror filter config accessors and the legacy fold."""

from __future__ import annotations

from typing import Any

import pytest

import sase.config as sase_config
from sase.external_mirror.config import issue_filters, pull_request_filters


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    monkeypatch.setattr(sase_config, "load_merged_config", lambda: config)


def test_modern_issue_criterion_wins_when_non_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "external_mirror": {
                "exclude_labels": ["question"],
                "issues": {"filters": {"label_globs": ["!bug"]}},
            }
        },
    )

    assert issue_filters().label_globs == ("!bug",)


def test_legacy_exclude_labels_folds_into_label_globs_when_modern_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {"external_mirror": {"exclude_labels": ["question", "wontfix"]}},
    )

    assert issue_filters().label_globs == ("!question", "!wontfix")


def test_modern_pr_author_criterion_wins_when_non_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "external_mirror": {
                "pr_authors": ["bot"],
                "pull_requests": {"filters": {"author_globs": ["alice"]}},
            }
        },
    )

    assert pull_request_filters().author_globs == ("alice",)


def test_legacy_pr_authors_folds_into_author_globs_when_modern_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {"external_mirror": {"pr_authors": ["alice", "bob"]}},
    )

    assert pull_request_filters().author_globs == ("alice", "bob")


def test_other_criteria_read_independently_of_the_legacy_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "external_mirror": {
                "exclude_labels": ["question"],
                "issues": {"filters": {"title_globs": ["chore: *"]}},
            }
        },
    )

    filters = issue_filters()
    assert filters.label_globs == ("!question",)
    assert filters.title_globs == ("chore: *",)


def test_malformed_external_mirror_section_degrades_to_empty_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, {"external_mirror": "not-a-dict"})

    assert issue_filters().label_globs == ()
    assert pull_request_filters().author_globs == ()


def test_load_merged_config_failure_degrades_to_empty_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(sase_config, "load_merged_config", _raise)

    assert issue_filters().label_globs == ()
    assert pull_request_filters().author_globs == ()
