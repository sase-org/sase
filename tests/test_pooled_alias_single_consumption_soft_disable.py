"""Pooled-alias reservation regression tests around soft provider disables.

Covers a bootstrap reservation becoming stale after ``disable_provider(...,
mode=PROVIDER_DISABLE_MODE_SOFT)`` runs before redemption: the prompt step
must replace the stale target with a healthy pool member (whether the
reservation was disabled after bootstrap, injected directly, or invalidated
only later when another provider becomes available), while a still-healthy
primary reservation must be left alone even when later pool members are also
soft-disabled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.model_alias_policy import (
    LARGE_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    disable_provider,
)
from sase.xprompt.models import create_anonymous_workflow
from sase.xprompt.workflow_executor import WorkflowExecutor
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


def _pool_cursor() -> int:
    state_path = Path.home() / ".sase" / "llm_lb.json"
    if not state_path.exists():
        return 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = state["entries"].get(_POOL_ALIAS)
    return int(entry["cursor"]) if entry else 0


def _selected(captured: dict[str, object]) -> tuple[str, str]:
    invoke_kwargs = captured["invoke_kwargs"]
    assert isinstance(invoke_kwargs, dict)
    selection = invoke_kwargs["launch_selection"]
    return selection.provider, selection.model


def _bootstrap(tmp_path: Path, name: str, prompt: str) -> tuple[str, dict]:
    workspace_dir = str(tmp_path / f"{name}_workspace")
    artifacts_dir = str(tmp_path / f"{name}_artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )
    root_meta = json.loads(
        (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    return artifacts_dir, root_meta


def _redeem(artifacts_dir: str, prompt: str) -> tuple[dict, dict, dict]:
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


def _assert_replacement_agrees(
    root_meta: dict,
    marker: dict,
    captured: dict[str, object],
    *,
    provider: str,
    model: str,
    stale_target: str,
) -> None:
    invoked_provider, invoked_model = _selected(captured)
    assert (invoked_provider, invoked_model) == (provider, model)
    assert root_meta["model"] == model
    assert root_meta["llm_provider"] == provider
    assert marker["model"] == model
    assert marker["llm_provider"] == provider
    chat_kwargs = captured["chat_kwargs"]
    assert isinstance(chat_kwargs, dict)
    assert chat_kwargs["metadata_model"] == model
    assert chat_kwargs["metadata_llm_provider"] == provider
    assert root_meta["model_alias_reservation"]["target"] == stale_target
    assert root_meta["model_alias_reservation"]["redeemed"] is True


def test_soft_disable_after_bootstrap_replaces_claude_reservation(
    tmp_path: Path,
) -> None:
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)
    stale_target = f"{member0[0]}/{member0[1]}"
    artifacts_dir, first_meta = _bootstrap(tmp_path, "soft_after", "do the work")
    assert first_meta["model_alias_reservation"]["target"] == stale_target
    assert first_meta["model_alias_reservation"]["redeemed"] is False
    assert _pool_cursor() == 1

    disable_provider("claude", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    root_meta, marker, captured = _redeem(artifacts_dir, "do the work")
    _assert_replacement_agrees(
        root_meta,
        marker,
        captured,
        provider=member1[0],
        model=member1[1],
        stale_target=stale_target,
    )
    assert _pool_cursor() == 0


def test_codex_becoming_available_invalidates_soft_claude_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import config as llm_config

    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)
    available = {"claude", "grok"}

    def _target_available(target: str, **_kwargs: object) -> bool:
        return target.split("/", 1)[0] in available

    monkeypatch.setattr(llm_config, "_resolved_target_is_available", _target_available)
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.resolved_target_is_available",
        _target_available,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda provider: provider in available,
    )
    disable_provider("claude", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    artifacts_dir, first_meta = _bootstrap(tmp_path, "codex_later", "do the work")
    stale_target = f"{member0[0]}/{member0[1]}"
    assert first_meta["model_alias_reservation"]["target"] == stale_target
    available.add("codex")
    root_meta, marker, captured = _redeem(artifacts_dir, "do the work")
    _assert_replacement_agrees(
        root_meta,
        marker,
        captured,
        provider=member1[0],
        model=member1[1],
        stale_target=stale_target,
    )


def test_injected_stale_claude_reservation_is_replaced_under_live_soft_context(
    tmp_path: Path,
) -> None:
    member0 = frozen_selector_provider_model_effort(_POOL_ALIAS, 0)
    member1 = frozen_selector_provider_model_effort(_POOL_ALIAS, 1)
    stale_target = f"{member0[0]}/{member0[1]}"
    artifacts_dir, first_meta = _bootstrap(tmp_path, "injected", "do the work")
    reservation = dict(first_meta["model_alias_reservation"])
    reservation["target"] = stale_target
    reservation["redeemed"] = False
    from sase.axe.run_agent_helpers import update_meta_fields

    update_meta_fields(
        artifacts_dir,
        {
            "model": member0[1],
            "llm_provider": member0[0],
            "model_alias_reservation": reservation,
        },
    )
    disable_provider("claude", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    root_meta, marker, captured = _redeem(artifacts_dir, "do the work")
    _assert_replacement_agrees(
        root_meta,
        marker,
        captured,
        provider=member1[0],
        model=member1[1],
        stale_target=stale_target,
    )


def _shipped_selector_member(alias: str, index: int) -> tuple[str, str, str | None]:
    from sase.llm_provider.load_balancing import (
        concatenated_selector_members,
        parse_model_alias_selector,
    )
    from sase.llm_provider.model_alias_policy import implicit_alias_targets
    from sase.xprompt.effort import split_model_effort

    selector = parse_model_alias_selector(implicit_alias_targets()[alias])
    assert selector is not None
    target, effort = split_model_effort(concatenated_selector_members(selector)[index])
    provider, model = target.split("/", 1)
    return provider, model, effort


def test_healthy_tail_does_not_invalidate_all_soft_primary_reservation(
    tmp_path: Path,
    real_model_alias_defaults: None,
) -> None:
    member0 = _shipped_selector_member(XLARGE_MODEL_ALIAS_NAME, 0)
    artifacts_dir, first_meta = _bootstrap(
        tmp_path, "tail", "%model:@xlarge\ndo the work"
    )
    stale_target = f"{member0[0]}/{member0[1]}"
    assert first_meta["model_alias_reservation"]["target"] == stale_target
    cursor_before = json.loads(
        (Path.home() / ".sase" / "llm_lb.json").read_text(encoding="utf-8")
    )["entries"][XLARGE_MODEL_ALIAS_NAME]["cursor"]
    disable_provider("claude", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    disable_provider("codex", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    root_meta, marker, captured = _redeem(artifacts_dir, "%model:@xlarge\ndo the work")
    provider, model = _selected(captured)
    assert (provider, model) == (member0[0], member0[1])
    assert root_meta["model"] == model
    assert root_meta["llm_provider"] == provider
    assert marker["model"] == model
    assert marker["llm_provider"] == provider
    assert root_meta["model_alias_reservation"]["redeemed"] is True
    cursor_after = json.loads(
        (Path.home() / ".sase" / "llm_lb.json").read_text(encoding="utf-8")
    )["entries"][XLARGE_MODEL_ALIAS_NAME]["cursor"]
    assert cursor_after == cursor_before


def test_shipped_large_soft_disable_after_bootstrap_selects_codex_not_tail(
    tmp_path: Path,
    real_model_alias_defaults: None,
) -> None:
    member0 = _shipped_selector_member(LARGE_MODEL_ALIAS_NAME, 0)
    member1 = _shipped_selector_member(LARGE_MODEL_ALIAS_NAME, 1)
    stale_target = f"{member0[0]}/{member0[1]}"
    artifacts_dir, first_meta = _bootstrap(tmp_path, "shipped_large", "do the work")
    assert first_meta["model_alias_reservation"]["target"] == stale_target
    disable_provider("claude", None, source="test", mode=PROVIDER_DISABLE_MODE_SOFT)
    root_meta, marker, captured = _redeem(artifacts_dir, "do the work")
    _assert_replacement_agrees(
        root_meta,
        marker,
        captured,
        provider=member1[0],
        model=member1[1],
        stale_target=stale_target,
    )
