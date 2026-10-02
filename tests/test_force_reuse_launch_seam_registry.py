"""Real-registry forced-reuse launch seam tests.

Split from ``tests.test_force_reuse_launch_seam``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from tests._force_reuse_launch_seam_helpers import (
    authorized_request,
    clan_kill_and_edit_prompt,
)

__all__ = [
    "test_forced_agent_session_member_relaunch_keeps_its_parent_resolvable",
    "test_launch_query_real_agent_session_cleanup_failure_prevents_spawn",
    "test_launch_query_wipes_real_agent_session_registry_before_spawn",
]


def test_launch_query_wipes_real_agent_session_registry_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Production-shaped agent-session-root reuse: a real registry, unmocked wipe.

    ``sase-op.2`` is seeded as a real durable agent session (the representation left
    behind once a planning shell hands off to a coding shell), not mocked
    away, because the agent-session-container refusal this pins regressed exactly
    at the real ``wipe_agent_name_for_reuse`` seam. The rewritten prompt must
    reach ``launch_agents_from_cwd`` only after the agent-session reservation
    (``sase-op.2`` and both concrete shells) is fully gone from the registry.
    """
    import json
    from pathlib import Path

    from sase.agent.names import get_reserved_agent_names, rebuild_name_registry
    from sase.main.query_handler._launch import launch_query

    agent_session_name = "sase-op.2"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }

    def _seed_artifact(
        suffix: str,
        name: str,
        *,
        done: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> Path:
        workflow_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
        )
        path = workflow_dir / suffix
        path.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "workflow_name": name, **(meta or {})}
        (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
        if done:
            (path / "done.json").write_text(
                json.dumps({"name": name, "outcome": "completed"}), encoding="utf-8"
            )
        return path

    plan = _seed_artifact(
        "20260801170000", plan_name, done=True, meta=agent_session_meta
    )
    _seed_artifact(
        "20260801170100",
        code_name,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
    )

    prompt = clan_kill_and_edit_prompt()
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    request = authorized_request(prompt)

    registry_snapshots_at_spawn: list[set[str]] = []

    def _capture_spawn(*_args: Any, **_kwargs: Any) -> list[Any]:
        registry_snapshots_at_spawn.append(get_reserved_agent_names())
        return []

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.ops.cli.load_request", return_value=request),
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=_capture_spawn,
        ) as mock_launch,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
        patch("sase.ops.commands.run.emit_run_launch_result"),
        pytest.raises(SystemExit),
    ):
        rebuild_name_registry()
        assert {agent_session_name, plan_name, code_name} <= get_reserved_agent_names()
        launch_query(prompt)

    record_failed.assert_not_called()
    mock_launch.assert_called_once()
    assert mock_launch.call_args.args[0] == (
        "%id(2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work"
    )
    assert registry_snapshots_at_spawn
    assert {agent_session_name, plan_name, code_name}.isdisjoint(
        registry_snapshots_at_spawn[0]
    )


