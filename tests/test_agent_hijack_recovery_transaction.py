"""Composed production recovery transaction: immediate and queued recovery.

Covers phase ``integration`` of the keep-work recovery child epic: the
public executor (:func:`recover_hijacked_agent`) drives the real Rust
transitions (file-backed ledger CAS), the real Python/Rust preview, real
continuation preparation, real pinned-target validation, real durable
admission persistence (typed request store plus journal), the real strict
child bootstrap gate, and real settlement — replacing only the
provider/process boundary.

Fixture-world inputs that cannot exist in isolation are controlled, not
mocked around: no live agent session exists to resolve (the reserved
member is fixed to ``acme--4``), the host disable file is not part of the
fixture (availability reads see an enabled provider unless a test says
otherwise), and the model ladder is pinned so targets are deterministic.
The provider itself is an in-process probe invoked only after the real
bootstrap gate persists its ack; process termination and claim
verification use the real file-backed running field with the test's own
live pid, so identity evidence is genuine.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import ledger as ledger_module
from sase.agent.hijack import preview as preview_module
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import (
    RECOVERY_LAUNCH_IDENTITY_ENV,
    RecoveryDeps,
    RecoverySubject,
)
from sase.agent.hijack.recovery_successor import (
    RECOVERY_DESCRIPTOR_ENV,
    RECOVERY_LINEAGE_ENV,
    RECOVERY_STRICT_ENV,
    collect_bootstrap_observation,
    decode_recovery_descriptor,
    enforce_recovery_bootstrap,
)
from sase.core import paths as paths_module

_BASELINE_FILENAME = "commit_finalizer_baseline.json"
_LINKED_FILENAME = "opened_linked_workspaces.json"


def _install_deterministic_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the model ladder, alias candidates, and provider availability."""
    monkeypatch.setattr(
        preview_module,
        "agent_hijack_config",
        lambda: SimpleNamespace(
            escalation_ladder=("@large", "@xlarge"), successor_context="fork"
        ),
    )
    monkeypatch.setattr(
        preview_module,
        "build_alias_candidates",
        lambda ladder: {
            "@large": ["claude/opus@high"],
            "@xlarge": ["claude/opus@xhigh"],
        },
    )


def _enable_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.llm_provider import provider_disable_peek as peek_module

    monkeypatch.setattr(peek_module, "peek_active_provider_disables", lambda: {})


