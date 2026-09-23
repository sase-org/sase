"""Regression tests for ``frozen_intent_vcs_prefix`` project-tag handling."""

from __future__ import annotations

from typing import Any

import pytest

import sase.project_tags as project_tags_module
from sase.monitor.followup_continuation import frozen_intent_vcs_prefix


def _meta(
    workflow: str,
    ref: str,
    mutable_next_action: str,
) -> dict[str, Any]:
    return {
        "vcs_ref": [workflow, ref],
        "monitor_next_action": mutable_next_action,
    }


def test_prose_mention_does_not_count_as_prefixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain prose mention is not a ``+tag`` token, so no prefix is added."""
    # Unknown names pass through ``project_tag_for`` unchanged (no ``+``).
    monkeypatch.setattr(project_tags_module, "project_tag_for", lambda key: key)

    prefix = frozen_intent_vcs_prefix(
        _meta("git", "sase-core", "Check the sase-core CI run and report."),
        frozen_next_action="Report the result.",
    )

    assert prefix == ""


def test_longer_tag_substring_does_not_count_as_prefixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``+bob`` does not match inside the longer ``+bobby`` tag token."""
    monkeypatch.setattr(project_tags_module, "project_tag_for", lambda key: "+bob")

    prefix = frozen_intent_vcs_prefix(
        _meta("git", "bob", "Ask +bobby about the outage"),
        frozen_next_action="Report the result.",
    )

    assert prefix == ""


def test_resolved_tag_token_counts_as_prefixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``+<project>`` token keeps the frozen intent prefixed."""
    monkeypatch.setattr(project_tags_module, "project_tag_for", lambda key: "+bob")

    prefix = frozen_intent_vcs_prefix(
        _meta("git", "bob", "Check +bob CI and report"),
        frozen_next_action="Report the result.",
    )

    assert prefix == "#git:bob\n"


def test_canonical_ref_counts_as_prefixed() -> None:
    """The ``#<workflow>:<key>`` form still counts without consulting tags."""
    prefix = frozen_intent_vcs_prefix(
        _meta("git", "bob", "Check #git:bob CI and report"),
        frozen_next_action="Report the result.",
    )

    assert prefix == "#git:bob\n"
