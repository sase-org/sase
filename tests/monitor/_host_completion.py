"""Shared builders for host-completion settlement tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_monitor_host_completion_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import InvokeResult
from sase.monitor.followup import launch_followup_agent
from sase.monitor.host_completion import settle_host_completion
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

__all__ = [
    "make_intent",
    "make_meta",
    "patch_mod",
    "patch_success_path",
    "production_recovery",
    "sandbox_home",
    "settle",
]


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox ``SASE_HOME`` and clear agent identity env for host-completion tests."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def make_meta(**overrides: object) -> dict[str, Any]:
    """Return a monitor meta dict with host-completion fields."""
    meta: dict[str, Any] = {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": "cci:test",
        "monitor_profile": "verify",
        "monitor_command": "just check-full",
        "monitor_execution_argv": ["just", "check-full"],
        "workspace_dir": "/ws/20",
        "workspace_num": 20,
        "continuation_monitor_result_id": "result-1",
        "monitor_diagnostic_manifest_ref": "file:explicit:diag",
        "name": "acme--1",
    }
    meta.update(overrides)
    return meta


def _eligible_decision() -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "eligible": True,
        "action": "complete",
        "reason": None,
        "reasons": [],
        "rendered_message": "Required checks passed in 3m 02s.",
    }


def make_intent(*repo_ids: str) -> dict[str, Any]:
    """Return a bound conditional-completion intent for *repo_ids*."""
    repositories = [
        {
            "repo_id": repo_id,
            "action": "commit",
            "message": "fix: finish the change",
        }
        for repo_id in repo_ids
    ]
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "cci:test",
        "kind": "conditional_completion",
        "status": "bound",
        "success_message": "Required checks passed in {duration}.",
        "declaration": {
            "payloads": [
                {
                    "instance_id": "commit",
                    "payload": {"repositories": repositories, "deferrals": []},
                }
            ]
            if repositories
            else []
        },
        "repository_decisions": repositories,
        "seal": {"creator": {"workspace_id": "20"}, "plan_digest": "p" * 64},
        "verification": {"command": ["just", "check-full"]},
    }


def _capture() -> OutputCapture:
    return OutputCapture()


def production_recovery(
    recoveries: list[dict[str, Any]],
    *,
    launched: bool = True,
) -> Any:
    """Return a ``launch_followup_agent``-shaped recovery callback."""
    required = {
        name
        for name, parameter in inspect.signature(
            launch_followup_agent
        ).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    }

    def launch_recovery(
        artifacts_dir: str,
        meta: dict[str, Any],
        *,
        monitor_state: str,
        exit_code: int | None,
        elapsed_seconds: float,
        capture: OutputCapture,
        project_name: str,
        timeout_kind: str | None = None,
        transfer_from_pid: int | None = None,
    ) -> FollowupLaunchResult:
        kwargs = {
            "artifacts_dir": artifacts_dir,
            "meta": meta,
            "monitor_state": monitor_state,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed_seconds,
            "capture": capture,
            "project_name": project_name,
            "timeout_kind": timeout_kind,
            "transfer_from_pid": transfer_from_pid,
        }
        missing = required - set(kwargs)
        assert not missing, f"recovery omitted {sorted(missing)}"
        recoveries.append(kwargs)
        if launched:
            return FollowupLaunchResult(launched=True, agent_name="acme--2")
        return FollowupLaunchResult(launched=False)

    return launch_recovery


def settle(
    artifacts: Path,
    meta: dict[str, Any],
    *,
    launch_recovery: Any,
    release_claim: Any,
    **overrides: object,
) -> Any:
    """Call ``settle_host_completion`` with production-shaped defaults."""
    kwargs: dict[str, Any] = {
        "monitor_state": "completed",
        "exit_code": 0,
        "elapsed_seconds": 182,
        "project_name": "proj",
        "capture": _capture(),
        **overrides,
    }
    return settle_host_completion(
        str(artifacts),
        meta,
        launch_recovery=launch_recovery,
        release_claim=release_claim,
        **kwargs,
    )


def patch_mod(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    """Patch *name* on every host-completion implementation module."""
    for module in (
        "sase.monitor.host_completion_settle",
        "sase.monitor.host_completion_run",
        "sase.monitor.host_completion_execute",
        "sase.monitor.host_completion_complete",
        "sase.monitor.host_completion_state",
    ):
        monkeypatch.setattr(f"{module}.{name}", value, raising=False)


def patch_success_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision: dict[str, Any] | None = None,
    run_finalizers: MagicMock | None = None,
    intent: dict[str, Any] | None = None,
) -> MagicMock:
    """Stub the success-path collaborators used by ``settle_host_completion``."""
    plan = MagicMock()
    plan.plan_digest = "p" * 64
    plan.entries = [MagicMock(instance_id="commit", provider_ref="builtin@commit")]
    publication = MagicMock()
    publication.context.context_digest = "c" * 64
    publication.context.run_id = "run-1"
    publication.context.agent_id = "agent-1"
    publication.context.turn_nonce = "nonce-1"
    publication.context.plan_digest = "p" * 64
    publication.context.obligations = []
    publication.payload = {"manifest_template": {"payloads": []}}
    loaded = intent or make_intent()
    patch_mod(
        monkeypatch,
        "load_prepared_completion",
        lambda *_args, **_kwargs: loaded,
    )
    patch_mod(monkeypatch, "ensure_finalizer_plan", lambda *_a, **_k: plan)
    patch_mod(monkeypatch, "_ensure_finalizer_plan", lambda *_a, **_k: plan)
    patch_mod(
        monkeypatch,
        "observe_completion_repositories",
        lambda *_a, **_k: [],
    )

    def publish_context(**kwargs: object) -> MagicMock:
        artifacts_dir = str(kwargs["artifacts_dir"])
        run_id = Path(artifacts_dir).name
        assert os.environ.get("SASE_AGENT_TIMESTAMP") == run_id
        assert os.environ.get("SASE_ARTIFACTS_DIR") == artifacts_dir
        publication.context.run_id = run_id
        return publication

    patch_mod(monkeypatch, "publish_final_context", publish_context)
    monkeypatch.setattr(
        "sase.monitor.diagnostics.diagnostic_manifest",
        lambda *_a, **_k: {"stages": []},
    )
    patch_mod(
        monkeypatch,
        "evaluate_conditional_completion",
        lambda *_a, **_k: decision or _eligible_decision(),
    )
    patch_mod(
        monkeypatch,
        "install_prepared_declaration",
        lambda *_a, **_k: None,
    )
    patch_mod(
        monkeypatch,
        "_install_prepared_declaration",
        lambda *_a, **_k: None,
    )
    finalizers = run_finalizers or MagicMock(return_value=InvokeResult(content=""))
    patch_mod(monkeypatch, "run_finalizers", finalizers)
    patch_mod(
        monkeypatch,
        "consume_conditional_completion",
        lambda request: {**request["intent"], "status": "consumed"},
    )
    patch_mod(
        monkeypatch,
        "persist_prepared_completion",
        lambda *_a, **_k: None,
    )
    patch_mod(monkeypatch, "load_commit_results", lambda *_a, **_k: [])
    patch_mod(monkeypatch, "update_meta_field", lambda *_a, **_k: None)
    patch_mod(monkeypatch, "mint_finalizer_turn_nonce", lambda: "nonce-exec")
    return finalizers
