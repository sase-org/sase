"""Golden tests pinning the ``VcsCommitWire``/``AggregatedCommitWire`` contract.

See :mod:`tests.test_core_vcs_log_parse` for the module-level contract this
family of tests exists to pin.
"""

from __future__ import annotations

import importlib.util

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.vcs_log_facade import (
    VCS_LOG_GIT_FORMAT,
    VCS_LOG_RECORD_SEP,
    VCS_LOG_UNIT_SEP,
)
from sase.core.vcs_log_wire import (
    VCS_LOG_WIRE_SCHEMA_VERSION,
    AggregatedCommitWire,
    VcsCommitWire,
    aggregated_commit_from_dict,
    vcs_commit_from_dict,
)

from ._vcs_log_facade_helpers import commit as _commit

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for direct-Rust vcs_log facade tests.",
)

US = VCS_LOG_UNIT_SEP
RS = VCS_LOG_RECORD_SEP


def test_vcs_log_wire_schema_version_is_four() -> None:
    assert VCS_LOG_WIRE_SCHEMA_VERSION == 4


def test_vcs_commit_round_trips_through_dict() -> None:
    from dataclasses import asdict, replace

    commit = replace(
        _commit("deadbeef", 42, "subject", parent_ids=("parent0",)),
        presence="local_only",
        origin="stitch",
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
        "origin": "auto",
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
            origin="auto",
        ),
    )


def test_git_format_uses_pinned_separators() -> None:
    # The format string must pin exactly eight fields terminated by the
    # record separator, so the parser and the git command stay in sync.
    assert VCS_LOG_GIT_FORMAT == (
        f"%H{US}%h{US}%an{US}%ae{US}%at{US}%P{US}%s{US}%b{RS}"
    )
