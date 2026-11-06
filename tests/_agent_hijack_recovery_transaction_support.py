"""Shared production fixture for the hijack recovery transaction tests."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
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
from sase.llm_provider.commit_finalizer_inheritance import commit_inheritance_source

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


def parent_done(txn: Transaction) -> dict[str, Any]:
    """Read the predecessor's ``done.json`` marker."""
    return json.loads((txn.parent / "done.json").read_text(encoding="utf-8"))


class Transaction:
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
        # The session root is the attach parent used for naming; it is not
        # the hijacked predecessor whose repository responsibility transfers.
        self.session_root = tmp_path / "session-root"
        self.session_root.mkdir()
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
        primary_modified = self.workspace_dir / "notes.md"
        primary_modified.write_text(
            "# primary fixture change\n\nPredecessor primary work.\n",
            encoding="utf-8",
        )
        linked_modified = self.linked_repo / "notes.md"
        linked_modified.write_text(
            "# linked fixture change\n\nPredecessor linked work.\n",
            encoding="utf-8",
        )
        fingerprints = {
            str(self.workspace_dir): {
                "notes.md": [
                    hashlib.sha256(primary_modified.read_bytes()).hexdigest(),
                    None,
                ]
            },
            str(self.linked_repo): {
                "notes.md": [
                    hashlib.sha256(linked_modified.read_bytes()).hexdigest(),
                    None,
                ]
            },
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
                # Same source the runner's strict gate reads: the attach
                # plan's actual predecessor, not its session-root parent.
                parent_artifacts_dir = commit_inheritance_source(kwargs["plan"])[0]
                observation = collect_bootstrap_observation(
                    child_artifacts_dir=str(successor_dir),
                    parent_artifacts_dir=parent_artifacts_dir,
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
                "workspace_num": kwargs["workspace_num"],
                "workspace_dir": kwargs["workspace_dir"],
                "primary_work": (Path(kwargs["workspace_dir"]) / "notes.md").read_text(
                    encoding="utf-8"
                ),
                "linked_work": (self.linked_repo / "notes.md").read_text(
                    encoding="utf-8"
                ),
            }
        )

    def _spawn(self, **kwargs: Any) -> Any:
        assert kwargs["workspace_num"] == 3
        assert kwargs["workspace_dir"] == str(self.workspace_dir)
        assert kwargs["descriptor"]["launch_identity"]
        assert kwargs["descriptor"]["reserved_successor_name"] == "acme--4"
        assert kwargs["extra_env"][RECOVERY_STRICT_ENV] == "1"
        assert kwargs["plan"].parent_artifacts_dir == str(self.session_root)
        assert kwargs["plan"].predecessor_artifacts_dir == str(self.parent)
        assert kwargs["plan"].predecessor_name == "acme--3"
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
            resolve_session_plan=lambda session_base, project_name: txn.session_plan(),
            spawn_successor=self._spawn,
            terminate_successor=terminate_successor,
            admission_spawn_coordinator=False,
            settle_timeout_seconds=5.0,
            settle_poll_seconds=0.02,
        )

    def session_plan(self) -> AgentSessionAttachLaunchPlan:
        """The real attach plan a live ``acme`` session would resolve."""
        return AgentSessionAttachLaunchPlan(
            parent_arg="acme",
            suffix_arg="@",
            parent_name="acme--0",
            parent_base="acme",
            parent_timestamp="20261105000000",
            parent_artifacts_dir=str(self.session_root),
            role_suffix="--4",
            agent_name="acme--4",
            agent_session_role="feedback",
            parent_agent_session_member_name="acme--0",
            parent_agent_session_role_suffix="--0",
            parent_needs_rename=False,
            parent_project_name="proj",
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
