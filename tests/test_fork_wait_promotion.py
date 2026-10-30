"""Promotion-aware bare-name fork waits (phase: promotion).

A bare-name ``#fork`` bound while its parent is still a plain agent must keep
waiting when that parent is promoted into a session after the bind. Covers the
16h replay, legacy ``kind: "agent"`` healing, exact-member single-turn waits,
never-promoted session-of-one release, the successor-ordering rule,
continuations, and member-dir collection for release confirmation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.agent.fork_waits import fork_wait_dependency
from sase.axe.run_agent_wait_deps import resolve_initial_wait_release
from sase.core.process_identity import process_identity_token
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    confirm_dependency_resolution,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._monitor_wait_dependency_helpers import (
    monitor_handoff_agent_session as _make_monitor_handoff_session,
)


def _running_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    **kwargs: object,
) -> Path:
    """Create a fixture :func:`find_named_agent` accepts as running.

    Name lookup skips non-done agents whose process is not alive, so the
    fixture carries this process's pid plus its matching identity token.
    """
    extra = dict(kwargs.pop("extra_meta", {}) or {})
    extra["process_identity"] = process_identity_token(os.getpid())
    return make_agent(
        base,
        project,
        suffix,
        name,
        pid=os.getpid(),
        extra_meta=extra,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _promote_to_session_root(
    artifact_dir: Path,
    base_name: str,
    *,
    role_suffix: str = "--plan",
) -> None:
    """Rewrite *artifact_dir*'s meta as the root of session *base_name*.

    Promotion renames in place: the artifact dir (timestamp key) is unchanged,
    only the name and session fields move.
    """
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["name"] = f"{base_name}{role_suffix}"
    meta["workflow_name"] = base_name
    meta["agent_session"] = base_name
    meta["role_suffix"] = role_suffix
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_done(artifact_dir: Path, outcome: str) -> None:
    (artifact_dir / "done.json").write_text(
        json.dumps({"outcome": outcome}), encoding="utf-8"
    )


def _write_gate_done(
    artifact_dir: Path,
    *,
    followup_agent: str | None = None,
) -> None:
    done: dict[str, object] = {"outcome": "gated", "gate_state": "answered"}
    if followup_agent is not None:
        done["gate_followup_outcome"] = "launched"
        done["gate_followup_agent"] = followup_agent
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _identity(name: str, artifact_dir: Path) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _legacy_agent_source(name: str, artifact_dir: Path) -> dict[str, str]:
    return {"kind": "agent", **_identity(name, artifact_dir)}


def _session_seed(name: str, artifact_dir: Path) -> dict[str, str]:
    return {"kind": "session", **_identity(name, artifact_dir)}


def _release(
    waiter_dir: Path,
    fork_sources: list[dict[str, str]],
) -> bool:
    return resolve_initial_wait_release(
        [],
        [],
        wait_fork_sources=fork_sources,
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable


def _patch_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def test_bare_name_binds_session_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    plain_dir = _running_agent(tmp_path, "proj", "20260506010101", "solo")

    assert fork_wait_dependency("solo") == _session_seed("solo", plain_dir)


def test_exact_member_keeps_agent_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )

    assert fork_wait_dependency("lane--plan") == _legacy_agent_source(
        "lane--plan", root_dir
    )


def test_16h_replay_waits_through_gate_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fork bound before promotion waits for review and coding to finish."""
    _patch_home(monkeypatch, tmp_path)
    plain_dir = _running_agent(tmp_path, "proj", "20260506010101", "16h")
    waiter_dir = make_waiting_agent(tmp_path, "16h")

    bound = fork_wait_dependency("16h")
    assert bound == _session_seed("16h", plain_dir)

    # The parent is promoted after the bind: same artifact dir, renamed to the
    # plan member of a new session with a pending gate.
    _promote_to_session_root(plain_dir, "16h")
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "16h--gate",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--gate",
        parent_timestamp=plain_dir.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )
    _write_done(plain_dir, "completed")

    assert not _release(waiter_dir, [bound])

    # Gate approval plus the code turn finishing releases the fork.
    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "16h--code",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--code",
        parent_timestamp=plain_dir.name,
        done=True,
        outcome="completed",
    )
    _write_gate_done(gate_dir, followup_agent="16h--code")

    assert _release(waiter_dir, [bound])
    assert code_dir.exists()


