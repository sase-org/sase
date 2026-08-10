"""Phase 4 (sase-55.4): reasoning-effort metadata persistence + uniform display.

Covers the end-to-end path that surfaces the effective reasoning effort as a
uniform ``Model: PROVIDER(model) @ <effort>`` suffix on the Agents tab:

* persistence into ``agent_meta.json`` and prompt-step markers,
* read-back into the :class:`~sase.ace.tui.models.agent.Agent` model via both the
  filesystem and Rust-backed scan-wire enrichment helpers,
* the uniform ``append_model_field`` suffix rendering, and
* the live Rust scanner projecting the field from real marker files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.tui.model_alias_styles import append_alias_reference
from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.core.agent_scan_wire import AgentMetaWire
from sase.llm_provider.model_label import (
    MODEL_ALIAS_REFERENCE_STYLE,
    model_value_text,
)
from tests._enrich_agent_helpers import make_agent


# --- agent_meta.json persistence -------------------------------------------


def test_agent_meta_persists_explicit_effort(tmp_path: Path) -> None:
    """An explicit ``%effort`` directive lands in ``agent_meta.json``."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%effort:xhigh\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["reasoning_effort"] == "xhigh"


def test_agent_meta_omits_effort_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No directive and no configured default leaves the key out entirely."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    # Pin the config default to "unset" so the test is independent of the
    # developer's ~/.config/sase/sase.yml (which Phase 6 sets to xhigh).
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: None)

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert "reasoning_effort" not in meta
    assert "model_alias" not in meta


def test_agent_meta_uses_config_default_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no directive, ``llm_provider.default_effort`` is persisted."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "high")

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["reasoning_effort"] == "high"


def test_agent_meta_records_model_alias_and_launch_override_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias launches store the typed alias while model follows overrides."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config

    config = {
        "provider": "claude",
        "model_aliases": {"builtin": {"medium_worker": "claude/sonnet"}},
    }
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%m(@medium_worker, medium_worker=codex/gpt-5)\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["model_alias"] == "medium_worker"
    assert (meta["llm_provider"], meta["model"]) == ("codex", "gpt-5")


