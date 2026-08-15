"""Named proc-shell qualification, validation, and completion."""

from __future__ import annotations

import pytest

from sase.procs import (
    ProcShellNameError,
    complete_proc_refs,
    matching_procs_by_shell_name,
    named_proc_shell_concurrency_key,
    new_proc_id,
    proc_shell_name_keys,
    qualify_proc_shell_name,
    resolve_proc_ref,
)
from sase.procs.ids import PROC_ID_ALPHABET
from sase.procs.models import Proc


def _proc(
    proc_id: str,
    *,
    shell_name: str | None = None,
    status: str = "success",
    label: str = "Build",
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=label,
        kind="command",
        status=status,
        command=["true"],
        cwd="/tmp",
        origin="test",
        created_at="2026-07-25T12:00:00Z",
        log_path=f"/tmp/{proc_id}.log",
        shell_name=shell_name,
    )


def test_qualify_attaches_bare_name_to_calling_sase_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    monkeypatch.delenv("SASE_AGENT", raising=False)

    assert qualify_proc_shell_name("build") == "foo--build"


def test_qualify_uses_sase_agent_when_shell_name_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.setenv("SASE_AGENT", "solo")

    assert qualify_proc_shell_name("docs") == "solo--docs"


def test_qualify_keeps_fully_qualified_names() -> None:
    assert qualify_proc_shell_name("agent--build") == "agent--build"


def test_qualify_rejects_slash_proc_id_and_malformed_names() -> None:
    with pytest.raises(ProcShellNameError, match="slash"):
        qualify_proc_shell_name("agent/build")
    with pytest.raises(ProcShellNameError, match="slash"):
        qualify_proc_shell_name("agent\\build")
    with pytest.raises(ProcShellNameError, match="malformed qualification"):
        qualify_proc_shell_name("--build")
    with pytest.raises(ProcShellNameError, match="malformed qualification"):
        qualify_proc_shell_name("agent--")
    with pytest.raises(ProcShellNameError, match="malformed qualification"):
        qualify_proc_shell_name("agent--build--extra")
    with pytest.raises(ProcShellNameError, match="malformed qualification"):
        qualify_proc_shell_name("agent--build.role")


def test_qualify_rejects_proc_id_ambiguity() -> None:
    proc_id = new_proc_id()
    assert set(proc_id) <= set(PROC_ID_ALPHABET)
    with pytest.raises(ProcShellNameError, match="ambiguous with a proc id"):
        qualify_proc_shell_name(proc_id)
    with pytest.raises(ProcShellNameError, match="ambiguous with a proc id"):
        qualify_proc_shell_name(f"agent--{proc_id}")


def test_qualify_rejects_invalid_agent_components() -> None:
    with pytest.raises(ProcShellNameError, match="invalid agent components"):
        qualify_proc_shell_name("bad name--build")
    with pytest.raises(ProcShellNameError, match="invalid agent components"):
        qualify_proc_shell_name("agent--bad name")


def test_bare_name_requires_calling_sase_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)

    with pytest.raises(ProcShellNameError, match="calling sase agent"):
        qualify_proc_shell_name("build")


def test_concurrency_key_is_namespaced_and_not_the_shell_name() -> None:
    key = named_proc_shell_concurrency_key("sase", "agent--build")

    assert key == "shell:sase:agent--build"
    assert key != "agent--build"


def test_proc_shell_name_keys_keep_historical_spellings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "foo")

    assert proc_shell_name_keys("build") == ("build", "foo--build")
    assert proc_shell_name_keys("old/name") == ("old/name",)


def test_resolve_prefers_named_shell_then_exact_id() -> None:
    named = _proc("zzz012345678", shell_name="agent--build", status="running")
    same_prefix = _proc("abc012345678")
    procs = [named, same_prefix]

    assert resolve_proc_ref("agent--build", procs) is named
    assert resolve_proc_ref(same_prefix.proc_id, procs) is same_prefix


def test_resolve_derives_bare_name_and_prefers_active_historical_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "foo")
    settled = _proc("aaa012345678", shell_name="foo--build", status="success")
    active = _proc("bbb012345678", shell_name="foo--build", status="running")

    assert resolve_proc_ref("build", [active, settled]) is active
    assert matching_procs_by_shell_name("build", [active, settled]) == [
        active,
        settled,
    ]


def test_complete_proc_refs_includes_historical_names() -> None:
    named = _proc("abc012345678", shell_name="agent--build")
    historical = _proc("def012345678", shell_name="old/name")

    assert complete_proc_refs("agent", [named, historical]) == ["agent--build"]
    assert complete_proc_refs("old", [named, historical]) == ["old/name"]
    assert complete_proc_refs("abc", [named, historical]) == [
        "abc012345678",
        "abc012",
    ]
    assert complete_proc_refs("", [named]) == [
        "agent--build",
        "abc012345678",
        "abc012",
    ]
