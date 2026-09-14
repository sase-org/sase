"""Pooled-alias reservation regression tests through a ``#gh:`` wrapper rename.

Covers ``execute_workflow()`` renaming the anonymous workflow display name
via a ``#gh:...`` directive: the bootstrap reservation must still be the one
redeemed at the prompt step even after the rename, even if another launch
consumes an intervening pool slot first, and the pre-rename
``is_anonymous()`` output-handler behavior must be unaffected.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.model_alias_policy import LARGE_MODEL_ALIAS_NAME
from sase.xprompt.models import InputArg, InputType, create_anonymous_workflow
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from tests._model_alias_defaults_fixture import frozen_selector_provider_model_effort

_POOL_ALIAS = LARGE_MODEL_ALIAS_NAME


@pytest.fixture(autouse=True)
def _force_pool_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat both frozen ``@large`` pool members as always available.

    Mirrors the setup already used by the runner-metadata pool tests in
    ``test_reasoning_effort_metadata_persistence.py``: a bare ``claude``
    provider config (so the default launch setting uses the shipped
    ``@large`` pool) with availability filtering disabled at both seams.
    Alias resolution reads the callable indirectly through ``config``, while
    reservation redemption imports it directly in ``launch_selection``; both
    checks are neutralised so a host without one pool member's CLI installed
    cannot change which member these tests observe.
    """
    from sase.llm_provider import config as llm_config

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(llm_config, "_resolved_target_is_available", lambda _t: True)
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.resolved_target_is_available",
        lambda _target, **_kwargs: True,
    )
    llm_config._get_model_aliases_for_token.cache_clear()


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

    # Prove redemption uses the bootstrap reservation even if another launch
    # advances the same pool before this workflow reaches its prompt step.
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


def test_root_metadata_reconciles_after_gh_wrapper_display_rename(
    tmp_path: Path,
) -> None:
    """A ``#gh:`` wrapper keeps anonymous-launch identity after display rename."""
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)

    root_meta, marker, captured = _run_renamed_gh_launch(
        tmp_path,
        "renamed",
        "#gh:sase",
    )
    provider, model = _selected(captured)

    assert (provider, model) == (member0[0], member0[1])
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
