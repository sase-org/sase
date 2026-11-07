"""Real-process hijack, recovery, and release coverage across linked repos."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import RecoveryDeps, RecoverySubject
from sase.agent.hijack.recover_release import ReleaseDeps, recover_release_action
from sase.agent.hijack.stop import stop_agent_for_hijack
from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
from sase.agent.hijack.ledger import load_record
from sase.llm_provider.commit_finalizer_baseline import (
    capture_dirty_baseline,
    load_dirty_baseline,
)
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.running_field._transfer import transfer_workspace_claim
from tests._running_field_helpers import create_project_file_with_running

_AGENT = "hijack-e2e--0"
_SESSION = "hijack-e2e"
_SUCCESSOR = "hijack-e2e--1"
_TIMESTAMP = "20261106120000"
_SUCCESSOR_TIMESTAMP = "20261106120100"
_WORKSPACE_NUM = 3
_TARGET = "fakey/fakey-large@xhigh"


class _PreviewRow:
    def __init__(
        self,
        action: str,
        *,
        available: bool = True,
        target: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.action = action
        self.available = available
        self.target = target
        self.reason = reason


class _Preview:
    def __init__(self, revision: int, rows: list[_PreviewRow]) -> None:
        self.revision = revision
        self.state = "held"
        self.rows = {row.action: row for row in rows}

    def action(self, name: str) -> _PreviewRow | None:
        return self.rows.get(name)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(root: Path, *, file_name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.name", "Agent Hijack E2E")
    _git(root, "config", "user.email", "hijack-e2e@example.invalid")
    (root / file_name).write_text("base\n", encoding="utf-8")
    _git(root, "add", file_name)
    _git(root, "commit", "-m", "base")
    remote = root.with_name(f"{root.name}.git")
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-u", "origin", "HEAD")


def _wait_for(path: Path, process: subprocess.Popen[str], timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(f"fakey exited before creating {path}")
        time.sleep(0.02)  # sase-test-wait: poll for the fakey-written signal file
    raise AssertionError(f"fakey did not create {path} before timeout")


def _start_waiting_fakey(
    root: Path,
    *,
    home: Path,
    artifacts: Path,
    state_dir: Path,
) -> subprocess.Popen[str]:
    import yaml

    root.mkdir(parents=True, exist_ok=True)
    started = root / "fakey.started"
    release = root / "fakey.release"
    scenario = root / "fakey.yml"
    scenario.write_text(
        yaml.safe_dump(
            {
                "steps": [
                    {"signal": str(started)},
                    {"wait_for": {"path": str(release), "timeout": 120}},
                ],
                "reply": "recovered",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("FAKEY_"):
            env.pop(key)
    env.update(
        SASE_HOME=str(home),
        SASE_ARTIFACTS_DIR=str(artifacts),
        FAKEY_STATE_DIR=str(state_dir),
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "sase.fakey.cli", "--scenario", str(scenario)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        start_new_session=True,
    )
    assert process.stdin is not None
    process.stdin.write("Continue the assigned work.\n")
    process.stdin.close()
    _wait_for(started, process)
    return process


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def _make_held_hijack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    from sase._linked_repo_markers import record_opened_linked_repo
    from sase.autonomy.record import resolve_selection

    home = tmp_path / "sase-home"
    workspace = tmp_path / "workspace"
    linked = tmp_path / "linked-core"
    artifacts = tmp_path / "predecessor-artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    _init_repo(workspace, file_name="base.txt")
    _init_repo(linked, file_name="base.txt")
    capture_dirty_baseline(str(workspace), str(artifacts))
    record_opened_linked_repo(
        "sase-core",
        str(linked),
        reason="agent opened linked repository",
        opened_at="2026-11-06T12:00:00Z",
    )
    (workspace / "primary-work.txt").write_text("primary changes\n", encoding="utf-8")
    (linked / "linked-work.txt").write_text("linked changes\n", encoding="utf-8")

    process = _start_waiting_fakey(
        tmp_path / "predecessor-process",
        home=home,
        artifacts=artifacts,
        state_dir=tmp_path / "predecessor-fakey-state",
    )
    autonomy = dict(resolve_selection("manual", source="inherited", surface="launch"))
    metadata = {
        "name": _AGENT,
        "pid": process.pid,
        "runner_capabilities": ["hijack"],
        "agent_llm_provider": "fakey",
        "agent_model": "fakey-large",
        "agent_effort": "high",
        "model_alias": "large",
        "model_alias_trail": ["large"],
        "goal_id": "goal-hijack-e2e",
        "bead_id": "sase-1qz.11",
        "autonomy": autonomy,
        "agent_session": _SESSION,
        "workspace_dir": str(workspace),
        "linked_repos": [str(linked)],
        "booted_at": time.time(),
    }
    (artifacts / "agent_meta.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WORKSPACE_NUM,
                "ace(run)-20261106_120000",
                _AGENT,
                pid=process.pid,
                artifacts_timestamp=_TIMESTAMP,
            )
        ],
    )

    monkeypatch.setattr(
        "sase.agent.running.named_agent_project_fields",
        lambda _agent: (artifacts, "proj", project_file, _TIMESTAMP, False),
    )
    row = SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        status="RUNNING",
        pid=process.pid,
        is_monitor=False,
        agent_session=_SESSION,
        workspace_num=_WORKSPACE_NUM,
        workspace_dir=str(workspace),
    )
    found = SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        is_done=False,
        outcome=None,
    )
    stopped = stop_agent_for_hijack(
        _AGENT,
        deps=StopDeps(
            find_agent=lambda name: found if name == _AGENT else None,
            list_running=lambda: [row],
        ),
    )
    assert stopped.status == "held", stopped.message
    assert stopped.hijack_id is not None
    held = load_record(stopped.hijack_id)
    assert held is not None and held["state"] == "held"
    assert {Path(item["repo"]) for item in held["snapshots"]} == {workspace, linked}
    return {
        "artifacts": artifacts,
        "autonomy": autonomy,
        "home": home,
        "linked": linked,
        "metadata": metadata,
        "process": process,
        "project_file": project_file,
        "record": held,
        "workspace": workspace,
    }


def _subject(setup: Mapping[str, Any]) -> RecoverySubject:
    record = load_record(str(setup["record"]["hijack_id"]))
    assert record is not None
    done = json.loads((Path(setup["artifacts"]) / "done.json").read_text())
    return RecoverySubject(
        record=record,
        project_name="proj",
        predecessor_meta=dict(setup["metadata"]),
        done_outcome=str(done["outcome"]),
        done_recovery=dict(done["recovery"]),
    )


def _session_plan(_session: str, _project: str | None) -> AgentSessionAttachLaunchPlan:
    return AgentSessionAttachLaunchPlan(
        parent_arg=_SESSION,
        suffix_arg="@",
        parent_name=f"{_SESSION}--0",
        parent_base=_SESSION,
        parent_timestamp=_TIMESTAMP,
        parent_artifacts_dir="/tmp/hijack-e2e-session",
        role_suffix="--1",
        agent_name=_SUCCESSOR,
        agent_session_role="feedback",
        parent_agent_session_member_name=f"{_SESSION}--0",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="proj",
    )


def test_hijack_reload_escalate_inherits_both_repos_through_finalizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import _recovery_admission_dispatcher
    from sase.agent.hijack.recovery_successor import (
        read_recovery_ack,
        require_recovery_inheritance,
        write_recovery_ack,
    )
    from sase.ace.tui.models.agent_hijack_presentation import (
        apply_hijack_ledger_presentation,
    )
    from sase.agent.hijack.recover_settle import gather_recovery_inheritance
    from sase.core.process_identity import process_identity_token
    from sase.llm_provider.commit_finalizer_inheritance import (
        inherit_commit_finalizer_responsibility,
    )
    from sase.llm_provider.commit_finalizer_state import collect_dirty_state

    setup = _make_held_hijack(tmp_path, monkeypatch)
    successor: subprocess.Popen[str] | None = None
    try:
        row = SimpleNamespace(
            status="HIJACKED",
            hijack_id=setup["record"]["hijack_id"],
            get_artifacts_dir=lambda: str(setup["artifacts"]),
            hijack_overlay=None,
            hijack_diff_summary=None,
            hijack_record=None,
        )
        apply_hijack_ledger_presentation([row])
        assert row.hijack_record is not None
        assert row.hijack_record["state"] == "held"
        assert row.hijack_overlay is None

        monkeypatch.setattr(
            _recovery_admission_dispatcher,
            "_target_available",
            lambda _target: (True, None),
        )
        captured: dict[str, Any] = {}

        def spawn_successor(**kwargs: Any) -> Any:
            nonlocal successor
            descriptor = dict(kwargs["descriptor"])
            assert kwargs["transfer_from_pid"] == setup["record"]["pid"]
            assert kwargs["workspace_num"] == _WORKSPACE_NUM
            assert kwargs["workspace_dir"] == str(setup["workspace"])
            assert descriptor["reserved_successor_name"] == _SUCCESSOR

            child_artifacts = tmp_path / "successor-artifacts"
            child_artifacts.mkdir()
            successor = _start_waiting_fakey(
                tmp_path / "successor-process",
                home=setup["home"],
                artifacts=child_artifacts,
                state_dir=tmp_path / "successor-fakey-state",
            )
            token = process_identity_token(successor.pid)
            assert token
            child_meta = {
                "name": _SUCCESSOR,
                "pid": successor.pid,
                "process_identity": token,
                "goal_id": setup["metadata"]["goal_id"],
                "bead_id": setup["metadata"]["bead_id"],
                "autonomy": setup["autonomy"],
                "agent_session": _SESSION,
                "agent_llm_provider": "fakey",
                "agent_model": "fakey-large",
                "agent_effort": "xhigh",
            }
            (child_artifacts / "agent_meta.json").write_text(
                json.dumps(child_meta, indent=2) + "\n", encoding="utf-8"
            )

            with monkeypatch.context() as local:
                local.setattr(
                    "sase.llm_provider.commit_finalizer_inheritance.append_repo_open_event_once",
                    lambda _event: None,
                )
                assert inherit_commit_finalizer_responsibility(
                    parent_artifacts_dir=str(setup["artifacts"]),
                    child_artifacts_dir=str(child_artifacts),
                    predecessor_name=_AGENT,
                    successor_name=_SUCCESSOR,
                    project_name="proj",
                    parent_workspace_dir=str(setup["workspace"]),
                    child_workspace_dir=str(setup["workspace"]),
                    workspace_num=_WORKSPACE_NUM,
                )

            transfer = transfer_workspace_claim(
                str(setup["project_file"]),
                _WORKSPACE_NUM,
                from_pid=int(setup["record"]["pid"]),
                to_pid=successor.pid,
                new_workflow="ace(run)-20261106_120100",
                new_artifacts_timestamp=_SUCCESSOR_TIMESTAMP,
                cl_name=_SUCCESSOR,
            )
            assert transfer.success, transfer.error

            resolving_record = load_record(str(setup["record"]["hijack_id"]))
            assert resolving_record is not None
            subject = RecoverySubject(
                record=resolving_record,
                project_name="proj",
                predecessor_meta=dict(setup["metadata"]),
                done_outcome="hijacked",
                done_recovery={"state": "pending", "kind": "hijack"},
            )
            evidence = gather_recovery_inheritance(
                subject,
                str(child_artifacts),
                goal=setup["metadata"]["goal_id"],
                bead=setup["metadata"]["bead_id"],
            )
            assert evidence is not None
            target = str(descriptor["concrete_target"])
            provider_model, _, effort = target.partition("@")
            provider, _, model = provider_model.partition("/")
            lineage = descriptor["lineage"]
            if isinstance(lineage, str):
                lineage = json.loads(lineage)
            ack = require_recovery_inheritance(
                predecessor_goal=evidence.predecessor_goal,
                successor_goal=evidence.successor_goal,
                predecessor_bead=evidence.predecessor_bead,
                successor_bead=evidence.successor_bead,
                baseline_inherited=evidence.baseline_inherited,
                baseline_diagnostics=evidence.baseline_diagnostics,
                predecessor_repo_count=evidence.predecessor_repo_count,
                transferred_repo_count=evidence.transferred_repo_count,
                repo_diagnostics=evidence.repo_diagnostics,
                predecessor_autonomy=evidence.predecessor_autonomy,
                predecessor_name=evidence.predecessor_name,
                parent_meta=evidence.parent_meta,
                child_meta=evidence.child_meta,
                predecessor_inventory_missing=evidence.predecessor_inventory_missing,
                launch_identity=str(descriptor["launch_identity"]),
                successor_name=_SUCCESSOR,
                process_token=token,
                project="proj",
                workspace_num=_WORKSPACE_NUM,
                workspace_dir=str(setup["workspace"]),
                lineage=lineage,
                provider=provider,
                model=model,
                effort=effort,
                concrete_target=target,
            )
            write_recovery_ack(str(child_artifacts), ack)
            captured["artifacts"] = child_artifacts
            captured["evidence"] = evidence
            return SimpleNamespace(
                agent_name=_SUCCESSOR,
                pid=successor.pid,
                artifacts_dir=str(child_artifacts),
                workspace_num=_WORKSPACE_NUM,
                workspace_dir=str(setup["workspace"]),
                workflow_name="ace(run)-20261106_120100",
                cl_name=_SUCCESSOR,
                timestamp=_SUCCESSOR_TIMESTAMP,
            )

        from sase.agent.hijack.recover_common import resolver_identity

        def execution_facts(
            record: Mapping[str, Any], target: str, mode: str
        ) -> Mapping[str, Any]:
            pid, token = resolver_identity()
            return {
                "schema_version": 1,
                "observed_resolver_pid": pid if mode == "dispatch" else None,
                "resolver_pid_live": mode != "dispatch"
                or pid == record.get("resolver_pid"),
                "resolver_identity_matches": mode != "dispatch"
                or token == record.get("resolver_process_identity_token"),
                "pinned_available": True,
                "pinned_unavailable_reason": None,
                "current_target": target,
                "provider_disabled": False,
                "model_unavailable": False,
            }

        deps = RecoveryDeps(
            load_subject=lambda _name: _subject(setup),
            preview=lambda record: _Preview(
                int(record["revision"]),
                [_PreviewRow("escalate", target=_TARGET)],
            ),
            build_prompt=lambda _record, **_kwargs: SimpleNamespace(
                prompt="Continue from the saved workspace evidence.",
                context_mode="fork",
            ),
            execution_facts=execution_facts,
            resolve_session_plan=_session_plan,
            spawn_successor=spawn_successor,
            admission_spawn_coordinator=False,
            settle_timeout_seconds=1.0,
            settle_poll_seconds=0.01,
        )
        result = recover_hijacked_agent(
            _AGENT,
            action="escalate",
            goal=setup["metadata"]["goal_id"],
            bead=setup["metadata"]["bead_id"],
            deps=deps,
        )
        assert result.kind == "launched", f"{result.message}: {dict(result.detail)}"
        assert result.successor == _SUCCESSOR
        assert result.concrete_target == _TARGET
        assert result.model_changed is True

        resolved = load_record(str(setup["record"]["hijack_id"]))
        assert resolved is not None and resolved["state"] == "resolved"
        done = json.loads((Path(setup["artifacts"]) / "done.json").read_text())
        assert done["recovery"]["state"] == "resolved"
        assert done["recovery"]["model_changed"] is True
        from sase.agent.hijack.core import agent_hijack_status_for_done_marker

        assert agent_hijack_status_for_done_marker("hijacked", done["recovery"]) == (
            "ESCALATED"
        )
        assert read_recovery_ack(str(captured["artifacts"])) is not None
        evidence = captured["evidence"]
        assert evidence.predecessor_repo_count == evidence.transferred_repo_count == 1
        assert evidence.baseline_inherited is True
        assert {
            Path(path) for path in load_dirty_baseline(Path(setup["artifacts"])) or {}
        } == {
            Path(path)
            for path in load_dirty_baseline(Path(captured["artifacts"])) or {}
        }

        with monkeypatch.context() as local:
            local.setenv("SASE_ARTIFACTS_DIR", str(captured["artifacts"]))
            finalizer_state = collect_dirty_state(
                str(setup["workspace"]), artifact_root=Path(captured["artifacts"])
            )
        changed_by_repo = {
            str(Path(repo.path).resolve()): set(repo.changed_files)
            for repo in finalizer_state.repos
        }
        assert "primary-work.txt" in changed_by_repo.get(
            str(setup["workspace"].resolve()), set()
        ), f"finalizer did not discover primary work: {changed_by_repo}"
        assert "linked-work.txt" in changed_by_repo[str(setup["linked"].resolve())]
        claims = get_claimed_workspaces(setup["project_file"])
        assert any(
            int(claim.workspace_num) == _WORKSPACE_NUM
            and int(claim.pid) == successor.pid
            and claim.cl_name == _SUCCESSOR
            for claim in claims
        )
    finally:
        if successor is not None:
            _stop_process(successor)
        _stop_process(setup["process"])


@pytest.mark.parametrize("action", ["restart", "dismiss"])
def test_restart_and_dismiss_snapshot_primary_and_linked_repos(
    action: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _make_held_hijack(tmp_path, monkeypatch)
    try:
        effects: list[str] = []

        def preview(record: Mapping[str, Any]) -> _Preview:
            return _Preview(
                int(record["revision"]),
                [
                    _PreviewRow("restart", target=None),
                    _PreviewRow("dismiss", target=None),
                ],
            )

        deps = ReleaseDeps(
            load_subject=lambda _name: _subject(setup),
            preview=preview,
            plan_restart=lambda _name: SimpleNamespace(name=_AGENT),
            execute_restart=lambda _plan: (
                effects.append("restart")
                or SimpleNamespace(status="ok", renamed_to=None)
            ),
            dismiss_row=lambda _name: (
                effects.append("dismiss")
                or SimpleNamespace(success=True, reason=None, message=None)
            ),
            release_bead_claim=lambda _record: (True, "released"),
        )
        result = recover_release_action(_AGENT, action=action, deps=deps)
        assert result.kind == "launched", result.message
        assert effects == [action]
        settled = load_record(str(setup["record"]["hijack_id"]))
        assert settled is not None
        assert settled["state"] == ("dismissed" if action == "dismiss" else "resolved")
        assert {Path(item["repo"]) for item in settled["snapshots"]} == {
            Path(setup["workspace"]),
            Path(setup["linked"]),
        }
        assert (Path(setup["artifacts"]) / "done.json").is_file()
    finally:
        _stop_process(setup["process"])
