"""Proc-ref resolution and filter_procs/read_procs filtering coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.procs import (
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    TUI_PROC_KIND,
    ProcRefError,
    append_proc,
    filter_procs,
    read_procs,
    resolve_proc_ref,
)

from tests._procs_facade_helpers import _proc


def test_resolve_proc_ref_handles_unique_short_unknown_and_ambiguous() -> None:
    first = _proc("abc012345678", label="First")
    second = _proc("abc112345678", label="Second")
    procs = [first, second]

    assert resolve_proc_ref("ABC0", procs) is first
    with pytest.raises(ProcRefError, match="at least 3"):
        resolve_proc_ref("ab", procs)
    with pytest.raises(ProcRefError, match="no proc"):
        resolve_proc_ref("zzz", procs)
    with pytest.raises(ProcRefError, match=r"abc012.*First.*abc112.*Second"):
        resolve_proc_ref("abc", procs)


def test_resolve_proc_ref_prefers_exact_named_proc_shell() -> None:
    named = _proc("zzz012345678", label="Named", shell_name="agent--build")
    prefixed = _proc("abc012345678", label="Prefix")
    procs = [named, prefixed]

    assert resolve_proc_ref("agent--build", procs) is named
    assert resolve_proc_ref("abc012345678", procs) is prefixed


def test_filter_procs_applies_every_supported_filter() -> None:
    wanted = _proc("wanted-proc1", label="Compile Docs", command=["mkdocs", "build"])
    other = _proc(
        "other-proc22",
        status="error",
        label="Tests",
        project="other",
        session_id=None,
        tags=["ci"],
        command=["pytest"],
        cl_name="test_suite",
    )
    procs = [wanted, other]

    assert filter_procs(procs, status="pending") == [wanted]
    assert filter_procs(procs, status={"error"}) == [other]
    assert filter_procs(procs, session_id="session-a") == [wanted]
    assert filter_procs(procs, session_id=None) == [other]
    assert filter_procs(procs, project="other") == [other]
    assert filter_procs(procs, tag="docs") == [wanted]
    assert filter_procs(procs, query="MKDOCS BUILD") == [wanted]
    assert filter_procs(procs, query="test_suite") == [other]


def test_filter_procs_matches_named_proc_shell_and_query() -> None:
    named = _proc("named-proc01", shell_name="agent--build")
    historical = _proc(
        "hist-proc001",
        label="Legacy",
        project="other",
        session_id=None,
        tags=["ci"],
        command=["true"],
        cl_name=None,
        shell_name="old/name",
    )

    assert filter_procs([named, historical], shell_name="agent--build") == [named]
    assert filter_procs([named, historical], shell_name={"old/name"}) == [historical]
    assert filter_procs([named, historical], query="agent--build") == [named]
    assert filter_procs([named, historical], query="old/name") == [historical]


def test_kind_filter_selects_one_or_many_proc_kinds(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    command = _proc("command-proc", created_at="2026-07-25T12:00:00Z")
    detached = _proc(
        "detach-proc1",
        kind=DETACHED_PROC_KIND,
        session_id=None,
        created_at="2026-07-25T12:01:00Z",
    )
    mirrored = _proc(
        "mirror-proc1", kind=TUI_PROC_KIND, created_at="2026-07-25T12:02:00Z"
    )
    for proc in (command, detached, mirrored):
        append_proc(proc, path=store, history_limit=10)

    assert read_procs(path=store, kind=DETACHED_PROC_KIND) == [detached]
    assert read_procs(path=store, kind={COMMAND_PROC_KIND, DETACHED_PROC_KIND}) == [
        detached,
        command,
    ]
    assert len(read_procs(path=store)) == 3
    assert filter_procs([command, detached, mirrored], kind=TUI_PROC_KIND) == [mirrored]
