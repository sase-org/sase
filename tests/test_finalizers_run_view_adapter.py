"""Run-view adapter end to end: real controller into the shared projection.

Each case drives the real controller and executors (fake commands and a
test-local plugin fixture), then runs the artifacts through the
TUI-agnostic collector, the ``project_finalizer_node_view`` binding, and
the typed facade, asserting the section 3.2 vocabulary states.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.models.agent_types import AgentType
from sase.ace.tui.models.finalizer_run_targets import node_run_targets
from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.core.finalizer_run_view import (
    FinalizerNodeView,
    finalizer_node_view_from_dict,
    project_finalizer_node_view,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.progress import ProgressJournal
from sase.finalizers.providers import FinalizerProviderRecord
from sase.finalizers.run_view_inputs import (
    RUN_INPUT_MAX_BYTES,
    STEPS_TEXT_MAX_BYTES,
    RunTarget,
    build_node_request,
    collect_run_input,
    run_inputs_signature,
)
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives

from .finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    commit_instance,
    config_for,
    init_live_repo,
    isolate_host_config,
    prepare_live_env,
    submit_deferral_from_context,
    use_config,
)

STEPS_PLUGIN_REF = "test-steps@steps"
STEPS_PLUGIN_ID = "steps"


def _provenance() -> FinalizerFieldProvenance:
    return FinalizerFieldProvenance("test", None)


def _command_config(
    command: list[str],
    *,
    instance_id: str = "local-check",
    max_attempts: int = 1,
) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=(instance_id,),
        required=(),
        instances={
            instance_id: ConfiguredFinalizerInstance(
                instance_id=instance_id,
                provider_ref="builtin@command",
                max_attempts=max_attempts,
                config={
                    "command": command,
                    "cwd": "primary",
                    "timeout": "30s",
                    "submission": "none",
                },
                provenance={"use": _provenance()},
            )
        },
        provenance={},
    )


def _prepare_command_run(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, config: FinalizerConfig
) -> None:
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", lambda: config)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: DirtyState(project_dir=str(artifacts), repos=(), details=""),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(artifacts))
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))


def _run(artifacts: Path) -> Any:
    return run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def _project(
    artifacts: Path,
    *,
    turn_terminal: bool = True,
    run_id: str = "run-1",
) -> FinalizerNodeView:
    request = build_node_request(
        [
            RunTarget(
                run_id=run_id, artifacts_dir=str(artifacts), turn_terminal=turn_terminal
            )
        ]
    )
    return project_finalizer_node_view(request)


def test_success_projects_typed_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config([sys.executable, "-c", "print('checked')"]),
    )

    result = _run(artifacts)

    assert result.content == "done"
    view = _project(artifacts)
    assert view.status == "success"
    assert view.glyph == "success"
    assert view.run_level_trouble is False
    assert len(view.runs) == 1
    run = view.runs[0]
    assert run.disposition == "ran"
    assert run.reason is None
    assert [item.status for item in run.declarations] == ["accepted"]
    assert len(run.instances) == 1
    instance = run.instances[0]
    assert instance.instance_id == "local-check"
    assert instance.status == "success"
    assert [(item.attempt, item.status) for item in instance.attempts] == [
        (1, "success")
    ]
    assert len(instance.operations) == 1
    operation = instance.operations[0]
    assert operation.op == "command"
    assert operation.kind == "subprocess"
    assert operation.returncode == 0
    assert operation.timed_out is False
    assert [(item.kind, item.name) for item in operation.logs] == [
        ("stdout", "attempt-1.stdout"),
        ("stderr", "attempt-1.stderr"),
    ]
    kinds = {item.kind: item.value for item in instance.evidence}
    assert kinds["exit_code"] == "0"
    assert "duration_seconds" in kinds
    assert instance.warnings == 0
    assert instance.failure_reason is None


def test_fail_retry_then_pass_supersedes_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    script = tmp_path / "flaky.py"
    script.write_text(
        "import pathlib, sys\n"
        "marker = pathlib.Path(sys.argv[1])\n"
        "if marker.exists():\n"
        "    sys.exit(0)\n"
        "marker.write_text('failed-once')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    marker = tmp_path / "flaky.marker"
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config(
            [sys.executable, str(script), str(marker)],
            instance_id="flaky-check",
            max_attempts=2,
        ),
    )

    result = _run(artifacts)

    assert result.content == "done"
    assert marker.is_file()
    view = _project(artifacts)
    assert view.status == "success"
    instance = view.runs[0].instances[0]
    assert instance.instance_id == "flaky-check"
    assert instance.status == "success"
    assert [(item.attempt, item.status) for item in instance.attempts] == [
        (1, "failed"),
        (2, "success"),
    ]
    assert [item.returncode for item in instance.operations] == [1, 0]
    # Errors from the superseded attempt never paint red.
    assert [
        (item.code, item.severity, item.attempt) for item in instance.diagnostics
    ] == [("command_failed", "superseded", 1)]


def test_deferral_projects_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "secret.env").write_text("TOKEN=xyz\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    use_config(
        monkeypatch,
        config_for(
            {"commit": replace(commit_instance(), refusal="defer")}, ("commit",)
        ),
    )

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_deferral_from_context(
        artifacts, reason="unsafe_content", paths=["secret.env"]
    )
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    runner.assert_not_called()
    view = _project(artifacts)
    assert view.status == "deferred"
    instance = view.runs[0].instances[0]
    assert instance.instance_id == "commit"
    assert instance.status == "deferred"
    assert instance.deferral is not None
    assert instance.deferral.reason == "unsafe_content"
    assert instance.deferral.paths == ["secret.env"]


def test_handoff_skip_projects_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    # Production order: the plan seals at turn start, the skip lands later.
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config([sys.executable, "-c", "print('checked')"]),
    )
    (artifacts / PLAN_PENDING_MARKER).write_text("pending", encoding="utf-8")
    sentinel = InvokeResult(content="untouched")

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=sentinel,
        model_tier="small",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result is sentinel
    view = _project(artifacts, turn_terminal=False)
    assert view.status == "skipped"
    assert view.glyph == "skipped"
    run = view.runs[0]
    assert run.disposition == "skipped"
    assert run.reason == "skipped · handoff:plan"
    assert [item.status for item in run.instances] == ["skipped"]


def test_kill_mid_op_projects_interrupted_with_live_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    # Production order: the plan seals at turn start; the kill leaves the
    # journal open with the live sink retained.
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config([sys.executable, "-c", "print('checked')"]),
    )
    journal = ProgressJournal(str(artifacts))
    journal.record(
        "phase_started",
        run_id="killed-run",
        plan_digest="digest-killed",
        mode="normal",
        runner={"pid": 1, "identity": "deadboot:123"},
    )
    journal.record("cycle_started", cycle=1)
    journal.record("instance_started", instance_id="local-check")
    journal.record(
        "attempt_started", instance_id="local-check", attempt=1, max_attempts=1
    )
    journal.record(
        "op_started",
        instance_id="local-check",
        attempt=1,
        op="command",
        kind="subprocess",
        label="sleep 300",
    )
    live = artifacts / "finalizers" / "local-check" / "attempt-1.command.live"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("still working...\npartial line", encoding="utf-8")

    view = _project(artifacts, turn_terminal=True)

    assert view.status == "interrupted"
    assert view.glyph == "interrupted"
    assert view.run_level_trouble is True
    run = view.runs[0]
    assert run.disposition == "interrupted"
    assert run.reason == "runner dead"
    instance = run.instances[0]
    assert instance.status == "interrupted"
    assert [(item.attempt, item.status) for item in instance.attempts] == [
        (1, "running")
    ]
    assert len(instance.operations) == 1
    operation = instance.operations[0]
    assert operation.live_tail == ["still working...", "partial line"]
    assert [(item.kind, item.name) for item in operation.logs] == [
        ("live", "attempt-1.command.live")
    ]


def _write_steps_plugin_site(site: Path) -> None:
    site.mkdir(parents=True)
    (site / "steps_plugin.py").write_text(
        "from sase.finalizers.steps import emit_step\n"
        "def provider(request):\n"
        "    operation = str(request['operation'])\n"
        "    if operation == 'execute':\n"
        "        emit_step('scanning tree', state='start')\n"
        "        emit_step('tree clean', state='ok', detail='0 findings')\n"
        "        return {'schema_version': 1, 'operation': operation,\n"
        "                'provider_ref': 'test-steps@steps',\n"
        "                'instance_id': str(request['instance_id']),\n"
        "                'status': 'success',\n"
        "                'evidence': [{'kind': 'finding_count', 'value': '0'}]}\n"
        "    return {'schema_version': 1, 'operation': operation,\n"
        "            'provider_ref': 'test-steps@steps',\n"
        "            'instance_id': str(request['instance_id']), 'status': 'ok',\n"
        "            'evidence': []}\n",
        encoding="utf-8",
    )
    dist = site / "test_steps-1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: test-steps\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        "[sase_finalizers]\nsteps = steps_plugin:provider\n",
        encoding="utf-8",
    )


def _advertise_steps_plugin(monkeypatch: pytest.MonkeyPatch, site: Path) -> None:
    from sase.finalizers.providers import collect_finalizer_providers as original

    monkeypatch.syspath_prepend(str(site))
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH", str(site) if not existing else str(site) + os.pathsep + existing
    )
    plugin = FinalizerProviderRecord(
        provider_ref=STEPS_PLUGIN_REF,
        provider_id=STEPS_PLUGIN_ID,
        package="test-steps",
        version="1.0.0",
        entry_point="steps_plugin:provider",
        builtin=False,
        capabilities=("describe", "validate", "execute", "verify"),
        load_status="ok",
    )
    builtins = tuple(item for item in original() if item.builtin)

    def providers() -> tuple[FinalizerProviderRecord, ...]:
        return (*builtins, plugin)

    monkeypatch.setattr(
        "sase.finalizers.providers.collect_finalizer_providers", providers
    )
    monkeypatch.setattr(
        "sase.finalizers.executor.collect_finalizer_providers", providers
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.diagnose_finalizer_providers",
        lambda *_args, **_kwargs: (),
    )


def test_plugin_execute_steps_project_typed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    site = tmp_path / "plugin-site"
    _write_steps_plugin_site(site)
    _advertise_steps_plugin(monkeypatch, site)
    _prepare_command_run(
        monkeypatch,
        artifacts,
        FinalizerConfig(
            defaults=("steps-check",),
            required=(),
            instances={
                "steps-check": ConfiguredFinalizerInstance(
                    instance_id="steps-check",
                    provider_ref=STEPS_PLUGIN_REF,
                    config={"env": ["PYTHONPATH"]},
                    provenance={"use": _provenance()},
                )
            },
            provenance={},
        ),
    )
    from .finalizers_live_e2e_test_helpers import submit_from_context

    submit_from_context(artifacts)

    result = _run(artifacts)

    assert result.content == "done"
    view = _project(artifacts)
    assert view.status == "success"
    instance = view.runs[0].instances[0]
    assert instance.instance_id == "steps-check"
    assert instance.status == "success"
    kinds = {item.kind: item.value for item in instance.evidence}
    assert kinds["finding_count"] == "0"
    execute = next(item for item in instance.operations if item.op == "execute")
    assert [(item.step, item.state) for item in execute.steps] == [
        ("scanning tree", "start"),
        ("tree clean", "ok"),
    ]


def test_collector_marks_oversize_inputs_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config([sys.executable, "-c", "print('checked')"]),
    )
    big = artifacts / "agent_meta.json"
    with open(big, "wb") as handle:
        handle.write(b"x" * (RUN_INPUT_MAX_BYTES + 1))

    run = collect_run_input(RunTarget(run_id="run-1", artifacts_dir=str(artifacts)))

    assert run["agent_meta"]["too_large"] is True
    assert run["agent_meta"]["text"] is None
    assert run["agent_meta"]["size"] == RUN_INPUT_MAX_BYTES + 1


def test_collector_drops_oversize_steps_text_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    _prepare_command_run(
        monkeypatch,
        artifacts,
        _command_config([sys.executable, "-c", "print('checked')"]),
    )
    _run(artifacts)
    steps = next((artifacts / "finalizers" / "local-check").glob("*.steps.jsonl"), None)
    if steps is None:
        steps = (
            artifacts / "finalizers" / "local-check" / "attempt-1.command.steps.jsonl"
        )
        steps.write_text("{}\n", encoding="utf-8")
    with open(steps, "ab") as handle:
        handle.write(b"y" * (STEPS_TEXT_MAX_BYTES + 1))

    run = collect_run_input(RunTarget(run_id="run-1", artifacts_dir=str(artifacts)))
    entry = next(
        item for item in run["instances"][0]["files"] if item["name"] == steps.name
    )

    assert entry["text"]["text"] is None
    assert entry["text"]["too_large"] is False


def test_signature_is_stable_and_stat_sensitive(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    target = RunTarget(run_id="run-1", artifacts_dir=str(artifacts))

    first = run_inputs_signature([target])
    assert run_inputs_signature([target]) == first
    (artifacts / "finalizer_plan.json").write_text('{"plan": {}}', encoding="utf-8")
    assert run_inputs_signature([target]) != first


def test_node_run_targets_lone_turn_and_pinned_attempt(tmp_path: Path) -> None:
    agent = SimpleNamespace(
        identity=(AgentType.RUNNING, "agent-1", None),
        agent_name="agent-1",
        status="DONE",
        is_monitor=False,
        finalizer_status=None,
        artifacts_dir=str(tmp_path),
    )

    (targets,) = node_run_targets(agent)

    assert targets.run_id == "run|agent-1|"
    assert targets.artifacts_dir == str(tmp_path)
    assert targets.number == 0
    assert targets.kind == "agent"
    assert targets.turn_terminal is True

    (pinned,) = node_run_targets(agent, 3)

    assert pinned.run_id == targets.run_id
    assert pinned.artifacts_dir == os.path.join(str(tmp_path), "attempts", "3")


def test_node_run_targets_session_container_in_roster_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.tui.models.agent_session_members as members

    first = SimpleNamespace(
        identity=(AgentType.RUNNING, "session--a", None),
        agent_name="session--a",
        status="DONE",
        is_monitor=False,
        finalizer_status=None,
        artifacts_dir=str(tmp_path / "a"),
    )
    second = SimpleNamespace(
        identity=(AgentType.RUNNING, "session--b", None),
        agent_name="session--b",
        status="RUNNING",
        is_monitor=True,
        finalizer_status=None,
        artifacts_dir=str(tmp_path / "b"),
    )
    container = SimpleNamespace(agent_name="session")
    monkeypatch.setattr(
        members, "is_sequential_agent_session_container", lambda _agent: True
    )
    monkeypatch.setattr(
        members, "concrete_agent_session_turn_rows", lambda _agent: (first, second)
    )

    def _fake_get_dir(turn: Any) -> str | None:
        return getattr(turn, "artifacts_dir", None)

    monkeypatch.setattr(
        "sase.ace.tui.models.artifact_files.get_artifacts_dir", _fake_get_dir
    )

    targets = node_run_targets(container)

    assert [item.number for item in targets] == [0, 1]
    assert [item.run_id for item in targets] == [
        "run|session--a|",
        "run|session--b|",
    ]
    assert [item.kind for item in targets] == ["agent", "monitor"]
    assert [item.turn_terminal for item in targets] == [True, False]


def test_facade_converters_are_tolerant() -> None:
    view = finalizer_node_view_from_dict(
        {
            "status": "mystery-state",
            "runs": [
                {
                    "run_id": "r",
                    "disposition": "mystery",
                    "number": "not-a-number",
                    "cycles": -1,
                    "unknown_future_key": {"nested": True},
                    "instances": [{"instance_id": "x"}],
                }
            ],
        }
    )

    assert view.status == "mystery-state"
    assert view.glyph == ""
    assert view.run_level_trouble is False
    assert view.attention_instance_id is None
    (run,) = view.runs
    assert run.disposition == "mystery"
    assert run.number == 0
    assert run.cycles == -1
    assert run.instances[0].status == ""
    with pytest.raises(ValueError):
        finalizer_node_view_from_dict("nope")  # type: ignore[arg-type]
