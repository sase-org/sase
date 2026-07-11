from pathlib import Path

import pytest

from sase.core.agent_artifact_facade import synthesize_default_agent_artifacts
from sase.core.agent_artifact_types import artifact_association_from_dir

from .helpers import agent_dir, write_json


def test_synthesize_default_artifacts_from_done_and_agent_meta(tmp_path: Path) -> None:
    artifacts_dir = agent_dir(tmp_path)
    chat = tmp_path / ".sase" / "chats" / "agent.md"
    plan = tmp_path / "plan.md"
    alternate_plan = tmp_path / "sdd_plan.md"
    image = tmp_path / "image.png"
    video = tmp_path / "demo.mp4"
    pdf = tmp_path / "generated.pdf"
    for path in (chat, plan, alternate_plan, image, video, pdf):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")

    write_json(
        artifacts_dir / "done.json",
        {
            "response_path": str(chat),
            "plan_path": str(plan),
            "image_paths": [str(image)],
            "video_paths": [str(video)],
            "markdown_pdf_paths": [str(pdf)],
            "name": "agent-name",
        },
    )
    write_json(
        artifacts_dir / "agent_meta.json",
        {
            "chat_path": str(tmp_path / "unused-chat.md"),
            "plan_path": str(plan),
            "sdd_plan_path": str(alternate_plan),
        },
    )
    write_json(artifacts_dir / "plan_path.json", {"plan_path": str(plan)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("chat", str(chat)),
        ("plan", str(plan)),
        ("image", str(image)),
        ("file", str(video)),
        ("pdf", str(pdf)),
    ]
    assert artifacts[0].agent_name == "agent-name"
    assert artifacts[0].project == "proj"
    assert artifacts[0].raw_timestamp == "20260507123456"


def test_artifact_association_from_dir_parses_sharded_agent_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    artifacts_dir.mkdir(parents=True)

    assoc = artifact_association_from_dir(artifacts_dir, agent_name="agent-one")

    assert assoc.project == "proj"
    assert assoc.workflow == "ace-run"
    assert assoc.raw_timestamp == "20260613120000"
    assert assoc.agent_name == "agent-one"


def test_committed_sdd_plan_is_single_default_plan_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    archived_plan = tmp_path / ".sase" / "plans" / "plan.md"
    sdd_plan = workspace / "sdd" / "plans" / "202605" / "plan.md"
    for path in (archived_plan, sdd_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")

    write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "plan_path": str(archived_plan),
        },
    )
    write_json(
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
    artifacts_dir = agent_dir(tmp_path)
    chat = tmp_path / ".sase" / "chats" / "meta-chat.md"
    chat.parent.mkdir(parents=True, exist_ok=True)
    chat.write_text("chat", encoding="utf-8")
    write_json(artifacts_dir / "agent_meta.json", {"chat_path": str(chat)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("chat", str(chat))
    ]


def test_generated_markdown_pdf_artifact_keeps_pdf_path_and_uses_source_metadata(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    source = workspace / "docs" / "report.md"
    pdf = artifacts_dir / "markdown_pdfs" / "docs__report.md.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("# Report\n", encoding="utf-8")
    pdf.parent.mkdir(parents=True)
    pdf.write_text("pdf", encoding="utf-8")
    write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "markdown_pdf_paths": [str(pdf)],
        },
    )
    write_json(
        artifacts_dir / "markdown_pdfs" / "index.json",
        [{"source_path": str(source), "pdf_path": str(pdf)}],
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
    artifacts_dir = agent_dir(tmp_path)
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


def test_prompt_referenced_gif_is_default_image_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "references" / "animation.gif"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"gif")
    write_json(artifacts_dir / "agent_meta.json", {"workspace_dir": str(workspace)})
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Use references/animation.gif as the reference.\n",
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("image", str(image.resolve()))
    ]


def test_prompt_workspace_relative_image_path_uses_workspace_dir(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "screenshots" / "before.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    write_json(artifacts_dir / "agent_meta.json", {"workspace_dir": str(workspace)})
    (artifacts_dir / "coder_prompt.md").write_text(
        "Use screenshots/before.png as the visual reference.\n",
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("image", str(image.resolve()))
    ]
    assert artifacts[0].workspace_dir == str(workspace)


def test_prompt_workspace_relative_video_path_is_default_file_artifact(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    video = workspace / "renders" / "demo.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"webm")
    write_json(artifacts_dir / "agent_meta.json", {"workspace_dir": str(workspace)})
    (artifacts_dir / "coder_prompt.md").write_text(
        "Review renders/demo.webm before editing.\n",
        encoding="utf-8",
    )

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("file", str(video.resolve()))
    ]
    assert artifacts[0].label == "demo.webm"
    assert artifacts[0].workspace_dir == str(workspace)


def test_home_plan_is_skipped_when_matching_workspace_plan_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home_plan = home / ".sase" / "plans" / "approved.md"
    workspace_plan = workspace / "sdd" / "plans" / "approved.md"
    for path in (home_plan, workspace_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "plan_path": str(home_plan),
        },
    )
    write_json(artifacts_dir / "agent_meta.json", {"plan_path": str(workspace_plan)})

    artifacts = synthesize_default_agent_artifacts(artifacts_dir)

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("plan", str(workspace_plan))
    ]
