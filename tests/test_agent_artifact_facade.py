import json
import shutil
from pathlib import Path

import pytest

from sase.core.agent_artifact_facade import (
    list_agent_artifacts,
    list_explicit_agent_artifacts,
    read_explicit_agent_artifact_index,
    store_explicit_agent_artifact,
    synthesize_default_agent_artifacts,
)


def _agent_dir(tmp_path: Path) -> Path:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507123456"
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_synthesize_default_artifacts_from_done_and_agent_meta(tmp_path: Path) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    chat = tmp_path / ".sase" / "chats" / "agent.md"
    plan = tmp_path / "plan.md"
    alternate_plan = tmp_path / "sdd_plan.md"
    image = tmp_path / "image.png"
    pdf = tmp_path / "generated.pdf"
    for path in (chat, plan, alternate_plan, image, pdf):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")

    _write_json(
        artifacts_dir / "done.json",
        {
            "response_path": str(chat),
            "plan_path": str(plan),
            "image_paths": [str(image)],
            "markdown_pdf_paths": [str(pdf)],
            "name": "agent-name",
        },
    )
    _write_json(
        artifacts_dir / "agent_meta.json",
        {
            "chat_path": str(tmp_path / "unused-chat.md"),
            "plan_path": str(plan),
            "sdd_plan_path": str(alternate_plan),
        },
    )
    _write_json(artifacts_dir / "plan_path.json", {"plan_path": str(plan)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("chat", str(chat)),
        ("plan", str(plan)),
        ("image", str(image)),
        ("pdf", str(pdf)),
    ]
    assert artifacts[0].agent_name == "agent-name"
    assert artifacts[0].project == "proj"
    assert artifacts[0].raw_timestamp == "20260507123456"


def test_committed_sdd_plan_is_single_default_plan_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    archived_plan = tmp_path / ".sase" / "plans" / "plan.md"
    sdd_plan = workspace / "sdd" / "tales" / "202605" / "plan.md"
    for path in (archived_plan, sdd_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")

    _write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "plan_path": str(archived_plan),
        },
    )
    _write_json(
        artifacts_dir / "agent_meta.json",
        {
            "sdd_plan_path": str(sdd_plan),
            "plan_committed": True,
        },
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("plan", str(sdd_plan))
    ]
    assert artifacts[0].workspace_dir == str(workspace)


