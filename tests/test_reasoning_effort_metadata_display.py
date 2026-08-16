"""Reasoning-effort metadata display tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.tui.model_alias_styles import append_alias_reference
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.agent.names._common import NamedAgent
from sase.agents import cli_show
from sase.llm_provider.model_label import (
    MODEL_ALIAS_REFERENCE_STYLE,
    model_value_text,
)


def test_append_model_field_suffix_is_uniform_across_providers() -> None:
    """Every provider renders the same trailing ``@ <effort>`` suffix."""
    for model, provider in (
        ("opus", "claude"),
        ("gpt-5.6-sol", "codex"),
        ("some-model", "agy"),
    ):
        text = Text()
        append_model_field(text, model, provider, "xhigh")
        assert text.plain.endswith(" @ xhigh\n"), (provider, text.plain)
        # The model/provider portion is still rendered ahead of the suffix.
        assert text.plain.startswith("Model: ")


def test_append_model_field_alias_chip_is_uniform_across_providers() -> None:
    for model, provider in (
        ("opus", "claude"),
        ("gpt-5.6-sol", "codex"),
        ("some-model", "agy"),
    ):
        text = Text()
        append_model_field(text, model, provider, "xhigh", "medium")

        assert text.plain.endswith(" @ xhigh ← @medium\n"), (
            provider,
            text.plain,
        )


def test_append_model_field_no_alias_chip_without_alias() -> None:
    text = Text()
    append_model_field(text, "opus", "claude", "xhigh")

    assert "← @" not in text.plain


def test_model_alias_chip_follows_advisory_and_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_advisory_for",
        lambda _model: {"severity": "warning"},
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_advisory_marker",
        lambda _severity: "!",
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_advisory_color",
        lambda _severity: "#FFD75F",
    )

    value = model_value_text("opus", "claude", "xhigh", "medium")
    assert value is not None

    assert value.plain.endswith("! @ xhigh ← @medium")


def test_model_alias_reference_style_is_shared() -> None:
    model_text = model_value_text("opus", "claude", None, "medium")
    alias_text = Text("CLAUDE(opus)")
    append_alias_reference(alias_text, "medium")
    assert model_text is not None

    model_alias_spans = [
        span
        for span in model_text.spans
        if model_text.plain[span.start : span.end] == "@medium"
    ]
    alias_reference_spans = [
        span
        for span in alias_text.spans
        if alias_text.plain[span.start : span.end] == "@medium"
    ]
    assert model_alias_spans
    assert alias_reference_spans
    assert str(model_alias_spans[0].style) == MODEL_ALIAS_REFERENCE_STYLE
    assert str(alias_reference_spans[0].style) == MODEL_ALIAS_REFERENCE_STYLE


def test_append_model_field_no_suffix_without_effort() -> None:
    """Omitting the effort keeps the legacy ``Model: PROVIDER(model)`` form."""
    text = Text()
    append_model_field(text, "opus", "claude", None)

    assert " @ " not in text.plain
    assert text.plain.endswith(")\n")


def test_append_model_field_effort_default_arg_is_none() -> None:
    """The new parameter is optional so existing call sites stay valid."""
    text = Text()
    append_model_field(text, "opus", "claude")

    assert " @ " not in text.plain


def test_append_model_field_explicit_provider_skips_model_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit provider metadata is enough to render common model labels."""

    def _unexpected_resolution(model: str) -> tuple[str | None, str]:
        raise AssertionError(model)

    monkeypatch.setattr(
        "sase.llm_provider.registry.resolve_model_provider", _unexpected_resolution
    )

    text = Text()
    append_model_field(text, "gpt-5", "codex")

    assert text.plain == "Model: CODEX(gpt-5)\n"


def test_append_model_field_explicit_provider_resolves_matching_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit-provider labels still honor configured model aliases."""

    def _unexpected_resolution(model: str) -> tuple[str | None, str]:
        raise AssertionError(model)

    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "large": {
                        "model": "codex/gpt-5",
                        "description": "Large model alias.",
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.resolve_model_provider",
        _unexpected_resolution,
    )

    text = Text()
    append_model_field(text, "large", "codex")

    assert text.plain == "Model: CODEX(gpt-5)\n"


def _show_agent_with_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    meta: dict[str, object],
) -> str:
    """Render ``sase agent show`` for an agent whose meta is ``meta``.

    Stubs ``find_named_agent`` so the test exercises only the detail-panel
    display path, not the artifact-scan lookup. Returns captured stdout.
    """
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    agent = NamedAgent(
        name="04m.1",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    def _stub_find(name: str) -> NamedAgent:
        assert name == "04m.1"
        return agent

    monkeypatch.setattr(cli_show, "find_named_agent", _stub_find)
    # Keep the rendered panel on single lines so assertions are wrap-stable.
    monkeypatch.setenv("COLUMNS", "200")

    cli_show.handle_agents_show(argparse.Namespace(name="04m.1"))
    return capsys.readouterr().out


def test_agent_show_cli_renders_effort_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI detail panel renders the uniform ``@ <effort>`` suffix."""
    out = _show_agent_with_meta(
        tmp_path,
        monkeypatch,
        capsys,
        {"model": "opus", "llm_provider": "claude", "reasoning_effort": "xhigh"},
    )

    assert "CLAUDE" in out
    assert "@ xhigh" in out


def test_agent_show_cli_renders_model_alias_chip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show_agent_with_meta(
        tmp_path,
        monkeypatch,
        capsys,
        {
            "model": "opus",
            "llm_provider": "claude",
            "reasoning_effort": "xhigh",
            "model_alias": "medium",
        },
    )

    assert "CLAUDE" in out
    assert "← @medium" in out


def test_agent_show_cli_omits_suffix_without_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no effort recorded the CLI keeps the bare model/provider label."""
    out = _show_agent_with_meta(
        tmp_path,
        monkeypatch,
        capsys,
        {"model": "opus", "llm_provider": "claude"},
    )

    assert "CLAUDE" in out
    assert " @ " not in out
