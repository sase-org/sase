"""Golden tests pinning the VCS-log parser/aggregator facade contract.

:mod:`sase.core.vcs_log_facade` must produce the exact records exercised
here, and the Rust implementation in ``sase-core`` must match
byte-for-byte — including the record/unit separator handling, the
multi-line body preservation, the malformed-record dropping, and the
``timestamp`` desc + ``(repo, full_id)`` tie-break ordering.

Every helper calls ``sase_core_rs`` directly. The tests assert the
content contract (via the real Rust binding when installed) and the
direct-call wiring (a missing wheel raises :class:`ImportError`; a stale
wheel without the binding raises :class:`AttributeError`; a registered
fake binding is called). The Python ``*_python`` helpers in
:mod:`sase.core.vcs_log_facade` are retained as host-logic golden
references for the parity tests at the bottom.
"""

from __future__ import annotations

import importlib
import importlib.util
import types
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME, require_rust_binding
from sase.core.vcs_log_facade import (
    VCS_LOG_GIT_FORMAT,
    VCS_LOG_RECORD_SEP,
    VCS_LOG_UNIT_SEP,
    _MergeSummary,
    _aggregate_commit_log_python,
    _classify_commit_origin_python,
    _classify_commit_presence_python,
    _parse_git_log_python,
    aggregate_commit_log,
    classify_commit_presence,
    merge_summary,
    parse_git_log,
)
from sase.core.vcs_log_wire import (
    VCS_LOG_WIRE_SCHEMA_VERSION,
    AggregatedCommitWire,
    VcsCommitWire,
    aggregated_commit_from_dict,
    vcs_commit_from_dict,
)

from ._rust_extension_module_helpers import (
    evict_rust_extension,
    install_fake_rust_extension,
)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust vcs_log facade tests.",
)

US = VCS_LOG_UNIT_SEP
RS = VCS_LOG_RECORD_SEP


def _record(
    full: str,
    short: str,
    name: str,
    email: str,
    ts: str,
    parents: str,
    subject: str,
    body: str,
) -> str:
    return (
        f"{full}{US}{short}{US}{name}{US}{email}{US}{ts}{US}{parents}{US}"
        f"{subject}{US}{body}{RS}"
    )


def _legacy_record(
    full: str,
    short: str,
    name: str,
    email: str,
    ts: str,
    subject: str,
    body: str,
) -> str:
    """A pre-schema-3 record: no ``%P`` field."""
    return f"{full}{US}{short}{US}{name}{US}{email}{US}{ts}{US}{subject}{US}{body}{RS}"


def _commit(
    full: str, ts: int, subject: str = "s", parent_ids: tuple[str, ...] = ()
) -> VcsCommitWire:
    return VcsCommitWire(
        full_id=full,
        short_id=full[:7],
        author_name="bryan",
        author_email="bryan@example.com",
        timestamp=ts,
        parent_ids=parent_ids,
        subject=subject,
        body="",
    )


# ---------------------------------------------------------------------------
# parse_git_log
# ---------------------------------------------------------------------------


def test_parse_empty_stream_returns_empty_list() -> None:
    assert parse_git_log("") == []


def test_parse_single_commit_all_fields() -> None:
    stream = _record(
        "a1b2c3d4e5f6",
        "a1b2c3d",
        "bryan",
        "bryan@example.com",
        "1700000000",
        "parent0",
        "fix(sdd): link store",
        "",
    )
    assert parse_git_log(stream) == [
        VcsCommitWire(
            full_id="a1b2c3d4e5f6",
            short_id="a1b2c3d",
            author_name="bryan",
            author_email="bryan@example.com",
            timestamp=1700000000,
            parent_ids=("parent0",),
            subject="fix(sdd): link store",
            body="",
        )
    ]


def test_parse_root_commit_has_empty_parent_ids() -> None:
    stream = _record("r1", "r1", "bryan", "b@x", "300", "", "root", "")
    parsed = parse_git_log(stream)
    assert parsed[0].parent_ids == ()
    assert parsed[0].is_merge is False


def test_parse_octopus_merge_has_all_parent_ids() -> None:
    stream = _record("m1", "m1", "bryan", "b@x", "300", "p1 p2 p3", "Merge octopus", "")
    parsed = parse_git_log(stream)
    assert parsed[0].parent_ids == ("p1", "p2", "p3")
    assert parsed[0].is_merge is True


def test_parse_legacy_seven_field_record_has_no_parent_ids() -> None:
    stream = _legacy_record("h1", "s1", "bryan", "b@x", "300", "legacy", "body")
    parsed = parse_git_log(stream)
    assert parsed[0].parent_ids == ()
    assert parsed[0].subject == "legacy"
    assert parsed[0].body == "body"