def test_agent_meta_omits_model_alias_for_concrete_model(
    tmp_path: Path,
) -> None:
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    extract_directives_and_write_meta(
        prompt="%model:claude/opus\ndo the work",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert "model_alias" not in meta


def test_agent_meta_consumes_alias_pool_once_and_resume_reuses_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The axe metadata lane is authoritative and a re-exec does not re-consume."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta
    from sase.llm_provider import config as llm_config

    monkeypatch.setattr(
        llm_config,
        "get_llm_provider_config",
        lambda: {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"pool": "claude/opus@medium | codex/gpt-5.5"}
            },
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        llm_config.get_llm_provider_config,
    )
    monkeypatch.setattr(
        llm_config, "_resolved_target_is_available", lambda _target: True
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    workspace_dir = str(tmp_path / "workspace")
    first_artifacts = str(tmp_path / "first")
    second_artifacts = str(tmp_path / "second")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(first_artifacts, exist_ok=True)
    os.makedirs(second_artifacts, exist_ok=True)

    prompt = "%model:@pool\ndo the work"
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    # Simulate the same runner re-executing after a wait/resume boundary.
    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=first_artifacts,
    )
    first = json.loads(
        (Path(first_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert (first["llm_provider"], first["model"], first["reasoning_effort"]) == (
        "claude",
        "opus",
        "medium",
    )
    assert first["model_alias"] == "pool"

    extract_directives_and_write_meta(
        prompt=prompt,
        workspace_dir=workspace_dir,
        artifacts_dir=second_artifacts,
    )
    second = json.loads(
        (Path(second_artifacts) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert (second["llm_provider"], second["model"]) == ("codex", "gpt-5.5")
    assert second["model_alias"] == "pool"
    assert "reasoning_effort" not in second


# --- prompt-step marker persistence ----------------------------------------


def test_step_marker_persists_and_preserves_effort(tmp_path: Path) -> None:
    """The step marker stores ``reasoning_effort`` and preserves it on rewrite."""
    from sase.xprompt.workflow_executor import WorkflowExecutor
    from sase.xprompt.workflow_models import (
        StepState,
        StepStatus,
        Workflow,
        WorkflowStep,
    )

    step = WorkflowStep(name="s1", agent="do it")
    workflow = Workflow(name="wf", steps=[step])
    executor = WorkflowExecutor(workflow=workflow, args={}, artifacts_dir=str(tmp_path))

    state = StepState(name="s1", status=StepStatus.IN_PROGRESS)
    executor._save_prompt_step_marker(
        "s1",
        state,
        model="opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        model_alias="medium_worker",
    )

    marker_path = tmp_path / "prompt_step_s1.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"
    assert marker["model_alias"] == "medium_worker"

    # A later rewrite that does not re-pass the effort keeps the stored value
    # (mirrors model/llm_provider preservation).
    state.status = StepStatus.COMPLETED
    executor._save_prompt_step_marker("s1", state)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"
    assert marker["model_alias"] == "medium_worker"


# --- Agent read-back (filesystem + scan wire) ------------------------------


def test_enrich_filesystem_reads_effort(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "xhigh",
                "model_alias": "medium_worker",
            }
        ),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.reasoning_effort == "xhigh"
    assert agent.model_alias == "medium_worker"


def test_enrich_wire_reads_effort() -> None:
    agent = make_agent(status="RUNNING")
    meta = AgentMetaWire(
        model="opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        model_alias="medium_worker",
    )

    enrich_agent_from_meta_wire(agent, meta, None)

    assert agent.reasoning_effort == "xhigh"
    assert agent.model_alias == "medium_worker"


def test_enrich_filesystem_without_effort_leaves_none(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"model": "opus", "llm_provider": "claude"}),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.reasoning_effort is None


# --- uniform append_model_field suffix -------------------------------------


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
        append_model_field(text, model, provider, "xhigh", "medium_worker")

        assert text.plain.endswith(" @ xhigh ← @medium_worker\n"), (
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

    value = model_value_text("opus", "claude", "xhigh", "medium_worker")
    assert value is not None

    assert value.plain.endswith("! @ xhigh ← @medium_worker")


def test_model_alias_reference_style_is_shared() -> None:
    model_text = model_value_text("opus", "claude", None, "medium_worker")
    alias_text = Text("CLAUDE(opus)")
    append_alias_reference(alias_text, "medium_worker")
    assert model_text is not None

    model_alias_spans = [
        span
        for span in model_text.spans
        if model_text.plain[span.start : span.end] == "@medium_worker"
    ]
    alias_reference_spans = [
        span
        for span in alias_text.spans
        if alias_text.plain[span.start : span.end] == "@medium_worker"
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


# --- live Rust scanner projection ------------------------------------------


def test_rust_scan_projects_reasoning_effort(tmp_path: Path) -> None:
    """The real Rust scanner projects ``reasoning_effort`` from both markers."""
    from sase.core.agent_scan_facade import scan_agent_artifacts

    artifact_dir = (
        tmp_path / "projects" / "myproj" / "artifacts" / "ace-run" / "20260623120000"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "xhigh",
                "model_alias": "medium_worker",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "completed",
                "cl_name": "c",
                "project_file": "/tmp/myproj.sase",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_s1.json").write_text(
        json.dumps(
            {
                "workflow_name": "wf",
                "step_name": "s1",
                "step_type": "agent",
                "status": "completed",
                "model": "opus",
                "llm_provider": "claude",
                "reasoning_effort": "high",
                "model_alias": "workflow_plan",
            }
        ),
        encoding="utf-8",
    )

    snapshot = scan_agent_artifacts(tmp_path / "projects")

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.reasoning_effort == "xhigh"
    assert record.agent_meta.model_alias == "medium_worker"
    assert record.prompt_steps[0].reasoning_effort == "high"
    assert record.prompt_steps[0].model_alias == "workflow_plan"


# --- `sase agent show` CLI detail panel ------------------------------------


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
    import argparse

    from sase.agent.names._common import NamedAgent
    from sase.agents import cli_show

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
            "model_alias": "medium_worker",
        },
    )

    assert "CLAUDE" in out
    assert "← @medium_worker" in out


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
