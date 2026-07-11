"""Rendering helper tests for the agent artifact selection modal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.modals.agent_artifacts_modal import _artifact_option_text
from sase.core.agent_artifact_facade import list_agent_artifacts
from tests.ace.tui.modals.agent_artifacts_modal_test_helpers import _artifact


def test_artifact_modal_unmarked_option_text_omits_empty_checkbox() -> None:
    plain = _artifact_option_text("1", _artifact(1), marked=False).plain

    assert "[ ]" not in plain


def test_artifact_modal_marked_option_text_displays_selected_marker() -> None:
    plain = _artifact_option_text("1", _artifact(1), marked=True).plain

    assert "[x]" in plain


def test_artifact_modal_option_text_truncates_long_label_and_path() -> None:
    artifact = _artifact(
        1,
        label="label-" + ("x" * 90),
        path="/tmp/" + "/".join(f"segment-{index:02d}" for index in range(20)),
    )

    plain = _artifact_option_text("1", artifact).plain

    assert "label-" + ("x" * 45) + "..." in plain
    assert "..." in plain
    assert "segment-19" in plain
    assert len(plain.splitlines()[0]) < 90


def test_artifact_modal_option_text_displays_home_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    artifact = _artifact(1, path=str(home / ".sase" / "chats" / "agent.md"))
    monkeypatch.setattr(Path, "home", lambda: home)

    plain = _artifact_option_text("1", artifact).plain

    assert "~/.sase/chats/agent.md" in plain
    assert str(home) not in plain


def test_artifact_modal_option_text_prefers_workspace_relative_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    artifact = _artifact(
        1,
        path=str(workspace / "src" / "report.md"),
        workspace_dir=str(workspace),
    )

    plain = _artifact_option_text("1", artifact).plain

    assert "src/report.md" in plain
    assert str(workspace) not in plain


def test_artifact_modal_displays_committed_plan_workspace_relative_path(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    archived_plan = tmp_path / ".sase" / "plans" / "202605" / "plan.md"
    sdd_plan = workspace / "sdd" / "plans" / "202605" / "plan.md"
    artifacts_dir.mkdir()
    for path in (archived_plan, sdd_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    (artifacts_dir / "done.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "plan_path": str(archived_plan),
                "sdd_plan_path": str(sdd_plan),
                "plan_committed": True,
            }
        ),
        encoding="utf-8",
    )

    artifacts = list_agent_artifacts(artifacts_dir)
    plain = _artifact_option_text("1", artifacts[0]).plain

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("plan", str(sdd_plan))
    ]
    assert "sdd/plans/202605/plan.md" in plain
    assert str(workspace) not in plain
    assert str(archived_plan) not in plain


def test_artifact_modal_option_text_renders_agent_prefix() -> None:
    plain = _artifact_option_text(
        "1",
        _artifact(1, label="proposal.md"),
        agent_label="agent-foo",
    ).plain

    assert "agent-foo" in plain
    assert "·" in plain
    assert "proposal.md" in plain


def test_artifact_modal_option_text_displays_pdf_markdown_source_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "docs__report.md.pdf"
    source = workspace / "docs" / "report.md"
    artifact = _artifact(
        1,
        label="report.md",
        kind="pdf",
        path=str(pdf),
        source_path=str(source),
        workspace_dir=str(workspace),
    )

    plain = _artifact_option_text("1", artifact).plain

    assert "docs/report.md" in plain
    assert "markdown_pdfs" not in plain
