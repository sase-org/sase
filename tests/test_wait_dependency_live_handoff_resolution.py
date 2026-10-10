"""Live in-process handoffs stay unresolved until the runner writes done.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.axe.run_agent_wait_deps import resolve_initial_wait_release
from sase.core.process_identity import process_identity_token
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)
from tests._gate_wait_dependency_helpers import _write_gate_done

_SESSION = "livehop"
_PLAN_TS = "20261010142546"
_GATE_TS = "20261010143145"
_CODE_TS = "20261010143215"


def _live_identity() -> dict[str, object]:
    pid = os.getpid()
    token = process_identity_token(pid)
    assert token, "live-runner fixtures need a verifiable process identity token"
    return {"pid": pid, "process_identity": token}


def _dead_identity() -> dict[str, object]:
    pid = os.getpid()
    token = process_identity_token(pid)
    boot_id = token.partition(":")[0] if token else "dead-boot"
    return {"pid": pid, "process_identity": f"{boot_id}:0"}


def _patch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def _session_index(tmp_path: Path) -> WaitDependencyIndex:
    return build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )


def _pid_and_extra(
    identity: dict[str, object] | None,
) -> tuple[int | None, dict[str, object] | None]:
    if identity is None:
        return None, None
    pid = identity["pid"]
    assert isinstance(pid, int)
    return pid, {"process_identity": identity["process_identity"]}


def _make_plan_root(
    tmp_path: Path,
    *,
    identity: dict[str, object] | None,
) -> Path:
    pid, extra = _pid_and_extra(identity)
    root_dir = make_agent(
        tmp_path,
        "proj",
        _PLAN_TS,
        f"{_SESSION}--plan",
        workflow_name=_SESSION,
        agent_session=_SESSION,
        role_suffix="--plan",
        pid=pid,
        extra_meta=extra,
    )
    write_workflow_state(root_dir)
    return root_dir


def _make_answered_gate(tmp_path: Path, root_dir: Path) -> Path:
    gate_dir = make_agent(
        tmp_path,
        "proj",
        _GATE_TS,
        f"{_SESSION}--gate",
        workflow_name=_SESSION,
        agent_session=_SESSION,
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
            "gate_followup_outcome": "suppressed",
        },
    )
    _write_gate_done(gate_dir, gate_state="answered", followup_outcome="suppressed")
    return gate_dir


def _make_code_member(
    tmp_path: Path,
    root_dir: Path,
    *,
    identity: dict[str, object] | None = None,
    workflow_completed: bool = False,
    done: bool = False,
) -> Path:
    pid, extra = _pid_and_extra(identity)
    code_dir = make_agent(
        tmp_path,
        "proj",
        _CODE_TS,
        f"{_SESSION}--code",
        workflow_name=_SESSION,
        agent_session=_SESSION,
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        pid=pid,
        extra_meta=extra,
        done=done,
        outcome="completed" if done else None,
    )
    if workflow_completed:
        write_workflow_state(code_dir)
    return code_dir


def _assert_session_unreleased(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    waiter_dir: Path,
) -> None:
    _patch_home(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)
    assert not (waiter_dir / "ready.json").exists()
    index = _session_index(tmp_path)
    assert not index.is_resolved(_SESSION)
    assert not resolve_initial_wait_release(
        [_SESSION],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable


def _assert_session_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    waiter_dir: Path,
) -> None:
    _patch_home(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)
    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": [_SESSION], "released_by": "wait_checks"}
    index = _session_index(tmp_path)
    assert index.is_resolved(_SESSION)
    assert resolve_initial_wait_release(
        [_SESSION],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable


def test_w2_live_runner_does_not_release_session_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, _SESSION)
    root_dir = _make_plan_root(tmp_path, identity=_live_identity())
    _make_answered_gate(tmp_path, root_dir)

    _assert_session_unreleased(tmp_path, monkeypatch, waiter_dir)


def test_w2_dead_runner_releases_session_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, _SESSION)
    root_dir = _make_plan_root(tmp_path, identity=_dead_identity())
    _make_answered_gate(tmp_path, root_dir)

    _assert_session_released(tmp_path, monkeypatch, waiter_dir)


def test_adding_code_member_without_done_stays_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, _SESSION)
    root_dir = _make_plan_root(tmp_path, identity=_dead_identity())
    _make_answered_gate(tmp_path, root_dir)
    _make_code_member(tmp_path, root_dir)

    _assert_session_unreleased(tmp_path, monkeypatch, waiter_dir)

    code_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run" / _CODE_TS
    (code_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "ready.json").unlink(missing_ok=True)
    _assert_session_released(tmp_path, monkeypatch, waiter_dir)


def test_shape_c_live_coder_without_done_stays_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, _SESSION)
    root_dir = make_agent(
        tmp_path,
        "proj",
        _PLAN_TS,
        f"{_SESSION}--plan",
        workflow_name=_SESSION,
        agent_session=_SESSION,
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    _make_answered_gate(tmp_path, root_dir)
    code_dir = _make_code_member(
        tmp_path,
        root_dir,
        identity=_live_identity(),
        workflow_completed=True,
    )

    _assert_session_unreleased(tmp_path, monkeypatch, waiter_dir)

    (code_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "ready.json").unlink(missing_ok=True)
    _assert_session_released(tmp_path, monkeypatch, waiter_dir)


def test_legacy_markerless_handoff_without_process_identity_still_resolves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, _SESSION)
    root_dir = _make_plan_root(tmp_path, identity=None)
    _make_answered_gate(tmp_path, root_dir)

    _assert_session_released(tmp_path, monkeypatch, waiter_dir)
