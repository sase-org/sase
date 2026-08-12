"""Tests for the external-mirror filter config doctor check."""

from __future__ import annotations

from typing import Any

import pytest

from sase.doctor.checks_config_external_mirror import check_config_external_mirror


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: config)


def test_ok_when_no_legacy_keys_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch,
        {
            "external_mirror": {
                "issues": {"filters": {"label_globs": []}},
                "pull_requests": {"filters": {"author_globs": []}},
            }
        },
    )

    check = check_config_external_mirror()

    assert check.status == "OK"
    assert check.data["problems"] == ()
    assert check.next_steps == ()


def test_ok_when_external_mirror_section_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, {})

    check = check_config_external_mirror()

    assert check.status == "OK"


def test_warns_naming_the_replacement_for_a_lone_legacy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {"external_mirror": {"exclude_labels": ["question"]}},
    )

    check = check_config_external_mirror()

    assert check.status == "WARN"
    assert len(check.data["problems"]) == 1
    [message] = [row["message"] for row in check.data["problems"]]
    assert "external_mirror.exclude_labels is deprecated" in message
    assert "external_mirror.issues.filters.label_globs" in message
    assert check.next_steps


def test_warns_louder_when_legacy_and_modern_are_both_set(
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

    check = check_config_external_mirror()

    assert check.status == "WARN"
    [message] = [row["message"] for row in check.data["problems"]]
    assert "external_mirror.pr_authors is set alongside" in message
    assert "ignored" in message
    assert "external_mirror.pull_requests.filters.author_globs" in message


def test_both_legacy_keys_can_warn_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "external_mirror": {
                "exclude_labels": ["question"],
                "pr_authors": ["bot"],
            }
        },
    )

    check = check_config_external_mirror()

    assert check.status == "WARN"
    assert len(check.data["problems"]) == 2
