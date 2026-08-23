"""Golden tests pinning ``aggregate_commit_log`` against the Rust facade contract.

See :mod:`tests.test_core_vcs_log_parse` for the module-level contract this
family of tests exists to pin, and the timestamp desc + ``(repo, full_id)``
tie-break ordering exercised here.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.vcs_log_facade import _aggregate_commit_log_python, aggregate_commit_log

from ._vcs_log_facade_helpers import commit as _commit
from ._vcs_log_facade_helpers import install_fake_module

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust vcs_log facade tests.",
)


# ---------------------------------------------------------------------------
# aggregate_commit_log
# ---------------------------------------------------------------------------


def test_aggregate_empty_returns_empty() -> None:
    assert aggregate_commit_log([], 20) == []


def test_aggregate_interleaves_by_timestamp_desc() -> None:
    repos = [
        ("sase", [_commit("a", 300), _commit("b", 100)]),
        ("sase-core", [_commit("c", 200)]),
    ]
    out = aggregate_commit_log(repos, 20)
    assert [(r.repo, r.commit.full_id) for r in out] == [
        ("sase", "a"),
        ("sase-core", "c"),
        ("sase", "b"),
    ]


def test_aggregate_tie_break_repo_then_full_id() -> None:
    repos = [
        ("zebra", [_commit("x", 500)]),
        ("alpha", [_commit("m", 500), _commit("a", 500)]),
    ]
    out = aggregate_commit_log(repos, 20)
    assert [(r.repo, r.commit.full_id) for r in out] == [
        ("alpha", "a"),
        ("alpha", "m"),
        ("zebra", "x"),
    ]


def test_aggregate_truncates_to_limit() -> None:
    repos = [("sase", [_commit("a", 500), _commit("b", 400), _commit("c", 300)])]
    out = aggregate_commit_log(repos, 2)
    assert [r.commit.full_id for r in out] == ["a", "b"]


def test_aggregate_negative_limit_is_unlimited() -> None:
    repos = [("sase", [_commit("a", 500), _commit("b", 400), _commit("c", 300)])]
    out = aggregate_commit_log(repos, -1)
    assert [r.commit.full_id for r in out] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Rust ↔ Python golden parity
# ---------------------------------------------------------------------------


def test_aggregate_matches_python_golden() -> None:
    repos = [
        ("sase", [_commit("a", 300), _commit("b", 300)]),
        ("core", [_commit("a", 300), _commit("c", 250)]),
    ]
    assert aggregate_commit_log(repos, 3) == _aggregate_commit_log_python(repos, 3)


# ---------------------------------------------------------------------------
# Direct-Rust call wiring
# ---------------------------------------------------------------------------


def test_aggregate_routes_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_aggregate(
        repos: list[tuple[str, list[dict[str, object]]]], limit: int
    ) -> list[dict[str, object]]:
        captured["repos"] = repos
        captured["limit"] = limit
        return [
            {
                "repo": "sase",
                "full_id": "a",
                "short_id": "a",
                "author_name": "bryan",
                "author_email": "b@x",
                "timestamp": 5,
                "subject": "s",
                "body": "",
                "presence": "unknown",
            }
        ]

    install_fake_module(monkeypatch, aggregate_commit_log=fake_aggregate)
    out = aggregate_commit_log([("sase", [_commit("a", 5)])], 10)
    assert captured["limit"] == 10
    # The commit was marshalled to its JSON dict for the boundary crossing.
    assert captured["repos"][0][0] == "sase"
    assert captured["repos"][0][1][0]["full_id"] == "a"
    assert out[0].repo == "sase"
    assert out[0].commit.full_id == "a"
