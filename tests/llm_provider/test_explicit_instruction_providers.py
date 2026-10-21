"""Grok and Muse explicit instruction-delivery adapter behavior."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.grok import GrokProvider
from sase.llm_provider.instruction_delivery import (
    ActiveInstructionDelivery,
    ActiveSlot,
    DeliveryPlan,
    SlotPlan,
    bind_instruction_delivery,
    reset_instruction_delivery,
    resolve_delivery_plan,
)
from sase.llm_provider.muse import MuseProvider

_GROK_MARKER = "<!-- sase-instructions bundle=0123456789ab invocation=abc-def -->"
_BUNDLE = f"# SASE Final Declaration\nFull instruction bundle.\n{_GROK_MARKER}\n"


def _active_delivery(
    provider: str,
    plan: DeliveryPlan,
    *,
    text: str | None = None,
) -> ActiveInstructionDelivery:
    return ActiveInstructionDelivery(
        invocation_id=str(uuid4()),
        provider=provider,
        root=ActiveSlot(plan=plan.root, text=text),
        subagent=ActiveSlot(plan=plan.subagent),
    )


@contextmanager
def _with_delivery(delivery: ActiveInstructionDelivery) -> Iterator[None]:
    token = bind_instruction_delivery(delivery)
    try:
        yield
    finally:
        reset_instruction_delivery(token)


def test_grok_explicit_rules_disable_memory_and_record_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROK_MEMORY", "1")
    provider = GrokProvider()
    with override_flags(grok_explicit_instructions=True):
        plan = resolve_delivery_plan(provider)
        assert plan.root.status == "explicit"
        delivery = _active_delivery("grok", plan, text=_BUNDLE)

        with (
            _with_delivery(delivery),
            patch("sase.llm_provider._grok_subprocess.subprocess.Popen") as mock_popen,
            patch(
                "sase.llm_provider._grok_subprocess.stream_and_parse_messages_json_output",
                return_value=("response", "", 0, {}),
            ),
            patch("sase.llm_provider._grok_invocation.provider_timer"),
        ):
            mock_popen.return_value = MagicMock()
            provider.invoke("work", model_tier="large", suppress_output=True)

    command = mock_popen.call_args.args[0]
    assert command[command.index("--rules") + 1] == _BUNDLE
    assert command[command.index("--rules") + 1].count(_GROK_MARKER) == 1
    assert mock_popen.call_args.kwargs["env"]["GROK_MEMORY"] == "0"
    session_id = command[command.index("--session-id") + 1]
    assert delivery.session_ids == [session_id]


def test_grok_disabled_flag_keeps_legacy_rules_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROK_MEMORY", "1")
    provider = GrokProvider()
    with override_flags(grok_explicit_instructions=False):
        plan = resolve_delivery_plan(provider)
        delivery = _active_delivery("grok", plan)
        with (
            _with_delivery(delivery),
            patch(
                "sase.llm_provider._grok_invocation._grok_rules_text",
                return_value="legacy Grok rules",
            ),
            patch("sase.llm_provider._grok_subprocess.subprocess.Popen") as mock_popen,
            patch(
                "sase.llm_provider._grok_subprocess.stream_and_parse_messages_json_output",
                return_value=("response", "", 0, {}),
            ),
            patch("sase.llm_provider._grok_invocation.provider_timer"),
        ):
            mock_popen.return_value = MagicMock()
            provider.invoke("work", model_tier="large", suppress_output=True)

    command = mock_popen.call_args.args[0]
    assert command[command.index("--rules") + 1] == "legacy Grok rules"
    assert "env" not in mock_popen.call_args.kwargs


def test_grok_interrupt_reuses_one_bundle_and_records_each_session() -> None:
    provider = GrokProvider()
    calls: list[tuple[list[str], str, dict[str, object]]] = []

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
        **kwargs: object,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output
        calls.append((args, prompt, kwargs))
        if len(calls) == 1:
            provider._pending_interrupt_message = "include another file"
            return ("first pass", "", -15, {})
        return ("second pass", "", 0, {})

    with override_flags(grok_explicit_instructions=True):
        plan = resolve_delivery_plan(provider)
        delivery = _active_delivery("grok", plan, text=_BUNDLE)
        with (
            _with_delivery(delivery),
            patch.object(GrokProvider, "_run_subprocess", side_effect=_fake_run),
        ):
            provider.invoke("original task", model_tier="large", suppress_output=True)

    assert len(calls) == 2
    rules = [args[args.index("--rules") + 1] for args, _, _ in calls]
    assert rules == [_BUNDLE, _BUNDLE]
    assert all(rule.count(_GROK_MARKER) == 1 for rule in rules)
    session_ids = [args[args.index("--session-id") + 1] for args, _, _ in calls]
    assert delivery.session_ids == session_ids
    assert all(
        kwargs["env_overrides"] == {"GROK_MEMORY": "0"} for _, _, kwargs in calls
    )


def test_grok_oversize_bundle_falls_back_to_legacy_rules() -> None:
    provider = GrokProvider()
    captured: dict[str, object] = {}

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
        **kwargs: object,
    ) -> tuple[str, str, int, dict[str, int]]:
        del prompt, suppress_output
        captured["args"] = args
        captured["kwargs"] = kwargs
        return ("response", "", 0, {})

    with override_flags(grok_explicit_instructions=True):
        plan = resolve_delivery_plan(provider)
        delivery = _active_delivery("grok", plan, text="x" * (120 * 1024 + 1))
        with (
            _with_delivery(delivery),
            patch(
                "sase.llm_provider._grok_invocation._grok_rules_text",
                return_value="legacy after oversize",
            ),
            patch.object(GrokProvider, "_run_subprocess", side_effect=_fake_run),
        ):
            provider.invoke("work", model_tier="large", suppress_output=True)

    args = captured["args"]
    assert isinstance(args, list)
    assert args[args.index("--rules") + 1] == "legacy after oversize"
    assert "env_overrides" not in captured["kwargs"]
    assert delivery.root.plan.status == "inherits_native"
    assert delivery.root.fallback is not None
    assert delivery.root.fallback["reason"] == "oversize"


def test_muse_explicit_prefix_survives_interrupt_and_wait_reconstruction() -> None:
    provider = MuseProvider()
    prompts: list[str] = []
    commands: list[list[str]] = []
    session_ids: list[str] = []

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output
        prompt_file = Path(args[args.index("--prompt-file") + 1])
        prompts.append(prompt_file.read_text(encoding="utf-8"))
        commands.append(args)
        assert session_id is not None
        session_ids.append(session_id)
        if len(prompts) == 1:
            provider._pending_interrupt_message = "add the missing test"
            return ("first pass", "", 0, {})
        if len(prompts) == 2:
            return ("I'll wait for the command to finish.", "", 0, {})
        return ("completed", "", 0, {})

    with override_flags(muse_explicit_instructions=True):
        plan = resolve_delivery_plan(provider)
        assert plan.root.status == "explicit"
        delivery = _active_delivery("muse", plan, text=_BUNDLE)
        with (
            _with_delivery(delivery),
            patch("sase.llm_provider.muse_provider.provider_timer"),
            patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
        ):
            provider.invoke("original task", model_tier="large", suppress_output=True)

    assert len(prompts) == 3
    assert prompts[0] == _BUNDLE + "\n\n--- User Prompt ---\noriginal task"
    assert all(prompt.count(_GROK_MARKER) == 1 for prompt in prompts)
    assert all(prompt.count("SASE Final Declaration") == 1 for prompt in prompts)
    assert all("--trust-workspace" not in args for args in commands)
    assert all("--no-foreign-personal-context" in args for args in commands)
    assert delivery.session_ids == session_ids


def test_muse_disabled_flag_keeps_directive_prefix_and_workspace_trust() -> None:
    provider = MuseProvider()
    with override_flags(muse_explicit_instructions=False):
        plan = resolve_delivery_plan(provider)
        delivery = _active_delivery("muse", plan)
        prompts: list[str] = []
        commands: list[list[str]] = []

        def _fake_run(
            args: list[str],
            suppress_output: bool,
            session_id: str | None = None,
        ) -> tuple[str, str, int, dict[str, int]]:
            del suppress_output, session_id
            prompt_file = Path(args[args.index("--prompt-file") + 1])
            prompts.append(prompt_file.read_text(encoding="utf-8"))
            commands.append(args)
            return ("response", "", 0, {})

        with (
            _with_delivery(delivery),
            patch("sase.llm_provider.muse_provider.provider_timer"),
            patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
        ):
            provider.invoke("original task", model_tier="large", suppress_output=True)

    assert prompts[0].startswith("SASE single-turn instructions for Muse Code")
    assert prompts[0].endswith("\n\n--- User Prompt ---\noriginal task")
    assert "--trust-workspace" in commands[0]
