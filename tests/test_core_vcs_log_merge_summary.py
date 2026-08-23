"""Golden tests pinning ``merge_summary`` against the Rust facade contract.

See :mod:`tests.test_core_vcs_log_parse` for the module-level contract this
family of tests exists to pin.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.vcs_log_facade import _MergeSummary, merge_summary

from ._vcs_log_facade_helpers import force_no_rust_extension, install_fake_module

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust vcs_log facade tests.",
)


def test_merge_summary_recognizes_pull_request() -> None:
    summary = merge_summary(
        "Merge pull request #123 from org/feature-branch",
        "\nFeature title\n\nDetails",
    )
    assert summary == _MergeSummary(
        kind="pull_request",
        reference="123",
        source="org/feature-branch",
        target=None,
        headline="Feature title",
    )


def test_merge_summary_recognizes_branch_into_target() -> None:
    summary = merge_summary("Merge branch 'feature' into master", "")
    assert summary == _MergeSummary(
        kind="branch",
        reference="feature",
        source="feature",
        target="master",
        headline=None,
    )


def test_merge_summary_recognizes_remote_tracking_branch() -> None:
    summary = merge_summary("Merge remote-tracking branch 'origin/feature'", "")
    assert summary == _MergeSummary(
        kind="remote_branch",
        reference="origin/feature",
        source="origin/feature",
        target=None,
        headline=None,
    )


def test_merge_summary_returns_none_for_unrecognized_subject() -> None:
    assert merge_summary("Merge unknown shape", "") is None


def test_merge_summary_missing_wheel_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force_no_rust_extension(monkeypatch)
    with pytest.raises(ImportError):
        merge_summary("Merge branch 'feature'", "")


def test_merge_summary_routes_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_parse_merge_summary(subject: str, body: str) -> dict[str, object] | None:
        captured["subject"] = subject
        captured["body"] = body
        return {
            "kind": "branch",
            "reference": "feature",
            "source": "feature",
            "target": None,
            "headline": None,
        }

    install_fake_module(monkeypatch, parse_merge_summary=fake_parse_merge_summary)
    result = merge_summary("Merge branch 'feature'", "")

    assert captured == {"subject": "Merge branch 'feature'", "body": ""}
    assert result == _MergeSummary(
        kind="branch",
        reference="feature",
        source="feature",
        target=None,
        headline=None,
    )


def test_merge_summary_routes_none_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_module(monkeypatch, parse_merge_summary=lambda _s, _b: None)
    assert merge_summary("Merge unknown shape", "") is None