def test_parse_strips_newline_git_inserts_between_records() -> None:
    stream = (
        _record("h1", "s1", "bryan", "b@x", "300", "", "first", "")
        + "\n"
        + _record("h2", "s2", "bryan", "b@x", "200", "", "second", "")
        + "\n"
    )
    parsed = parse_git_log(stream)
    assert [c.full_id for c in parsed] == ["h1", "h2"]


def test_parse_multiline_body_preserved() -> None:
    body = "detail line one\ndetail line two"
    stream = _record("h1", "s1", "bryan", "b@x", "300", "", "subject", body)
    parsed = parse_git_log(stream)
    assert parsed[0].body == body


def test_parse_drops_record_with_too_few_fields() -> None:
    malformed = f"h1{US}s1{US}bryan{US}b@x{US}300{US}subject{RS}"
    good = _record("h2", "s2", "bryan", "b@x", "200", "", "ok", "")
    parsed = parse_git_log(malformed + good)
    assert [c.full_id for c in parsed] == ["h2"]


def test_parse_drops_record_with_bad_timestamp() -> None:
    bad = _record("h1", "s1", "bryan", "b@x", "not-a-number", "", "x", "")
    good = _record("h2", "s2", "bryan", "b@x", "200", "", "ok", "")
    parsed = parse_git_log(bad + good)
    assert [c.full_id for c in parsed] == ["h2"]


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
# Wire helpers
# ---------------------------------------------------------------------------


def test_vcs_log_wire_schema_version_is_four() -> None:
    assert VCS_LOG_WIRE_SCHEMA_VERSION == 4


def test_vcs_commit_round_trips_through_dict() -> None:
    from dataclasses import asdict, replace

    commit = replace(
        _commit("deadbeef", 42, "subject", parent_ids=("parent0",)),
        presence="local_only",
        origin="sase",
    )
    assert vcs_commit_from_dict(asdict(commit)) == commit


def test_vcs_commit_missing_origin_defaults_manual() -> None:
    data = {
        "full_id": "deadbeef",
        "short_id": "deadbee",
        "author_name": "bryan",
        "author_email": "bryan@example.com",
        "timestamp": 42,
        "subject": "subject",
        "body": "",
    }
    assert vcs_commit_from_dict(data).origin == "manual"


def test_vcs_commit_unrecognized_origin_defaults_manual() -> None:
    data = {
        "full_id": "deadbeef",
        "short_id": "deadbee",
        "author_name": "bryan",
        "author_email": "bryan@example.com",
        "timestamp": 42,
        "subject": "subject",
        "body": "",
        "origin": "bogus",
    }
    assert vcs_commit_from_dict(data).origin == "manual"


def test_vcs_commit_missing_presence_defaults_unknown() -> None:
    data = {
        "full_id": "deadbeef",
        "short_id": "deadbee",
        "author_name": "bryan",
        "author_email": "bryan@example.com",
        "timestamp": 42,
        "subject": "subject",
        "body": "",
    }
    assert vcs_commit_from_dict(data).presence == "unknown"


def test_vcs_commit_missing_parent_ids_defaults_empty_tuple() -> None:
    data = {
        "full_id": "deadbeef",
        "short_id": "deadbee",
        "author_name": "bryan",
        "author_email": "bryan@example.com",
        "timestamp": 42,
        "subject": "subject",
        "body": "",
    }
    assert vcs_commit_from_dict(data).parent_ids == ()


def test_aggregated_commit_from_flat_dict() -> None:
    flat = {
        "repo": "sase",
        "full_id": "a1b2c3d4",
        "short_id": "a1b2c3d",
        "author_name": "bryan",
        "author_email": "bryan@example.com",
        "timestamp": 1700000000,
        "parent_ids": ["parent0", "parent1"],
        "subject": "fix: thing",
        "body": "",
        "presence": "remote_only",
        "origin": "sase",
    }
    row = aggregated_commit_from_dict(flat)
    assert row == AggregatedCommitWire(
        repo="sase",
        commit=VcsCommitWire(
            full_id="a1b2c3d4",
            short_id="a1b2c3d",
            author_name="bryan",
            author_email="bryan@example.com",
            timestamp=1700000000,
            parent_ids=("parent0", "parent1"),
            subject="fix: thing",
            body="",
            presence="remote_only",
            origin="sase",
        ),
    )


def test_git_format_uses_pinned_separators() -> None:
    # The format string must pin exactly eight fields terminated by the
    # record separator, so the parser and the git command stay in sync.
    assert VCS_LOG_GIT_FORMAT == (
        f"%H{US}%h{US}%an{US}%ae{US}%at{US}%P{US}%s{US}%b{RS}"
    )


# ---------------------------------------------------------------------------
# Rust ↔ Python golden parity
# ---------------------------------------------------------------------------


