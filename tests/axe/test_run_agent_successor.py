"""Direct tests for the in-process family-successor engine."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from sase.axe.run_agent_successor import (
    FollowupModel,
    SuccessorRequest,
    continue_as_successor,
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


def test_allocated_suffix_forwards_template_and_reservations(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/followup")
    reserved = ("--plan", "--1")

    with patch(
        "sase.axe.run_agent_successor.allocate_agent_family_child_suffix",
        return_value="--plan-0",
    ) as allocate:
        name = continue_as_successor(
            ctx,
            state,
            _request(
                suffix=None,
                suffix_template="--plan-@",
                extra_reserved_suffixes=reserved,
                agent_family_role="feedback",
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
    assert create.call_args.kwargs["agent_family_role"] == "feedback"


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
