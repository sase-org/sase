"""Golden tests pinning ``classify_commit_*`` against the Rust facade contract.

See :mod:`tests.test_core_vcs_log_parse` for the module-level contract this
family of tests exists to pin.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME, require_rust_binding
from sase.core.vcs_log_facade import (
    _classify_commit_origin_python,
    _classify_commit_presence_python,
    _classify_commit_types_python,
    classify_commit_presence,
    classify_commit_types,
)
from sase.core.vcs_log_wire import VcsCommitWire

from ._vcs_log_facade_helpers import commit as _commit
from ._vcs_log_facade_helpers import install_fake_module

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust vcs_log facade tests.",
)


# ---------------------------------------------------------------------------
# Rust ↔ Python golden parity
# ---------------------------------------------------------------------------


def test_classify_matches_python_golden() -> None:
    commits = [_commit("synced", 300), _commit("ahead", 200), _commit("behind", 100)]
    assert classify_commit_presence(
        commits, {"ahead"}, {"behind"}
    ) == _classify_commit_presence_python(commits, {"ahead"}, {"behind"})


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("fix: handwritten", ""),
        ("fix: tracked", "Details\n\nSASE_TYPE=stitch\nSASE_BEAD=sase-1"),
        ("fix: automatic", "Details\n\nSASE_TYPE=sase init"),
        ("fix: legacy", "Details\n\nSASE_AGENT=sase-1"),
        ("fix: handwritten", "SASE_TYPE=not terminal\n\nMore"),
    ],
)
def test_classify_origin_matches_python_golden(subject: str, body: str) -> None:
    message = f"{subject}\n\n{body}" if body else subject
    binding = require_rust_binding("classify_commit_origin")
    assert binding(message) == _classify_commit_origin_python(subject, body)


@pytest.mark.parametrize(
    ("commit", "expected"),
    [
        (_commit("manual", 1, "fix: handwritten"), ("manual",)),
        (
            VcsCommitWire(
                full_id="auto",
                short_id="auto",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=2,
                subject="fix: generated",
                body="Details\n\nSASE_TYPE=SDD",
                origin="auto",
            ),
            ("automatic", "sdd"),
        ),
        (
            VcsCommitWire(
                full_id="auto-alias",
                short_id="auto",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=2,
                subject="fix: generated",
                body="Details\n\nSASE_TYPE=auto",
                origin="auto",
            ),
            ("automatic",),
        ),
        (
            VcsCommitWire(
                full_id="tracked",
                short_id="tracked",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=3,
                subject="fix: tracked",
                body="Details\n\nSASE_TYPE=stitch",
                origin="stitch",
            ),
            ("stitch",),
        ),
        (
            VcsCommitWire(
                full_id="merge",
                short_id="merge",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=4,
                parent_ids=("p1", "p2"),
                subject="Merge tracked work",
                body="Details\n\nSASE_TYPE=bead_work\nSASE_PATCH=feat-x",
                origin="auto",
            ),
            ("automatic", "bead_work", "merge", "patch"),
        ),
        (
            VcsCommitWire(
                full_id="legacy",
                short_id="legacy",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=5,
                subject="fix: legacy",
                body="Details\n\nTYPE=Future Kind\nPATCH=feat-x",
                origin="auto",
            ),
            ("automatic", "future kind", "patch"),
        ),
        (
            VcsCommitWire(
                full_id="body",
                short_id="body",
                author_name="bryan",
                author_email="bryan@example.com",
                timestamp=6,
                parent_ids=("p1", "p2"),
                subject="fix: handwritten",
                body="SASE_TYPE=not terminal\n\nMore",
            ),
            ("manual", "merge"),
        ),
    ],
)
def test_classify_commit_types_matches_python_golden(
    commit: VcsCommitWire,
    expected: tuple[str, ...],
) -> None:
    assert _classify_commit_types_python(commit) == expected
    assert classify_commit_types(commit) == expected


# ---------------------------------------------------------------------------
# Direct-Rust call wiring
# ---------------------------------------------------------------------------


def test_classify_routes_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_classify(
        commits: list[dict[str, object]],
        ahead_ids: list[str],
        behind_ids: list[str],
    ) -> list[dict[str, object]]:
        captured["commits"] = commits
        captured["ahead_ids"] = ahead_ids
        captured["behind_ids"] = behind_ids
        out = dict(commits[0])
        out["presence"] = "local_only"
        return [out]

    install_fake_module(monkeypatch, classify_commit_presence=fake_classify)
    result = classify_commit_presence([_commit("a", 5)], {"a"}, set())

    assert captured["ahead_ids"] == ["a"]
    assert captured["behind_ids"] == []
    assert captured["commits"][0]["full_id"] == "a"
    assert result[0].presence == "local_only"


def test_classify_commit_types_routes_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_classify(commit: dict[str, object]) -> list[str]:
        captured["commit"] = commit
        return ["manual", "custom"]

    install_fake_module(monkeypatch, classify_commit_types=fake_classify)
    commit = _commit("a", 5, parent_ids=("p1", "p2"))

    assert classify_commit_types(commit) == ("manual", "custom")
    assert captured["commit"]["full_id"] == "a"
    assert captured["commit"]["parent_ids"] == ("p1", "p2")
