"""Direct tests for the in-process agent-session-successor engine."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from sase.axe.run_agent_successor import (
    FollowupModel,
    STAGED_SUCCESSOR_ID_ENV,
    STAGED_SUCCESSOR_ORIGIN_DIR_ENV,
    SuccessorRequest,
    continue_as_successor,
    deliver_staged_successor_detached,
    mark_detached_successor_started_from_environment,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.staged_handoff import (
    acquire_adoption_lock,
    read_staged_successor,
    successor_prompt_digest,
    write_staged_successor_locked,
    write_successor_prompt,
)
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def _request(**overrides: object) -> SuccessorRequest:
    payload: dict[str, object] = {
        "base_meta": {"model": "opus"},
        "prompt": "do the next step",
        "suffix": PLAN_CHAIN_CODER_SUFFIX,
        "relationships": {"piped_from": "parent"},
        "prompt_artifact_label": "Full coder prompt",
    }
    payload.update(overrides)
    return SuccessorRequest(**payload)  # type: ignore[arg-type]


def test_explicit_suffix_creates_named_successor(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/followup")
    store = Mock()
    promote = Mock()

    name = continue_as_successor(
        ctx,
        state,
        _request(),
        create_artifacts=create,
        promote=promote,
        store_prompt=store,
    )

    assert name == "test_agent--code"
    assert state.current_role_suffix == PLAN_CHAIN_CODER_SUFFIX
    assert state.current_artifacts_dir == "/tmp/followup"
    assert state.current_prompt == "do the next step"
    assert state.agent_step == 2
    create.assert_called_once()
    assert create.call_args.args[1] == {"model": "opus"}
    assert create.call_args.args[2] == PLAN_CHAIN_CODER_SUFFIX
    assert create.call_args.kwargs["agent_name_override"] == "test_agent--code"
    assert create.call_args.kwargs["workflow_name"] == "test_agent"
    assert create.call_args.kwargs["relationships"] == {"piped_from": "parent"}
    store.assert_called_once_with(
        "/tmp/followup",
        "do the next step",
        label="Full coder prompt",
    )
    promote.assert_called_once_with(ctx.artifacts_dir, "test_agent")


def test_staged_successor_replay_reuses_persisted_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = replace(make_ctx(tmp_path), agent_name=None)
    state = make_state(tmp_path)
    origin_dir = state.current_artifacts_dir
    staged_id = "stage-questions-1"
    destination = tmp_path / "successor-artifacts"
    monkeypatch.setattr(
        "sase.artifacts.launch_artifacts_dir",
        lambda _project, _timestamp: str(destination),
    )
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        lambda count: ["20261031010101"] * count,
    )
    create_calls: list[dict[str, object]] = []

    def create_artifacts(
        _project: str,
        base_meta: dict[str, object],
        suffix: str,
        _origin_timestamp: str,
        **kwargs: object,
    ) -> str:
        create_calls.append(kwargs)
        destination.mkdir(parents=True, exist_ok=True)
        relationships = kwargs["relationships"]
        assert isinstance(relationships, dict)
        (destination / "agent_meta.json").write_text(
            json.dumps(
                {
                    **base_meta,
                    "name": suffix,
                    "staged_handoff_id": relationships["staged_handoff_id"],
                    "staged_successor_launch_id": relationships[
                        "staged_successor_launch_id"
                    ],
                }
            ),
            encoding="utf-8",
        )
        return str(destination)

    request = _request(suffix="--questions-0", suffix_template=None)
    first_store = Mock(side_effect=RuntimeError("interrupted after child creation"))
    with acquire_adoption_lock(Path(state.current_artifacts_dir)):
        with pytest.raises(RuntimeError, match="interrupted"):
            continue_as_successor(
                ctx,
                state,
                request,
                create_artifacts=create_artifacts,
                promote=Mock(),
                store_prompt=first_store,
                write_model_meta=Mock(),
                staged_id=staged_id,
                staged_kind="questions",
            )

    first = read_staged_successor(origin_dir, staged_id=staged_id)
    assert first is not None
    assert first["delivery_state"] == "prepared"
    assert first["successor"]["prompt_digest"] == successor_prompt_digest(
        request.prompt
    )

    retry_state = make_state(tmp_path)
    retry_store = Mock()
    with acquire_adoption_lock(Path(retry_state.current_artifacts_dir)):
        replay_name = continue_as_successor(
            ctx,
            retry_state,
            request,
            create_artifacts=create_artifacts,
            promote=Mock(),
            store_prompt=retry_store,
            write_model_meta=Mock(),
            staged_id=staged_id,
            staged_kind="questions",
        )

    replay = read_staged_successor(origin_dir, staged_id=staged_id)
    assert replay is not None
    assert replay["delivery_state"] == "created"
    assert replay["successor"] == first["successor"]
    assert replay_name == "--questions-0"
    assert len(create_calls) == 1
    assert retry_state.current_artifacts_dir == str(destination)
    retry_store.assert_called_once_with(
        str(destination), request.prompt, label="Full coder prompt"
    )
    assert retry_state.pending_staged_successor == {
        "origin_artifacts_dir": origin_dir,
        "staged_id": staged_id,
    }


def test_allocated_suffix_forwards_template_and_reservations(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/followup")
    reserved = ("--plan", "--1")

    with patch(
        "sase.axe._run_agent_successor_shared.allocate_agent_session_child_suffix",
        return_value="--plan-0",
    ) as allocate:
        name = continue_as_successor(
            ctx,
            state,
            _request(
                suffix=None,
                suffix_template="--plan-@",
                extra_reserved_suffixes=reserved,
                agent_session_role="feedback",
                prompt_artifact_label="Full question prompt",
            ),
            create_artifacts=create,
            promote=Mock(),
            store_prompt=Mock(),
        )

    allocate.assert_called_once_with(
        "test_agent",
        "--plan-@",
        extra_reserved_suffixes=reserved,
    )
    assert name == "test_agent--plan-0"
    assert state.current_role_suffix == "--plan-0"
    assert create.call_args.args[2] == "--plan-0"
    assert create.call_args.kwargs["agent_session_role"] == "feedback"


def test_unnamed_agent_renders_fallback_suffix(tmp_path: Path) -> None:
    ctx = replace(make_ctx(tmp_path), agent_name=None)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/followup")
    promote = Mock()

    name = continue_as_successor(
        ctx,
        state,
        _request(
            suffix=None,
            suffix_template="--@",
            fallback_token="1",
        ),
        create_artifacts=create,
        promote=promote,
        store_prompt=Mock(),
    )

    assert name == "--1"
    assert state.current_role_suffix == "--1"
    assert create.call_args.kwargs["agent_name_override"] is None
    promote.assert_not_called()


def test_step_two_promotion_fires_exactly_once(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    promote = Mock()
    create = Mock(return_value="/tmp/followup")

    continue_as_successor(
        ctx,
        state,
        _request(),
        create_artifacts=create,
        promote=promote,
        store_prompt=Mock(),
    )
    continue_as_successor(
        ctx,
        state,
        _request(),
        create_artifacts=create,
        promote=promote,
        store_prompt=Mock(),
    )

    assert state.agent_step == 3
    assert promote.call_args_list == [call(ctx.artifacts_dir, "test_agent")]


def test_promote_role_suffix_is_forwarded(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    promote = Mock()

    continue_as_successor(
        ctx,
        state,
        _request(promote_role_suffix="--0"),
        create_artifacts=Mock(return_value="/tmp/followup"),
        promote=promote,
        store_prompt=Mock(),
    )

    promote.assert_called_once_with(
        ctx.artifacts_dir,
        "test_agent",
        role_suffix="--0",
    )


def test_model_meta_written_only_when_supplied(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    write_model = Mock()
    model = FollowupModel(
        model_prefix="%model:opus\n",
        meta=("claude", "opus"),
    )

    continue_as_successor(
        ctx,
        state,
        _request(),
        create_artifacts=Mock(return_value="/tmp/followup"),
        promote=Mock(),
        store_prompt=Mock(),
        write_model_meta=write_model,
    )
    write_model.assert_not_called()

    state.agent_step = 1
    continue_as_successor(
        ctx,
        state,
        _request(model=model),
        create_artifacts=Mock(return_value="/tmp/followup"),
        promote=Mock(),
        store_prompt=Mock(),
        write_model_meta=write_model,
    )
    write_model.assert_called_once()
    assert write_model.call_args.args[1] is model


def test_relationships_and_prompt_artifact_are_recorded(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/followup")
    store = Mock()
    relationships = {"source_plan_agent_name": "test_agent--plan"}

    continue_as_successor(
        ctx,
        state,
        _request(
            relationships=relationships,
            prompt_artifact_label="Full question prompt",
            prompt="merged q&a",
        ),
        create_artifacts=create,
        promote=Mock(),
        store_prompt=store,
    )

    assert create.call_args.kwargs["relationships"] == relationships
    store.assert_called_once_with(
        "/tmp/followup",
        "merged q&a",
        label="Full question prompt",
    )


def test_before_create_callback_runs_after_suffix_and_before_artifacts(
    tmp_path: Path,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    events: list[tuple[str, str, str] | str] = []

    def before_create(suffix: str, successor_name: str) -> None:
        events.append(("before", suffix, successor_name))
        assert state.current_role_suffix == "--plan-0"
        assert state.current_artifacts_dir == str(tmp_path / "artifacts")
        assert state.current_prompt == "original prompt"

    def create(*_args: object, **_kwargs: object) -> str:
        events.append("create")
        return "/tmp/followup"

    continue_as_successor(
        ctx,
        state,
        _request(
            suffix=None,
            suffix_template="--plan-@",
            before_create=before_create,
        ),
        create_artifacts=create,
        promote=Mock(),
        store_prompt=Mock(),
    )

    assert events == [("before", "--plan-0", "test_agent--plan-0"), "create"]
    assert state.current_artifacts_dir == "/tmp/followup"
    assert state.current_prompt == "do the next step"


def test_before_state_change_persists_identity_before_mutating_runner(
    tmp_path: Path,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    original_dir = state.current_artifacts_dir
    events: list[str] = []
    create = Mock(return_value="/tmp/followup")

    def before_state_change(suffix: str, successor_name: str) -> None:
        events.append("persist")
        assert (suffix, successor_name) == ("--next", "test_agent--next")
        assert state.current_role_suffix == ".plan"
        assert state.current_artifacts_dir == original_dir
        assert state.current_prompt == "original prompt"

    with patch(
        "sase.axe.run_agent_successor_inprocess.mark_lifecycle_phase",
        side_effect=lambda *_args: events.append("lifecycle"),
    ):
        continue_as_successor(
            ctx,
            state,
            _request(
                suffix="--next",
                reserved_timestamp="20261031010101",
                before_state_change=before_state_change,
            ),
            create_artifacts=create,
            promote=Mock(),
            store_prompt=Mock(),
        )

    assert events == ["persist", "lifecycle"]
    assert create.call_args.kwargs["timestamp"] == "20261031010101"


def test_detached_successor_launch_is_reserved_once_with_saved_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "agent"}), encoding="utf-8"
    )
    destination = tmp_path / "successor"
    staged_id = "stage-1"
    launch_identity = "stage-1:20261031010101"
    prompt = "#fork:agent\nfinish this work"
    launch_prompt = "%model:fakey/model-x\n" + prompt
    project_file = tmp_path / "project.sase"
    project_file.write_text(
        "RUNNING:\n\nNAME: project\nSTATUS: Ready\n", encoding="utf-8"
    )
    prompt_ref = write_successor_prompt(origin, prompt)
    launch_prompt_ref = write_successor_prompt(
        origin, launch_prompt, filename="staged_successor_launch_prompt.md"
    )
    relationships = {
        "staged_handoff_id": staged_id,
        "staged_successor_launch_id": launch_identity,
    }
    successor = {
        "agent_name": "agent--1",
        "role_suffix": "--1",
        "artifacts_dir": str(destination),
        "artifacts_timestamp": "20261031_010101",
        "launch_timestamp": "20261031010101",
        "launch_identity": launch_identity,
        "prompt_ref": str(prompt_ref),
        "launch_prompt_ref": str(launch_prompt_ref),
        "prompt_digest": successor_prompt_digest(prompt),
        "launch_prompt_digest": successor_prompt_digest(launch_prompt),
        "project_name": "sase",
        "project_file": str(project_file),
        "origin_artifacts_timestamp": "20261028_120000",
        "cl_name": "test-cl",
        "workspace_dir": str(tmp_path),
        "workspace_num": 1,
        "is_home_mode": False,
        "model": "model-x",
        "provider": "fakey",
        "vcs_ref": None,
        "relationships": relationships,
        "continuation_refs": {},
        "loop_state": {},
        "followup_model": {
            "meta": ["fakey", "model-x"],
            "model_alias": None,
            "model_alias_trail": [],
            "model_alias_origin": None,
        },
        "attach_plan": None,
    }
    record = {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": "pipe",
        "origin_artifacts_dir": str(origin),
        "delivery_state": "prepared",
        "successor": successor,
    }
    with acquire_adoption_lock(origin):
        write_staged_successor_locked(record, artifacts_dir=origin)

    creation_calls: list[dict[str, object]] = []
    spawn = Mock(
        return_value=AgentLaunchResult(
            pid=123,
            workspace_num=1,
            workspace_dir=str(tmp_path),
            output_path=str(tmp_path / "output.log"),
        )
    )

    def create(*_args: object, **kwargs: object) -> str:
        creation_calls.append({"kwargs": kwargs, "base_meta": _args[1]})
        destination.mkdir(exist_ok=True)
        (destination / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": "agent--1",
                    "staged_handoff_id": staged_id,
                    "staged_successor_launch_id": launch_identity,
                }
            ),
            encoding="utf-8",
        )
        return str(destination)

    store_prompt = Mock()
    monkeypatch.setattr("sase.axe.run_agent_helpers.create_followup_artifacts", create)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_plan_artifacts.store_followup_prompt_artifact",
        store_prompt,
    )
    monkeypatch.setattr("sase.agent.detached_child.spawn_detached_child", spawn)

    launched = deliver_staged_successor_detached(str(origin), staged_id)
    replay = deliver_staged_successor_detached(str(origin), staged_id)

    assert launched.state == "submitted" and launched.pid == 123
    assert replay.state == "held"
    assert len(creation_calls) == 1
    creation_kwargs = creation_calls[0]["kwargs"]
    assert isinstance(creation_kwargs, dict)
    assert creation_kwargs["timestamp"] == "20261031010101"
    creation_meta = creation_calls[0]["base_meta"]
    assert isinstance(creation_meta, dict)
    assert creation_meta["model"] == "model-x"
    store_prompt.assert_called_once_with(
        str(destination), launch_prompt, label="Piped prompt"
    )
    spawn.assert_called_once()
    assert spawn.call_args.kwargs["timestamp"] == "20261031010101"
    assert spawn.call_args.kwargs["prompt"] == launch_prompt
    monkeypatch.setenv(STAGED_SUCCESSOR_ORIGIN_DIR_ENV, str(origin))
    monkeypatch.setenv(STAGED_SUCCESSOR_ID_ENV, staged_id)
    assert mark_detached_successor_started_from_environment()
    assert STAGED_SUCCESSOR_ORIGIN_DIR_ENV not in os.environ
    assert STAGED_SUCCESSOR_ID_ENV not in os.environ
    saved = read_staged_successor(str(origin), staged_id=staged_id)
    assert saved is not None and saved["delivery_state"] == "started"
    assert saved["successor"]["launch_pid"] == 123


@pytest.mark.parametrize(
    "suffix, suffix_template",
    [
        (None, None),
        (PLAN_CHAIN_CODER_SUFFIX, "--@"),
    ],
)
def test_suffix_and_template_are_mutually_exclusive(
    tmp_path: Path, suffix: str | None, suffix_template: str | None
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)

    with pytest.raises(ValueError, match="exactly one"):
        continue_as_successor(
            ctx,
            state,
            _request(suffix=suffix, suffix_template=suffix_template),
            create_artifacts=Mock(return_value="/tmp/followup"),
            promote=Mock(),
            store_prompt=Mock(),
        )