def test_agent_meta_chat_path_is_used_when_done_response_is_missing(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    chat = tmp_path / ".sase" / "chats" / "meta-chat.md"
    chat.parent.mkdir(parents=True, exist_ok=True)
    chat.write_text("chat", encoding="utf-8")
    _write_json(artifacts_dir / "agent_meta.json", {"chat_path": str(chat)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("chat", str(chat))
    ]


def test_generated_markdown_pdf_artifact_keeps_pdf_path_and_uses_source_metadata(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    source = workspace / "docs" / "report.md"
    pdf = artifacts_dir / "markdown_pdfs" / "docs__report.md.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("# Report\n", encoding="utf-8")
    pdf.parent.mkdir(parents=True)
    pdf.write_text("pdf", encoding="utf-8")
    _write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "markdown_pdf_paths": [str(pdf)],
        },
    )
    (artifacts_dir / "markdown_pdfs" / "index.json").write_text(
        json.dumps([{"source_path": str(source), "pdf_path": str(pdf)}]),
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [
        (artifact.kind, artifact.label, artifact.path) for artifact in artifacts
    ] == [("pdf", "report.md", str(pdf))]
    assert artifacts[0].source_path == str(source)
    assert artifacts[0].workspace_dir == str(workspace)


def test_prompt_absolute_image_path_is_default_image_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    image = tmp_path / "telegram" / "image.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpg")
    (artifacts_dir / "raw_xprompt.md").write_text(
        f"Please inspect {image} before changing code.\n",
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("image", str(image.resolve()))
    ]
    assert artifacts[0].label == "image.jpg"


def test_prompt_workspace_relative_image_path_uses_workspace_dir(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "screenshots" / "before.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    _write_json(artifacts_dir / "agent_meta.json", {"workspace_dir": str(workspace)})
    (artifacts_dir / "coder_prompt.md").write_text(
        "Use screenshots/before.png as the visual reference.\n",
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("image", str(image.resolve()))
    ]
    assert artifacts[0].workspace_dir == str(workspace)


def test_home_plan_is_skipped_when_matching_workspace_plan_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home_plan = home / ".sase" / "plans" / "approved.md"
    workspace_plan = workspace / "sdd" / "tales" / "approved.md"
    for path in (home_plan, workspace_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    _write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "plan_path": str(home_plan),
        },
    )
    _write_json(artifacts_dir / "agent_meta.json", {"plan_path": str(workspace_plan)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("plan", str(workspace_plan))
    ]


def test_explicit_plan_duplicate_does_not_add_second_plan_row(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    archived_plan = tmp_path / ".sase" / "plans" / "plan.md"
    sdd_plan = tmp_path / "workspace" / "sdd" / "tales" / "202605" / "plan.md"
    explicit_plan = tmp_path / "explicit-plan.md"
    for path in (archived_plan, sdd_plan, explicit_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    _write_json(
        artifacts_dir / "agent_meta.json",
        {
            "plan_path": str(archived_plan),
            "sdd_plan_path": str(sdd_plan),
            "plan_committed": True,
        },
    )
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    store_explicit_agent_artifact(
        explicit_plan,
        artifacts_dir,
        label="Explicit plan",
        kind="plan",
        artifacts_root=tmp_path / ".sase" / "artifacts",
    )
    artifacts = list_agent_artifacts(artifacts_dir, index_path=index_path)

    plans = [artifact for artifact in artifacts if artifact.kind == "plan"]
    assert [
        (artifact.label, artifact.path, artifact.explicit) for artifact in plans
    ] == [("plan.md", str(sdd_plan), False)]


def test_single_explicit_plan_is_kept_without_metadata_plan(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    first_plan = tmp_path / "first.md"
    second_plan = tmp_path / "second.md"
    for path in (first_plan, second_plan):
        path.write_text("# Plan\n", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    store_explicit_agent_artifact(
        first_plan,
        artifacts_dir,
        label="First plan",
        kind="plan",
        artifacts_root=tmp_path / ".sase" / "artifacts",
    )
    store_explicit_agent_artifact(
        second_plan,
        artifacts_dir,
        label="Second plan",
        kind="plan",
        artifacts_root=tmp_path / ".sase" / "artifacts",
    )

    artifacts = list_agent_artifacts(artifacts_dir, index_path=index_path)

    assert [(artifact.kind, artifact.label) for artifact in artifacts] == [
        ("plan", "First plan")
    ]


def test_store_explicit_artifact_creates_index_and_dedupes_display_order(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    explicit_source = tmp_path / "report.md"
    explicit_source.write_text("# Report\n", encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_text("png", encoding="utf-8")
    _write_json(
        artifacts_dir / "done.json",
        {
            "response_path": str(explicit_source),
            "image_paths": [str(image)],
        },
    )

    stored = store_explicit_agent_artifact(
        explicit_source,
        artifacts_dir,
        label="Report",
        artifacts_root=tmp_path / ".sase" / "artifacts",
    )

    indexed = read_explicit_agent_artifact_index(
        tmp_path / ".sase" / "artifacts" / "index.jsonl"
    )
    artifacts = list_agent_artifacts(
        artifacts_dir,
        index_path=tmp_path / ".sase" / "artifacts" / "index.jsonl",
    )

    assert len(indexed) == 1
    assert indexed[0] == stored
    assert Path(stored.path).is_file()
    assert Path(stored.path).is_relative_to(tmp_path / ".sase" / "artifacts")
    assert [(artifact.kind, artifact.label) for artifact in artifacts] == [
        ("chat", "Chat transcript"),
        ("markdown", "Report"),
        ("image", "image.png"),
    ]


def test_explicit_artifact_association_survives_removed_and_restored_run_dir(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    source = tmp_path / "artifact.txt"
    source.write_text("data", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    stored = store_explicit_agent_artifact(
        source,
        artifacts_dir,
        artifacts_root=tmp_path / ".sase" / "artifacts",
        move=True,
    )
    shutil.rmtree(artifacts_dir)

    explicit = list_explicit_agent_artifacts(artifacts_dir, index_path=index_path)

    assert explicit == [stored]
    assert not source.exists()
    assert Path(stored.path).is_file()

    artifacts_dir.mkdir(parents=True)
    revived = list_agent_artifacts(artifacts_dir, index_path=index_path)

    assert revived == [stored]
