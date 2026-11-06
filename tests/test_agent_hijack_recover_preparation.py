"""Production recovery preview and prompt preparation before the CAS."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import preview as preview_module
from sase.agent.hijack import _preview_prompt as prompt_module
from sase.agent.hijack import _preview_recovery as recovery_module
from tests._agent_hijack_recover_helpers import (
    Flow,
    record as make_record,
    spawned,
    write_done,
)


def _artifacts(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text(
        "Finish the task.\n\n```markdown\n#fork:other-agent\n%id(other-agent)\n```\n",
        encoding="utf-8",
    )
    (artifacts / "chat.md").write_text(
        "## Prompt\n\nFinish the task.\n\n## Response\n\nPartial work.\n",
        encoding="utf-8",
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "acme--3", "chat_path": str(artifacts / "chat.md")}),
        encoding="utf-8",
    )
    write_done(artifacts / "done.json")
    record = make_record(
        artifacts,
        model_alias="large",
        model_alias_trail=["large"],
        model_origin="prompt",
    )
    return artifacts, record


def _install_real_preview_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recovery_module,
        "agent_hijack_config",
        lambda: SimpleNamespace(
            escalation_ladder=("@large", "@xlarge"), successor_context="fork"
        ),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_alias_candidates",
        lambda ladder: {
            "@large": ["claude/opus@high"],
            "@xlarge": ["claude/opus@xhigh"],
        },
    )
    monkeypatch.setattr(
        prompt_module,
        "agent_hijack_config",
        lambda: SimpleNamespace(
            escalation_ladder=("@large", "@xlarge"), successor_context="fork"
        ),
    )


def _available_facts(record: dict[str, Any], target: str, mode: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "observed_resolver_pid": record.get("resolver_pid"),
        "resolver_pid_live": True,
        "resolver_identity_matches": True,
        "pinned_available": True,
        "pinned_unavailable_reason": None,
        "current_target": target,
        "provider_disabled": False,
        "model_unavailable": False,
    }


@pytest.mark.parametrize(
    ("action", "expected_target"),
    [
        ("continue", "claude/opus@high"),
        ("escalate", "claude/opus@xhigh"),
    ],
)
def test_real_preview_and_continuation_are_prepared_before_cas(
    action: str,
    expected_target: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, record = _artifacts(tmp_path)
    _install_real_preview_inputs(monkeypatch)
    successor_dir = tmp_path / "successor"
    successor_dir.mkdir()
    flow = Flow(monkeypatch, record, successor_dir)
    flow._spawn = spawned(4242, successor_dir)
    deps = flow.deps()

    preview_states: list[str] = []

    def real_preview(current: dict[str, Any]) -> Any:
        preview_states.append(str(current.get("state")))
        return preview_module.hijack_recovery_preview(current)

    deps.preview = real_preview
    real_builder = preview_module.build_hijack_continuation_prompt
    builder_states: list[str] = []

    def real_builder_before_cas(current: dict[str, Any], **kwargs: Any) -> Any:
        builder_states.append(str(current.get("state")))
        assert flow.ledger.events == []
        return real_builder(current, **kwargs)

    deps.build_prompt = real_builder_before_cas
    deps.execution_facts = _available_facts
    result = flow.recover(action=action, deps=deps)

    assert result.kind == "launched"
    assert result.concrete_target == expected_target
    assert flow.spawned_prompt is not None
    assert flow.spawned_prompt.startswith(f"%model:{expected_target}")
    # The example stays literal while the active recovery fork is prepared.
    assert "#fork:other-agent\n%id(other-agent)" in flow.spawned_prompt
    assert builder_states == ["held"]
    assert "resolving" not in preview_states
    assert preview_states and set(preview_states) == {"held"}
    assert flow.ledger.events[:2] == ["begin_resolution", "record_launch"]


def test_continue_edited_prompt_pins_its_effective_model_and_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, record = _artifacts(tmp_path)
    _install_real_preview_inputs(monkeypatch)
    edited = preview_module.build_hijack_continuation_prompt(record).prompt
    edited += "\n\nKeep the existing changes and use the edited model.\n"
    successor_dir = tmp_path / "successor"
    successor_dir.mkdir()
    flow = Flow(monkeypatch, record, successor_dir)
    flow._spawn = spawned(4242, successor_dir)
    deps = flow.deps()
    deps.preview = preview_module.hijack_recovery_preview
    deps.build_prompt = None
    deps.execution_facts = _available_facts

    result = flow.recover(
        action="continue",
        prompt=edited,
        model="sonnet@low",
        deps=deps,
    )

    assert result.kind == "launched"
    assert result.action == "instruct"
    assert result.concrete_target == "claude/sonnet@low"
    assert flow.spawned_prompt is not None
    assert flow.spawned_prompt.startswith("%model:claude/sonnet@low")
    assert result.model_changed is True
    assert result.detail["context_mode"] == "fork"


def test_provider_disabled_at_dispatch_refuses_without_reopening_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts_path, record = _artifacts(tmp_path)
    _install_real_preview_inputs(monkeypatch)
    successor_dir = tmp_path / "successor"
    successor_dir.mkdir()
    flow = Flow(monkeypatch, record, successor_dir)
    flow._spawn = spawned(4242, successor_dir)
    deps = flow.deps()
    deps.preview = preview_module.hijack_recovery_preview
    deps.build_prompt = None

    def availability(current: dict[str, Any], target: str, mode: str) -> dict[str, Any]:
        facts = _available_facts(current, target, mode)
        if mode == "dispatch":
            facts.update(
                pinned_available=False,
                current_target=None,
                provider_disabled=True,
                model_unavailable=False,
                pinned_unavailable_reason="provider disabled after preparation",
            )
        return facts

    deps.execution_facts = availability
    result = flow.recover(deps=deps)

    assert result.kind == "refused"
    assert result.detail["code"] == "provider_disabled"
    assert flow.ledger.current["state"] == "held"
    assert flow.log == []


def test_real_preview_rejects_stale_revision_before_any_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts_path, record = _artifacts(tmp_path)
    _install_real_preview_inputs(monkeypatch)
    flow = Flow(monkeypatch, record, tmp_path / "successor")
    deps = flow.deps()
    deps.preview = preview_module.hijack_recovery_preview
    deps.build_prompt = None
    deps.execution_facts = _available_facts

    result = flow.recover(expected_revision=6, deps=deps)

    assert result.kind == "refused"
    assert result.detail["code"] == "stale_revision"
    assert flow.ledger.events == []
