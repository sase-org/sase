"""Golden tests pinning ``parse_git_log`` against the Rust facade contract.

:mod:`sase.core.vcs_log_facade` must produce the exact records exercised
here, and the Rust implementation in ``sase-core`` must match
byte-for-byte — including the record/unit separator handling, the
multi-line body preservation, and the malformed-record dropping. See
:mod:`tests.test_core_vcs_log_aggregate`, :mod:`tests.test_core_vcs_log_classify`,
:mod:`tests.test_core_vcs_log_wire`, and :mod:`tests.test_core_vcs_log_merge_summary`
for the rest of the facade contract.
"""

from __future__ import annotations

import importlib.util

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.vcs_log_facade import (
    VCS_LOG_RECORD_SEP,
    VCS_LOG_UNIT_SEP,
    _parse_git_log_python,
    parse_git_log,
)
from sase.core.vcs_log_wire import VcsCommitWire

from ._vcs_log_facade_helpers import force_no_rust_extension, install_fake_module

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
    assert parsed[0].origin == "stitch"


def test_parse_computes_auto_origin_from_footer() -> None:
    stream = _record(
        "h1",
        "s1",
        "bryan",
        "b@x",
        "300",
        "",
        "fix: automatic",
        "Details\n\nSASE_TYPE=sase init",
    )
    parsed = parse_git_log(stream)
    assert parsed[0].origin == "auto"


def test_parse_manual_commit_has_manual_origin() -> None:
    stream = _record(
        "h1", "s1", "bryan", "b@x", "300", "", "fix: handwritten", "no footer here"
    )
    parsed = parse_git_log(stream)
    assert parsed[0].origin == "manual"


# ---------------------------------------------------------------------------
# Direct-Rust call wiring
# ---------------------------------------------------------------------------


def test_parse_missing_wheel_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force_no_rust_extension(monkeypatch)
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

    install_fake_module(monkeypatch, parse_git_log=fake_parse)
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
