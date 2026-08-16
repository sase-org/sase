"""Composed regression tests for the pooled-alias single-consumption fix.

Exercises the runner metadata preview (``extract_directives_and_write_meta``)
together with the anonymous workflow's real prompt-step invocation
(``WorkflowExecutor`` / ``invoke_agent``) against the shipped two-member
``@large`` pool that ``llm_provider.default_model`` delegates to. A pooled alias must advance
its machine-global round-robin cursor exactly once per real LLM invocation:
never during the runner's metadata preview, and never twice for one launch.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.model_alias_policy import LARGE_MODEL_ALIAS_NAME
from sase.xprompt.models import InputArg, InputType, create_anonymous_workflow
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from tests._model_alias_defaults_fixture import frozen_selector_provider_model_effort

_POOL_ALIAS = LARGE_MODEL_ALIAS_NAME


@pytest.fixture(autouse=True)
def _force_pool_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat both frozen ``@large`` pool members as always available.

    Mirrors the setup already used by the runner-metadata pool tests in
    ``test_reasoning_effort_metadata_persistence.py``: a bare ``claude``
    provider config (so the default launch setting uses the shipped
    ``@large`` pool) with availability filtering disabled so member
    selection is deterministic regardless of installed provider CLIs.
    """
    from sase.llm_provider import config as llm_config

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(llm_config, "_resolved_target_is_available", lambda _t: True)
    llm_config._get_model_aliases_for_token.cache_clear()


def _pool_cursor() -> int:
    state_path = Path.home() / ".sase" / "llm_lb.json"
    if not state_path.exists():
        return 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = state["entries"].get(_POOL_ALIAS)
    return int(entry["cursor"]) if entry else 0


