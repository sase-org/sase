"""Anonymous workflow steps inherit the recorded agent model without %model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider.launch_selection import LaunchSelection
from sase.xprompt.directives import PromptDirectives
from sase.xprompt.workflow_executor_steps_prompt_launch import (
    _launch_selection_from_agent_meta,
    resolve_prompt_step_launch_selection,
)


def _write_meta(artifacts_dir: Path, **fields: Any) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(fields, indent=2),
        encoding="utf-8",
    )


def test_agent_meta_supplies_launch_selection_when_prompt_has_no_model(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "successor"
    _write_meta(
        artifacts,
        llm_provider="fakey",
        model="fakey-large",
        reasoning_effort="low",
        model_alias_trail=["large"],
    )

    selection = _launch_selection_from_agent_meta(
        str(artifacts),
        directives=PromptDirectives(),
    )

    assert selection == LaunchSelection(
        provider="fakey",
        model="fakey-large",
        reasoning_effort="low",
        effort_explicit=False,
        alias_trail=("large",),
        cursor_alias=None,
    )


def test_agent_meta_yields_to_explicit_model_directive(tmp_path: Path) -> None:
    artifacts = tmp_path / "successor"
    _write_meta(artifacts, llm_provider="fakey", model="fakey-large")

    selection = _launch_selection_from_agent_meta(
        str(artifacts),
        directives=PromptDirectives(model="fakey-small"),
    )

    assert selection is None


def test_resolve_prompt_step_prefers_agent_meta_over_default_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "successor"
    _write_meta(artifacts, llm_provider="fakey", model="fakey-large")
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.resolve_launch_selection",
        lambda *_args, **_kwargs: LaunchSelection(
            provider="claude",
            model="opus",
            reasoning_effort="xhigh",
            effort_explicit=False,
            alias_origin="default_model",
        ),
    )

    selection = resolve_prompt_step_launch_selection(
        str(artifacts),
        directives=PromptDirectives(),
        provider_disables=None,
    )

    assert selection.provider == "fakey"
    assert selection.model == "fakey-large"


def test_stale_unredeemed_reservation_is_not_inherited_from_agent_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "stale"
    _write_meta(
        artifacts,
        llm_provider="claude",
        model="opus",
        model_alias_reservation={
            "alias": "pool",
            "target": "claude/opus",
            "effort": None,
            "alias_trail": ["pool"],
            "alias_origin": "directive",
            "redeemed": False,
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.launch_selection_from_reservation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.resolve_launch_selection",
        lambda *_args, **_kwargs: LaunchSelection(
            provider="codex",
            model="gpt-5.6-sol",
            reasoning_effort=None,
            effort_explicit=False,
            alias_origin="directive",
        ),
    )

    selection = resolve_prompt_step_launch_selection(
        str(artifacts),
        directives=PromptDirectives(),
        provider_disables=None,
    )

    assert selection.provider == "codex"
    assert selection.model == "gpt-5.6-sol"