def test_parse_matches_python_golden() -> None:
    stream = (
        _record("h1", "s1", "bryan", "b@x", "300", "p0", "first", "body\nmore")
        + "\n"
        + _record("h2", "s2", "amy", "a@x", "200", "", "second", "")
        + "\n"
    )
    assert parse_git_log(stream) == _parse_git_log_python(stream)


def test_parse_matches_python_golden_legacy_seven_field_record() -> None:
    stream = _legacy_record("h1", "s1", "bryan", "b@x", "300", "legacy", "body")
    assert parse_git_log(stream) == _parse_git_log_python(stream)


def test_parse_matches_python_golden_root_commit_zero_parents() -> None:
    stream = _record("h1", "s1", "bryan", "b@x", "300", "", "root", "")
    assert parse_git_log(stream) == _parse_git_log_python(stream)


def test_parse_matches_python_golden_octopus_merge() -> None:
    stream = _record("h1", "s1", "bryan", "b@x", "300", "p1 p2 p3", "octopus", "")
    assert parse_git_log(stream) == _parse_git_log_python(stream)


def test_aggregate_matches_python_golden() -> None:
    repos = [
        ("sase", [_commit("a", 300), _commit("b", 300)]),
        ("core", [_commit("a", 300), _commit("c", 250)]),
    ]
    assert aggregate_commit_log(repos, 3) == _aggregate_commit_log_python(repos, 3)


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
        ("fix: handwritten", "SASE_TYPE=not terminal\n\nMore"),
    ],
)
def test_classify_origin_matches_python_golden(subject: str, body: str) -> None:
    message = f"{subject}\n\n{body}" if body else subject
    binding = require_rust_binding("classify_commit_origin")
    assert binding(message) == _classify_commit_origin_python(subject, body)


def test_parse_computes_origin_from_footer() -> None:
    stream = _record(
        "h1",
        "s1",
        "bryan",
        "b@x",
        "300",
        "",
        "fix: tracked",
        "Details\n\nSASE_TYPE=stitch",
    )
    parsed = parse_git_log(stream)
    assert parsed[0].origin == "sase"


def test_parse_manual_commit_has_manual_origin() -> None:
    stream = _record(
        "h1", "s1", "bryan", "b@x", "300", "", "fix: handwritten", "no footer here"
    )
    parsed = parse_git_log(stream)
    assert parsed[0].origin == "manual"


# ---------------------------------------------------------------------------
# Direct-Rust call wiring
# ---------------------------------------------------------------------------


def _force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    evict_rust_extension(monkeypatch)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail)


def _install_fake_module(
    monkeypatch: pytest.MonkeyPatch, **bindings: Any
) -> types.ModuleType:
    return install_fake_rust_extension(monkeypatch, **bindings)


def test_parse_missing_wheel_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_no_rust_extension(monkeypatch)
    with pytest.raises(ImportError):
        parse_git_log("")


def test_parse_routes_through_registered_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {}

    def fake_parse(_stdout: str) -> list[dict[str, object]]:
        calls["parse_git_log"] = calls.get("parse_git_log", 0) + 1
        return [
            {
                "full_id": "from-rust",
                "short_id": "from-r",
                "author_name": "rust",
                "author_email": "rust@x",
                "timestamp": 1,
                "subject": "s",
                "body": "",
                "presence": "synced",
            }
        ]

    _install_fake_module(monkeypatch, parse_git_log=fake_parse)
    result = parse_git_log("ignored")
    assert calls["parse_git_log"] == 1
    assert result == [
        VcsCommitWire(
            full_id="from-rust",
            short_id="from-r",
            author_name="rust",
            author_email="rust@x",
            timestamp=1,
            subject="s",
            body="",
            presence="synced",
        )
    ]


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

    _install_fake_module(monkeypatch, aggregate_commit_log=fake_aggregate)
    out = aggregate_commit_log([("sase", [_commit("a", 5)])], 10)
    assert captured["limit"] == 10
    # The commit was marshalled to its JSON dict for the boundary crossing.
    assert captured["repos"][0][0] == "sase"
    assert captured["repos"][0][1][0]["full_id"] == "a"
    assert out[0].repo == "sase"
    assert out[0].commit.full_id == "a"


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

    _install_fake_module(monkeypatch, classify_commit_presence=fake_classify)
    result = classify_commit_presence([_commit("a", 5)], {"a"}, set())

    assert captured["ahead_ids"] == ["a"]
    assert captured["behind_ids"] == []
    assert captured["commits"][0]["full_id"] == "a"
    assert result[0].presence == "local_only"


# ---------------------------------------------------------------------------
# merge_summary
# ---------------------------------------------------------------------------


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
    _force_no_rust_extension(monkeypatch)
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

    _install_fake_module(monkeypatch, parse_merge_summary=fake_parse_merge_summary)
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
    _install_fake_module(monkeypatch, parse_merge_summary=lambda _s, _b: None)
    assert merge_summary("Merge unknown shape", "") is None