def _seed_auto_agent_session_member(
    home: Any,
    suffix: str,
    name: str,
    agent_session_name: str,
    role: str,
    *,
    done_name: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """Seed one finished member of a ``%auto`` plan-chain session under *home*."""
    import json

    path = home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    path.mkdir(parents=True)
    payload = {
        "name": name,
        "workflow_name": agent_session_name,
        "agent_session": agent_session_name,
        "agent_session_role": role,
        "agent_session_parallel": False,
        **(meta or {}),
    }
    (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
    (path / "done.json").write_text(
        json.dumps({"name": done_name or name, "outcome": "completed"}),
        encoding="utf-8",
    )
    return path


def test_forced_agent_session_member_relaunch_keeps_its_parent_resolvable(
    tmp_path: Any,
) -> None:
    """``,x`` on ``P--code`` must not wipe the ``P--plan`` root it attaches to.

    A ``%auto`` chain's root ``done.json`` names the code member, and every
    member stores the agent session as ``workflow_name``. Both used to pull the root
    into the wipe of ``P--code``, so agent-session attach then failed with "parent
    agent 'P' was not found" after deleting the whole agent session.
    """
    from pathlib import Path

    from sase.agent._agent_session_attach_resolution import (
        resolve_agent_session_attach_plan,
    )
    from sase.agent._agent_session_attach_types import AgentSessionAttachDirective
    from sase.agent.force_reuse_launch import (
        apply_force_reuse_launch,
        plan_force_reuse_launch,
    )
    from sase.agent.names import get_reserved_agent_names, rebuild_name_registry

    agent_session_name = "sase-17m.3.1.land"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    root = _seed_auto_agent_session_member(
        tmp_path,
        "20260924115043",
        plan_name,
        agent_session_name,
        "root",
        done_name=code_name,
        meta={"plan_chain_root": True},
    )
    code = _seed_auto_agent_session_member(
        tmp_path,
        "20260924115200",
        code_name,
        agent_session_name,
        "code",
        meta={"parent_timestamp": root.name},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        launch_plan = plan_force_reuse_launch(
            f"%id(!code, session={agent_session_name})\nDo work"
        )
        assert launch_plan is not None
        assert launch_plan.owner_names == [code_name]

        apply_force_reuse_launch(launch_plan)

        assert not code.exists()
        assert root.exists()
        assert {agent_session_name, plan_name} <= get_reserved_agent_names()

        attach_plan = resolve_agent_session_attach_plan(
            AgentSessionAttachDirective(
                parent=agent_session_name, suffix="code", force_reuse=True
            ),
            project_name="proj",
        )

    assert attach_plan.agent_name == code_name
    assert attach_plan.parent_name == plan_name
    assert Path(attach_plan.parent_artifacts_dir) == root


def test_launch_query_real_agent_session_cleanup_failure_prevents_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A genuine cleanup failure for the agent-session-shaped owner aborts spawn.

    ``wipe_names_for_forced_reuse``/``wipe_force_reuse_owner`` and the real
    registry lookup run unmocked against a seeded agent-session registry entry for
    the production-shaped owner name; only the low-level
    ``sase.agent.names.wipe_agent_name_for_reuse`` primitive is made to
    report an artifact-deletion error, the same shape of failure a real I/O
    error would produce.
    """
    import json
    from pathlib import Path

    from sase.agent.names import AgentNameWipeResult, rebuild_name_registry
    from sase.main.query_handler._launch import launch_query

    agent_session_name = "sase-op.2"
    plan_name = f"{agent_session_name}--plan"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }

    def _seed_artifact(
        suffix: str,
        name: str,
        *,
        done: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> Path:
        workflow_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
        )
        path = workflow_dir / suffix
        path.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "workflow_name": name, **(meta or {})}
        (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
        if done:
            (path / "done.json").write_text(
                json.dumps({"name": name, "outcome": "completed"}), encoding="utf-8"
            )
        return path

    _seed_artifact("20260801180000", plan_name, done=True, meta=agent_session_meta)

    prompt = clan_kill_and_edit_prompt()
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_MONITOR_ID", raising=False)
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    request = authorized_request(prompt)

    def _fail_with_permission_error(name: str, **_kwargs: Any) -> AgentNameWipeResult:
        return AgentNameWipeResult(
            target_name=name, found=True, errors=("permission denied",)
        )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()

        with (
            patch("sase.ops.cli.load_request", return_value=request),
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names",
                return_value=[],
            ),
            patch(
                "sase.xprompt.unresolved.scan_query_for_unresolved_references",
                return_value=[],
            ),
            patch(
                "sase.agent.names.wipe_agent_name_for_reuse",
                side_effect=_fail_with_permission_error,
            ),
            patch(
                "sase.main.query_handler._launch.launch_agents_from_cwd"
            ) as mock_launch,
            patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
            patch("sase.ops.commands.run.emit_run_launch_result") as emit_result,
            pytest.raises(SystemExit) as excinfo,
        ):
            launch_query(prompt)

    assert excinfo.value.code == 1
    mock_launch.assert_not_called()
    record_failed.assert_called_once_with(prompt, origin="typed")
    emit_result.assert_called_once()
    emit_kwargs = emit_result.call_args.kwargs
    assert emit_kwargs["success"] is False
    assert "permission denied" in emit_kwargs["message"]
