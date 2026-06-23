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

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.core.agent_scan_wire import AgentMetaWire
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
    )

    marker_path = tmp_path / "prompt_step_s1.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"

    # A later rewrite that does not re-pass the effort keeps the stored value
    # (mirrors model/llm_provider preservation).
    state.status = StepStatus.COMPLETED
    executor._save_prompt_step_marker("s1", state)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["reasoning_effort"] == "xhigh"


# --- Agent read-back (filesystem + scan wire) ------------------------------


def test_enrich_filesystem_reads_effort(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {"model": "opus", "llm_provider": "claude", "reasoning_effort": "xhigh"}
        ),
        encoding="utf-8",
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.reasoning_effort == "xhigh"


def test_enrich_wire_reads_effort() -> None:
    agent = make_agent(status="RUNNING")
    meta = AgentMetaWire(model="opus", llm_provider="claude", reasoning_effort="xhigh")

    enrich_agent_from_meta_wire(agent, meta, None)

    assert agent.reasoning_effort == "xhigh"


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
        ("gpt-5.5", "codex"),
        ("some-model", "agy"),
    ):
        text = Text()
        append_model_field(text, model, provider, "xhigh")
        assert text.plain.endswith(" @ xhigh\n"), (provider, text.plain)
        # The model/provider portion is still rendered ahead of the suffix.
        assert text.plain.startswith("Model: ")


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
            {"model": "opus", "llm_provider": "claude", "reasoning_effort": "xhigh"}
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
            }
        ),
        encoding="utf-8",
    )

    snapshot = scan_agent_artifacts(tmp_path / "projects")

    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.reasoning_effort == "xhigh"
    assert record.prompt_steps[0].reasoning_effort == "high"