def _run_composed_launch(
    tmp_path: Path,
    name: str,
    prompt: str,
) -> tuple[dict, dict, dict]:
    """Preview via runner metadata, then run the real anonymous-workflow step.

    Mirrors the two real call sites in production: the runner's bootstrap
    calls ``extract_directives_and_write_meta`` (a non-consuming preview)
    before ``run_execution_loop`` hands the prompt to a ``WorkflowExecutor``
    running an anonymous, single-step workflow (the one real invocation).

    Returns ``(root_meta, step_marker, captured)`` where ``captured`` holds
    the ``invoke_agent``/``save_chat_history`` kwargs under
    ``"invoke_kwargs"`` / ``"chat_kwargs"``.
    """
    workspace_dir = str(tmp_path / f"{name}_workspace")
    artifacts_dir = str(tmp_path / f"{name}_artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    captured: dict[str, object] = {}

    def _fake_invoke_agent(prompt_text: str, **kwargs: object) -> AIMessage:
        del prompt_text
        captured["invoke_kwargs"] = kwargs
        return AIMessage(content="ok")

    def _fake_save_chat_history(**kwargs: object) -> str:
        captured["chat_kwargs"] = kwargs
        return "/tmp/chat.md"

    anon_workflow = create_anonymous_workflow(prompt)
    with (
        patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
        patch(
            "sase.history.chat.save_chat_history",
            side_effect=_fake_save_chat_history,
        ),
    ):
        executor = WorkflowExecutor(
            workflow=anon_workflow,
            args={},
            artifacts_dir=artifacts_dir,
        )
        assert executor.execute() is True

    root_meta = json.loads(
        (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    marker = json.loads(
        (Path(artifacts_dir) / "prompt_step_main.json").read_text(encoding="utf-8")
    )
    return root_meta, marker, captured


def _gh_workflow_catalog() -> dict[str, Workflow]:
    return {
        "gh": Workflow(
            name="gh",
            inputs=[InputArg(name="project", type=InputType.LINE)],
            steps=[
                WorkflowStep(
                    name="main",
                    prompt_part="Project: {{ project }}",
                )
            ],
            tags=frozenset({XPromptTag.vcs}),
        )
    }


def _run_renamed_gh_launch(
    tmp_path: Path,
    name: str,
    prompt: str,
    *,
    silent: bool = True,
) -> tuple[dict, dict, dict]:
    """Run through ``execute_workflow()`` so ``#gh:...`` renames the wrapper."""
    workspace_dir = str(tmp_path / f"{name}_workspace")
    artifacts_dir = str(tmp_path / f"{name}_artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    from sase.llm_provider.launch_selection import resolve_launch_selection
    from sase.xprompt.directives import PromptDirectives

    intervening = resolve_launch_selection(PromptDirectives(), consume=True)
    assert intervening is not None

    captured: dict[str, object] = {}

    def _fake_invoke_agent(prompt_text: str, **kwargs: object) -> AIMessage:
        del prompt_text
        captured["invoke_kwargs"] = kwargs
        return AIMessage(content="ok")

    def _fake_save_chat_history(**kwargs: object) -> str:
        captured["chat_kwargs"] = kwargs
        return "/tmp/chat.md"

    anon_workflow = create_anonymous_workflow(prompt)
    with (
        patch(
            "sase.xprompt.loader.get_all_prompts", return_value=_gh_workflow_catalog()
        ),
        patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value=_gh_workflow_catalog(),
        ),
        patch("sase.llm_provider.invoke_agent", side_effect=_fake_invoke_agent),
        patch(
            "sase.history.chat.save_chat_history",
            side_effect=_fake_save_chat_history,
        ),
    ):
        from sase.xprompt.workflow_runner import execute_workflow

        execute_workflow(
            anon_workflow.name,
            [],
            {},
            artifacts_dir=artifacts_dir,
            workflow_obj=anon_workflow,
            silent=silent,
        )

    root_meta = json.loads(
        (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    marker = json.loads(
        (Path(artifacts_dir) / "prompt_step_main.json").read_text(encoding="utf-8")
    )
    return root_meta, marker, captured


def _selected(captured: dict[str, object]) -> tuple[str, str]:
    invoke_kwargs = captured["invoke_kwargs"]
    assert isinstance(invoke_kwargs, dict)
    selection = invoke_kwargs["launch_selection"]
    return selection.provider, selection.model


def test_two_consecutive_default_launches_alternate_pool_members(
    tmp_path: Path,
) -> None:
    """Two no-%model launches invoke opposite pool members, one cursor step apart."""
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)

    _, _, first = _run_composed_launch(tmp_path, "first", "do the work")
    assert _selected(first) == (member0[0], member0[1])
    assert _pool_cursor() == 1

    _, _, second = _run_composed_launch(tmp_path, "second", "do the work")
    assert _selected(second) == (member1[0], member1[1])
    assert _pool_cursor() == 0


def test_explicit_large_directive_and_default_alias_share_pool_cursor(
    tmp_path: Path,
) -> None:
    """A no-%model launch and a %model:@large launch share one cursor."""
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)

    _, _, first = _run_composed_launch(tmp_path, "first", "do the work")
    assert _selected(first) == (member0[0], member0[1])

    root_meta, marker, second = _run_composed_launch(
        tmp_path, "second", "%model:@large\ndo the work"
    )
    assert _selected(second) == (member1[0], member1[1])
    assert root_meta["model_alias_trail"] == ["large"]
    assert root_meta["model_alias_origin"] == "directive"
    assert marker["model_alias_trail"] == ["large"]
    assert marker["model_alias_origin"] == "directive"
    assert _pool_cursor() == 0


def test_root_metadata_step_marker_and_chat_agree_with_invoked_model(
    tmp_path: Path,
) -> None:
    """agent_meta.json, the step marker, and chat metadata all name the same
    model actually passed to the provider — not a separately re-resolved
    preview that could pick a different pool member."""
    root_meta, marker, captured = _run_composed_launch(tmp_path, "solo", "do the work")
    provider, model = _selected(captured)

    assert root_meta["model"] == model
    assert root_meta["llm_provider"] == provider
    assert root_meta["model_alias_trail"] == ["large"]
    assert root_meta["model_alias_origin"] == "default_model"
    assert marker["model"] == model
    assert marker["llm_provider"] == provider
    assert marker["model_alias_trail"] == ["large"]
    assert marker["model_alias_origin"] == "default_model"

    chat_kwargs = captured["chat_kwargs"]
    assert isinstance(chat_kwargs, dict)
    assert chat_kwargs["metadata_model"] == model
    assert chat_kwargs["metadata_llm_provider"] == provider


def test_root_metadata_reconciles_after_gh_wrapper_display_rename(
    tmp_path: Path,
) -> None:
    """A ``#gh:`` wrapper keeps anonymous-launch identity after display rename."""
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)

    root_meta, marker, captured = _run_renamed_gh_launch(
        tmp_path,
        "renamed",
        "#gh:sase",
    )
    provider, model = _selected(captured)

    assert (provider, model) == (member1[0], member1[1])
    assert root_meta["model"] == model
    assert root_meta["llm_provider"] == provider
    assert root_meta["model_alias_trail"] == ["large"]
    assert root_meta["model_alias_origin"] == "default_model"
    assert marker["model"] == model
    assert marker["llm_provider"] == provider


def test_gh_wrapper_display_rename_keeps_verbose_output_handling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-rename ``is_anonymous()`` output-handler behavior is unchanged."""
    captured: dict[str, object] = {}

    class _FakeWorkflowOutputHandler:
        def __init__(self) -> None:
            captured["output_handler_created"] = True

        def __getattr__(self, _name: str) -> object:
            def _noop(*_args: object, **_kwargs: object) -> None:
                return None

            return _noop

    monkeypatch.setattr(
        "sase.xprompt.workflow_output.WorkflowOutputHandler",
        _FakeWorkflowOutputHandler,
    )

    _run_renamed_gh_launch(
        tmp_path,
        "output_handler",
        "#gh:sase",
        silent=False,
    )

    assert captured["output_handler_created"] is True


def test_workflow_with_no_agent_step_does_not_advance_cursor(tmp_path: Path) -> None:
    """A workflow with only non-agent steps never touches the pool cursor."""
    step = WorkflowStep(name="s1", bash="echo ok")
    workflow = Workflow(name="bash_only", steps=[step])
    artifacts_dir = str(tmp_path / "bash_only")
    os.makedirs(artifacts_dir, exist_ok=True)

    executor = WorkflowExecutor(workflow=workflow, args={}, artifacts_dir=artifacts_dir)
    assert executor.execute() is True
    assert _pool_cursor() == 0


def test_runner_metadata_preview_never_advances_cursor_even_on_reexec(
    tmp_path: Path,
) -> None:
    """Metadata preparation (including a simulated re-exec) only previews."""
    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="do the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )
    assert _pool_cursor() == 0

    # Simulate a runner re-exec: preserved metadata is reused, still no consume.
    extract_directives_and_write_meta(
        prompt="do the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )
    assert _pool_cursor() == 0


def test_concurrent_consuming_resolutions_serialize_without_double_consumption(
    tmp_path: Path,
) -> None:
    """Concurrent real invocations each consume the shared pool exactly once.

    Exercises ``resolve_launch_selection(consume=True)`` directly (the exact
    boundary the workflow executor's prompt step calls) rather than the full
    runner pipeline, so the assertion isolates pool-cursor serialization from
    unrelated global state the broader runner touches.
    """
    from sase.llm_provider.launch_selection import resolve_launch_selection
    from sase.xprompt.directives import PromptDirectives

    del tmp_path  # unused; the pool lock lives under the isolated fake HOME
    n = 8
    results: list[tuple[str, str]] = []
    lock = threading.Lock()

    def _consume() -> None:
        selection = resolve_launch_selection(PromptDirectives(), consume=True)
        assert selection is not None
        with lock:
            results.append((selection.provider, selection.model))

    threads = [threading.Thread(target=_consume) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)[:2]
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)[:2]
    assert len(results) == n
    assert results.count(member0) == n // 2
    assert results.count(member1) == n // 2
    assert _pool_cursor() == 0