def test_legacy_bare_name_heals_over_promoted_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued legacy ``kind: agent`` record follows its parent's promotion."""
    _patch_home(monkeypatch, tmp_path)
    waiter_dir = make_waiting_agent(tmp_path, "16h")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "16h--plan",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "16h--gate",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )
    legacy = _legacy_agent_source("16h", root_dir)

    assert not _release(waiter_dir, [legacy])

    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "16h--code",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    _write_gate_done(gate_dir, followup_agent="16h--code")

    assert _release(waiter_dir, [legacy])
    assert code_dir.exists()


def test_legacy_exact_member_stays_single_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy record naming ``16h--plan`` releases with the plan turn."""
    _patch_home(monkeypatch, tmp_path)
    waiter_dir = make_waiting_agent(tmp_path, "16h--plan")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "16h--plan",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "16h--gate",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )

    assert _release(waiter_dir, [_legacy_agent_source("16h--plan", root_dir)])


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_never_promoted_session_of_one_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """A session seed over a never-promoted agent follows that one artifact."""
    _patch_home(monkeypatch, tmp_path)
    waiter_dir = make_waiting_agent(tmp_path, "solo")
    plain_dir = make_agent(
        tmp_path, "proj", "20260506010101", "solo", done=True, outcome=outcome
    )
    # A later namesake must not redirect the pinned record.
    make_agent(tmp_path, "proj", "20260506020202", "solo")

    assert _release(waiter_dir, [_session_seed("solo", plain_dir)])


def test_successor_before_predecessor_done_keeps_waiter_pending(
    tmp_path: Path,
) -> None:
    """A successor registered before its predecessor's ``done.json`` blocks."""
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
    )

    def _index(*dirs: Path) -> WaitDependencyIndex:
        index = WaitDependencyIndex.empty()
        index.add_many(
            (
                artifact_dir,
                json.loads(
                    (artifact_dir / "agent_meta.json").read_text(encoding="utf-8")
                ),
                "proj",
            )
            for artifact_dir in dirs
        )
        return index

    stale = _index(root_dir)
    fresh = _index(root_dir, code_dir)
    assert dependency_resolution_status(
        stale, [], wait_fork_sources=[_session_seed("lane", root_dir)]
    ).resolved

    confirmation = confirm_dependency_resolution(
        stale,
        lambda: fresh,
        [],
        wait_fork_sources=[_session_seed("lane", root_dir)],
    )

    assert not confirmation.confirmed


def test_gate_followup_does_not_wait_on_itself(tmp_path: Path) -> None:
    """A same-session follow-up waiting on the bare name releases with itself."""
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "lane--gate",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )
    followup_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=gate_dir.name,
    )
    _write_gate_done(gate_dir, followup_agent="lane--code")

    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )

    assert dependency_resolution_status(
        index,
        ["lane"],
        self_artifact_dir=str(followup_dir),
    ).resolved


def test_monitor_followup_releases_on_exact_starter(tmp_path: Path) -> None:
    """A monitor follow-up waiting on its exact starter releases with it."""
    _root_dir, _monitor_dir, successor_dir = _make_monitor_handoff_session(
        tmp_path,
        successor_outcome=False,
    )
    assert successor_dir is not None

    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )

    assert dependency_resolution_status(
        index,
        ["monitor-lane--plan"],
        self_artifact_dir=str(successor_dir),
    ).resolved


def test_member_dirs_include_session_for_healed_record(tmp_path: Path) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "lane--gate",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )

    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    member_dirs = index.dependency_member_dirs(
        [],
        wait_fork_sources=[_legacy_agent_source("lane", root_dir)],
    )

    assert str(root_dir) in member_dirs
    assert str(gate_dir) in member_dirs