def _disable_provider(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    from sase.llm_provider import provider_disable_peek as peek_module

    monkeypatch.setattr(
        peek_module, "peek_active_provider_disables", lambda: {provider: object()}
    )


class _Transaction:
    """Isolated production fixture with real persistence and a fake provider."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        provider_probe: list[dict[str, Any]] | None = None,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.root = tmp_path
        self.state_root = tmp_path / ".sase"
        self.parent = tmp_path / "parent"
        self.parent.mkdir()
        self.workspace_dir = tmp_path / "ws3"
        self.workspace_dir.mkdir()
        self.linked_repo = tmp_path / "linked" / "sase-core"
        self.linked_repo.mkdir(parents=True)
        self.project_file = tmp_path / "proj.sase"
        self.pid = os.getpid()
        from sase.core.process_identity import process_identity_token

        self.token = process_identity_token(self.pid)
        assert self.token, "the fixture needs a real process identity token"
        self.provider_calls: list[dict[str, Any]] = (
            provider_probe if provider_probe is not None else []
        )
        self.spawned_prompts: list[str] = []
        self.terminations: list[int] = []
        self.terminate_verified = True
        self.spawn_mode: str = "provider"
        self.ack_overrides: dict[str, Any] = {}
        self.child_goal = "goal-1"
        self.child_bead: str | None = "sase-1"
        self._env_lock = threading.Lock()
        self._write_fixture_files()
        monkeypatch.setattr(
            paths_module, "sase_subdir", lambda name: self.state_root / name
        )
        monkeypatch.setattr(
            ledger_module, "sase_subdir", lambda name: self.state_root / name
        )
        _install_deterministic_inputs(monkeypatch)
        _enable_providers(monkeypatch)
        ledger_module.create_record(self._record())

    def _write_fixture_files(self) -> None:
        modified = self.linked_repo / "notes.md"
        modified.write_text("# fixture change\n\nPredecessor work.\n", encoding="utf-8")
        digest = hashlib.sha256(modified.read_bytes()).hexdigest()
        fingerprints = {
            str(self.workspace_dir): {"notes.md": [digest, None]},
            str(self.linked_repo): {"notes.md": [digest, None]},
        }
        repos = {
            "schema_version": 3,
            "linked_repos": [
                {
                    "name": "sase-core",
                    "workspace_dir": str(self.linked_repo),
                    "kind": "linked",
                    "reason": "test",
                    "opened_at": "test",
                }
            ],
        }
        (self.parent / _BASELINE_FILENAME).write_text(
            json.dumps(fingerprints), encoding="utf-8"
        )
        (self.parent / _LINKED_FILENAME).write_text(json.dumps(repos), encoding="utf-8")
        from sase.autonomy.record import resolve_selection

        autonomy = resolve_selection("manual", source="inherited", surface="launch")
        (self.parent / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": "acme--3",
                    "bead_id": "sase-1",
                    "goal_id": "goal-1",
                    "chat_path": str(self.parent / "chat.md"),
                    "autonomy": dict(autonomy),
                }
            ),
            encoding="utf-8",
        )
        (self.parent / "chat.md").write_text(
            "## Prompt\n\nFinish the task.\n\n## Response\n\nPartial work.\n",
            encoding="utf-8",
        )
        (self.parent / "raw_prompt.md").write_text(
            "Finish the task.\n\n```markdown\n#fork:other-agent\n%id(other-agent)\n```\n",
            encoding="utf-8",
        )
        (self.parent / "done.json").write_text(
            json.dumps(
                {
                    "outcome": "hijacked",
                    "recovery": {
                        "state": "pending",
                        "kind": "hijack",
                        "hijack_id": "h-123",
                    },
                }
            ),
            encoding="utf-8",
        )
        self.project_file.write_text(
            "\n".join(
                (
                    "# Project: proj",
                    "RUNNING:",
                    "  #3 | 111 | ace(run)-20261105_000000 | acme--3 | "
                    "20261105000000 | PINNED",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def _record(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "hijack_id": "h-123",
            "agent_name": "acme--3",
            "artifacts_dir": str(self.parent),
            "session": "acme",
            "project_file": str(self.project_file),
            "workspace_num": 3,
            "workspace_dir": str(self.workspace_dir),
            "pid": 111,
            "expected_claim_owner_pid": 111,
            "provider": "claude",
            "model": "opus",
            "effort": "high",
            "model_alias": "large",
            "model_alias_trail": ["large"],
            "model_origin": "prompt",
            "state": "held",
            "revision": 7,
        }

    def child_dir(self, launch_identity: str) -> Path:
        return self.root / f"succ-{launch_identity[:12]}"

    def _write_child(self, successor_dir: Path) -> None:
        from sase.llm_provider.commit_finalizer_baseline import BASELINE_FILENAME
        from sase._linked_repo_markers import OPENED_LINKED_FILENAME

        assert BASELINE_FILENAME == _BASELINE_FILENAME
        assert OPENED_LINKED_FILENAME == _LINKED_FILENAME
        successor_dir.mkdir(parents=True, exist_ok=True)
        (successor_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": "acme--4",
                    "pid": self.pid,
                    "process_identity": self.token,
                    "bead_id": self.child_bead,
                    "goal_id": self.child_goal,
                }
            ),
            encoding="utf-8",
        )
        for filename in (_BASELINE_FILENAME, _LINKED_FILENAME):
            (successor_dir / filename).write_text(
                (self.parent / filename).read_text(encoding="utf-8"), encoding="utf-8"
            )

    def _transfer_claim(self) -> None:
        from sase.running_field._transfer import transfer_workspace_claim

        result = transfer_workspace_claim(
            str(self.project_file),
            3,
            from_pid=111,
            to_pid=self.pid,
            new_workflow="ace(run)-20261105_000001",
            new_artifacts_timestamp="20261105000001",
            cl_name="acme--4",
            caller_tag="recovery-transaction-test",
        )
        assert result.success, f"claim transfer failed: {result.error}"

    def _run_gate(self, kwargs: dict[str, Any], successor_dir: Path) -> None:
        """Run the real child-side bootstrap gate, then the fake provider."""
        extra_env = dict(kwargs["extra_env"])
        saved = {key: os.environ.get(key) for key in extra_env}
        with self._env_lock:
            os.environ.update(extra_env)
            try:
                descriptor = decode_recovery_descriptor(
                    os.environ.get(RECOVERY_DESCRIPTOR_ENV)
                )
                target = str(kwargs["descriptor"]["concrete_target"])
                target_provider, _, target_model = target.partition("/")
                target_model, _, target_effort = target_model.partition("@")
                observation = collect_bootstrap_observation(
                    child_artifacts_dir=str(successor_dir),
                    parent_artifacts_dir=str(self.parent),
                    successor_name="acme--4",
                    process_token=self.token,
                    project=str(kwargs["project_name"]),
                    workspace_num=int(kwargs["workspace_num"]),
                    workspace_dir=str(kwargs["workspace_dir"]),
                    provider=target_provider or None,
                    model=target_model or None,
                    effort=target_effort or None,
                    launch_identity=os.environ.get(RECOVERY_LAUNCH_IDENTITY_ENV),
                )
                ack = enforce_recovery_bootstrap(
                    child_artifacts_dir=str(successor_dir),
                    descriptor=descriptor,
                    observation=observation,
                )
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        ack.update(self.ack_overrides)
        if self.ack_overrides:
            from sase.agent.hijack.recovery_successor import write_recovery_ack

            write_recovery_ack(str(successor_dir), ack)
        self.provider_calls.append(
            {
                "prompt": str(kwargs["prompt"]),
                "goal": ack.get("goal"),
                "bead": ack.get("bead"),
                "model": ack.get("concrete_target"),
            }
        )

    def _spawn(self, **kwargs: Any) -> Any:
        assert kwargs["workspace_num"] == 3
        assert kwargs["workspace_dir"] == str(self.workspace_dir)
        assert kwargs["descriptor"]["launch_identity"]
        assert kwargs["descriptor"]["reserved_successor_name"] == "acme--4"
        assert kwargs["extra_env"][RECOVERY_STRICT_ENV] == "1"
        assert RECOVERY_LINEAGE_ENV in kwargs["extra_env"]
        assert RECOVERY_LAUNCH_IDENTITY_ENV in kwargs["extra_env"]
        assert RECOVERY_DESCRIPTOR_ENV in kwargs["extra_env"]
        self.spawned_prompts.append(str(kwargs["prompt"]))
        if self.spawn_mode == "lost_contact":
            raise RuntimeError("lost contact before child boot")
        successor_dir = self.child_dir(str(kwargs["descriptor"]["launch_identity"]))
        self._transfer_claim()
        self._write_child(successor_dir)
        self._run_gate(kwargs, successor_dir)
        return SimpleNamespace(
            agent_name="acme--4",
            pid=self.pid,
            artifacts_dir=str(successor_dir),
            workspace_num=3,
            workspace_dir=str(self.workspace_dir),
            workflow_name="ace(run)-20261105_000001",
            cl_name="acme--4",
            timestamp="20261105000001",
        )

    def deps(self) -> RecoveryDeps:
        txn = self

        def load_subject(agent_or_name: object) -> RecoverySubject | None:
            from sase.agent.hijack.recover_subject import (
                read_predecessor_done_marker,
            )
            from sase.history.chat_fork.common import load_json_object

            _ = agent_or_name
            record = ledger_module.load_record("h-123")
            assert record is not None
            meta = load_json_object(self.parent / "agent_meta.json")
            assert isinstance(meta, dict)
            done_outcome, done_recovery = read_predecessor_done_marker(record)
            # No live agent session exists in the fixture world, so the
            # project identity is fixed while every read stays real.
            return RecoverySubject(
                record=dict(record),
                project_name="proj",
                predecessor_meta=dict(meta),
                done_outcome=done_outcome,
                done_recovery=done_recovery,
            )

        def terminate_successor(
            pid: int, _artifacts_dir: str | None, _token: str | None
        ) -> dict[str, Any]:
            txn.terminations.append(pid)
            if txn.terminate_verified:
                return {"verified_dead": True, "state": "killed", "survivors": []}
            return {"verified_dead": False, "state": "survivors", "survivors": [pid]}

        return RecoveryDeps(
            load_subject=load_subject,
            resolve_session_plan=lambda session_base, project_name: SimpleNamespace(
                agent_name="acme--4"
            ),
            spawn_successor=self._spawn,
            terminate_successor=terminate_successor,
            admission_spawn_coordinator=False,
            settle_timeout_seconds=5.0,
            settle_poll_seconds=0.02,
        )

    def recover(self, **kwargs: Any) -> Any:
        params: dict[str, Any] = {"action": "continue", "deps": self.deps()}
        params.update(kwargs)
        return recover_hijacked_agent("acme--3", **params)

    def record(self) -> dict[str, Any]:
        current = ledger_module.load_record("h-123")
        assert current is not None
        return dict(current)

    def bundles(self) -> list[Path]:
        root = self.state_root / "typed_launches"
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir())

    def children(self) -> list[Path]:
        return sorted(
            path
            for path in self.root.iterdir()
            if path.is_dir() and path.name.startswith("succ-")
        )


def _parent_done(txn: _Transaction) -> dict[str, Any]:
    return json.loads((txn.parent / "done.json").read_text(encoding="utf-8"))


def _ack_for(txn: _Transaction, child: Path) -> dict[str, Any]:
    from sase.agent.hijack.recovery_successor import read_recovery_ack

    ack = read_recovery_ack(str(child))
    assert ack is not None
    return dict(ack)


def test_continue_full_transaction_launches_with_real_policy_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    result = txn.recover(action="continue")

    assert result.kind == "launched"
    assert result.concrete_target == "claude/opus@high"
    assert result.successor == "acme--4"
    assert result.launch_identity
    assert result.admission_request_id
    assert txn.record()["state"] == "resolved"
    # One durable request, one child, same workspace pair and exact target.
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    assert ack["launch_identity"] == result.launch_identity
    assert ack["successor_name"] == "acme--4"
    assert ack["concrete_target"] == "claude/opus@high"
    assert ack["provider"] == "claude"
    assert ack["model"] == "opus"
    assert ack["effort"] == "high"
    assert ack["workspace_num"] == 3
    assert ack["workspace_dir"] == str(txn.workspace_dir)
    assert ack["goal"] == "goal-1"
    assert ack["bead"] == "sase-1"
    assert ack["goal_verified"] is True
    assert ack["bead_verified"] is True
    assert ack["scope_verified"] is True
    assert ack["baselines_verified"] is True
    assert ack["inventory_verified"] is True
    # The provider boundary observes the original inheritance, not a copy.
    assert txn.provider_calls == [
        {
            "prompt": txn.spawned_prompts[0],
            "goal": "goal-1",
            "bead": "sase-1",
            "model": "claude/opus@high",
        }
    ]
    assert txn.spawned_prompts[0].startswith("%model:claude/opus@high")
    # The prepared prompt stays inert: the fork example is literal text.
    assert "#fork:other-agent\n%id(other-agent)" in txn.spawned_prompts[0]
    # Predecessor outcome is preserved; only recovery fields are resolved.
    done = _parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "resolved"
    assert done["recovery"]["action"] == "continue"
    assert done["recovery"]["successor"] == "acme--4"
    # The held claim moved to the successor on the same workspace pair.
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(str(txn.project_file))
    owned = [claim for claim in claims if claim.workspace_num == 3]
    assert len(owned) == 1
    assert owned[0].pid == txn.pid


def test_escalate_full_transaction_pins_changed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    result = txn.recover(action="escalate")

    assert result.kind == "launched"
    assert result.concrete_target == "claude/opus@xhigh"
    assert result.model_changed is True
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    assert ack["concrete_target"] == "claude/opus@xhigh"
    assert ack["effort"] == "xhigh"
    assert txn.provider_calls[0]["model"] == "claude/opus@xhigh"
    assert txn.provider_calls[0]["goal"] == "goal-1"
    done = _parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["action"] == "escalate"


def test_instruct_edited_prompt_with_explicit_model_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import preview as preview_module

    txn = _Transaction(monkeypatch, tmp_path)
    edited = preview_module.build_hijack_continuation_prompt(
        txn.record(), model_target="claude/opus@high"
    ).prompt
    edited += "\n\nKeep the existing changes and use the edited model.\n"

    result = txn.recover(action="continue", prompt=edited, model="sonnet@low")

    assert result.kind == "launched"
    assert result.action == "instruct"
    assert result.concrete_target == "claude/sonnet@low"
    assert result.model_changed is True
    assert txn.spawned_prompts[0].startswith("%model:claude/sonnet@low")
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    assert ack["model"] == "sonnet"
    assert ack["effort"] == "low"
    assert ack["goal"] == "goal-1"
    assert result.detail["context_mode"] == "fork"


def test_concurrent_resolvers_create_one_request_and_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    results: list[Any] = []
    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            results.append(txn.recover(action="continue"))
        except BaseException as exc:  # noqa: BLE001 - surface thread failures
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors
    assert len(results) == 2
    kinds = sorted(result.kind for result in results)
    assert kinds[1] == "launched"
    assert kinds[0] in {"already_resolving", "already_resolved"}
    launched = next(result for result in results if result.kind == "launched")
    waiting = next(result for result in results if result.kind != "launched")
    assert waiting.admission_request_id == launched.admission_request_id
    assert waiting.launch_identity == launched.launch_identity
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert txn.record()["state"] == "resolved"


def test_crash_after_cas_resumes_the_same_attempt_without_a_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolver that dies after CAS leaves a resumable real attempt."""
    from sase.agent.hijack import ledger as ledger_module
    from sase.agent.hijack.recover_common import admission_request_id_for
    from sase.agent.hijack.recover_common import new_launch_identity
    from sase.agent.hijack.recover_subject import lineage_for
    from sase.agent.hijack.recovery_admission import (
        persist_prepared_recovery_descriptor,
        prepare_recovery_admission_descriptor,
    )
    from sase.agent.hijack.recover_target import resolve_effective_target
    from sase.agent.launch_submission import capture_launch_submitted_at

    txn = _Transaction(monkeypatch, tmp_path)
    held = txn.record()
    preview = preview_module.hijack_recovery_preview(dict(held))
    row = preview.action("continue")
    assert row is not None
    target = resolve_effective_target(
        action="continue",
        record=held,
        preview_action={
            "available": row.available,
            "reason": row.reason,
            "target": row.target,
        },
        model_override=None,
        prompt_text=None,
    )
    launch_identity = new_launch_identity()
    request_id = admission_request_id_for("h-123", launch_identity)
    descriptor = prepare_recovery_admission_descriptor(
        record=held,
        action=target.action,
        target=target.concrete_target,
        model_changed=target.model_changed,
        prompt="prepared",
        context_mode="fork",
        reserved_successor_name="acme--4",
        session_base="acme",
        project_name="proj",
        launch_identity=launch_identity,
        admission_request_id=request_id,
        lineage=lineage_for(hijack_id="h-123", record=held, target=target),
        resolver_pid=os.getpid(),
        resolver_process_identity_token=None,
        attempt_revision=int(held.get("revision", 0)) + 1,
        launch_submitted_at=capture_launch_submitted_at(),
    )
    persist_prepared_recovery_descriptor(descriptor)
    # The crash happens here: begin_resolution is the last write. A fresh
    # coordinator process reconstructs from the same durable evidence. The
    # event carries the full reservation the Rust machine requires.
    resolving = ledger_module.cas_advance_record(
        dict(held),
        {
            "event": "begin_resolution",
            "action": target.action,
            "reserved_successor_name": "acme--4",
            "concrete_target_model": target.concrete_target,
            "model_changed": target.model_changed,
            "resolver_pid": os.getpid(),
            "launch_identity": launch_identity,
            "admission_request_id": request_id,
            "admission_identity": descriptor["dispatch_fingerprint"],
        },
    )
    assert resolving["state"] == "resolving"

    resumed = txn.recover(action="continue")

    # The fresh resolver re-dispatches the same durable attempt exactly
    # once; settlement stays with reconciliation, so the record resolves
    # nothing yet and no duplicate request or child may appear.
    assert resumed.kind == "already_resolving"
    assert resumed.admission_request_id == request_id
    assert resumed.launch_identity == launch_identity
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert len(txn.provider_calls) == 1
    assert txn.record()["state"] == "resolving"

    again = txn.recover(action="continue")

    assert again.kind == "already_resolving"
    assert again.admission_request_id == request_id
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert len(txn.provider_calls) == 1


def test_uncertain_spawn_keeps_resolving_and_resumes_the_same_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    txn.spawn_mode = "lost_contact"
    first = txn.recover(action="continue")

    assert first.kind == "uncertain"
    assert txn.record()["state"] == "resolving"
    assert txn.record()["launch_stage"] == "dispatching"
    assert txn.children() == []
    assert txn.provider_calls == []

    resumed = txn.recover(action="continue")

    assert resumed.kind == "already_resolving"
    assert resumed.admission_request_id == first.admission_request_id
    assert resumed.launch_identity == first.launch_identity
    assert resumed.detail["admission"]["state"] == "dispatching"
    assert len(txn.bundles()) == 1
    assert txn.children() == []
    assert txn.record()["state"] == "resolving"


def test_cancel_of_uncertain_dispatch_retains_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack.recovery_admission import (
        cancel_recovery_admission_request,
        observe_recovery_admission,
    )
    from sase.agent.launch_admission import run_coordinator_in_bundle

    txn = _Transaction(monkeypatch, tmp_path)
    txn.spawn_mode = "lost_contact"
    first = txn.recover(action="continue")
    assert first.kind == "uncertain"

    # Cancelling an uncertain dispatch proves nothing: the journal stays
    # dispatching and the record retains resolving for reconciliation.
    cancelled = cancel_recovery_admission_request(
        str(first.admission_request_id), reason="stop request"
    )

    assert cancelled["state"] == "dispatching"
    assert cancelled["admission_complete"] is False
    assert txn.record()["state"] == "resolving"
    status = observe_recovery_admission(str(first.admission_request_id))
    assert status["state"] == "dispatching"
    # A fresh coordinator reads the same bundle and still cannot finish it.
    bundle = txn.bundles()[0]
    progress = run_coordinator_in_bundle(bundle)
    assert progress.complete is False
    assert txn.children() == []
    assert txn.provider_calls == []
    assert observe_recovery_admission(str(first.admission_request_id))["state"] == (
        "dispatching"
    )


def test_disabled_provider_refuses_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    _disable_provider(monkeypatch, "claude")

    result = txn.recover(action="continue")

    assert result.kind == "refused"
    assert result.detail["code"] == "provider_disabled"
    assert txn.record()["state"] == "held"
    assert txn.spawned_prompts == []
    assert txn.children() == []
    assert txn.bundles() == []


def test_failed_inheritance_never_runs_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The child boots with a bead the predecessor never held, so the real
    # bootstrap gate refuses before the provider boundary is reached.
    txn = _Transaction(monkeypatch, tmp_path)
    txn.child_bead = "sase-999"

    result = txn.recover(action="continue")

    assert result.kind == "error"
    assert result.detail["code"] == "launch_failed"
    assert txn.record()["state"] == "held"
    assert txn.provider_calls == []


def test_failed_termination_retains_resolving_for_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _Transaction(monkeypatch, tmp_path)
    txn.terminate_verified = False
    txn.ack_overrides = {"launch_identity": "wrong-identity"}

    result = txn.recover(action="continue")

    assert result.kind == "uncertain"
    assert txn.record()["state"] == "resolving"
    assert txn.terminations == [txn.pid]
    assert "safe rollback is unproven" in result.message
    assert result.detail["rollback"]["outcome"] != "return_to_held"


def test_interrupted_settlement_replays_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import recover_settle as settle_module
    from sase.agent.hijack.recover_settle import settle_recovery

    txn = _Transaction(monkeypatch, tmp_path)
    calls = {"writes": 0}
    real_write = settle_module._write_predecessor_settlement

    def fail_once(*args: Any, **kwargs: Any) -> None:
        calls["writes"] += 1
        if calls["writes"] == 1:
            raise OSError("simulated crash between CAS and done.json")
        real_write(*args, **kwargs)

    monkeypatch.setattr(settle_module, "_write_predecessor_settlement", fail_once)
    with pytest.raises(OSError, match="simulated crash"):
        txn.recover(action="continue")

    # The CAS landed but the marker write did not: still resolving's
    # successor, done.json without recovery fields, outcome untouched.
    resolved = txn.record()
    assert resolved["state"] == "resolved"
    assert resolved["reserved_successor_name"] == "acme--4"
    done = _parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "pending"
    revision_after_crash = resolved["revision"]

    # Replaying the real settlement helper repairs only the marker: no new
    # CAS, no duplicate successor, same resolved revision. The fault only
    # fires once, so the replayed write goes through.
    replayed = settle_recovery(
        dict(resolved),
        action="continue",
        successor_name="acme--4",
    )

    assert replayed["state"] == "resolved"
    assert replayed["revision"] == revision_after_crash
    done = _parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "resolved"
    assert done["recovery"]["successor"] == "acme--4"
    assert calls["writes"] == 2
