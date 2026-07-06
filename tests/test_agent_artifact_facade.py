import json
import shutil
from pathlib import Path

import pytest

from sase.core.agent_artifact_facade import (
    list_agent_artifacts,
    list_explicit_agent_artifacts,
    list_indexed_agent_artifacts,
    persist_default_agent_artifacts,
    read_explicit_agent_artifact_index,
    store_default_agent_artifact,
    store_explicit_agent_artifact,
    synthesize_default_agent_artifacts,
)
from sase.core.agent_artifact_types import artifact_association_from_dir


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
    video = tmp_path / "demo.mp4"
    pdf = tmp_path / "generated.pdf"
    for path in (chat, plan, alternate_plan, image, video, pdf):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")

    _write_json(
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


def test_store_default_agent_artifact_writes_index_row_with_source_path(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "sdd" / "research" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-bytes")

    stored = store_default_agent_artifact(
        image,
        artifacts_dir,
        artifacts_root=tmp_path / ".sase" / "artifacts",
        workspace_dir=str(workspace),
    )

    assert stored is not None
    assert stored.explicit is False
    assert stored.source_path == str(image)
    assert stored.workspace_dir == str(workspace)
    assert Path(stored.path).is_file()
    assert Path(stored.path).is_relative_to(tmp_path / ".sase" / "artifacts")

    indexed = read_explicit_agent_artifact_index(
        tmp_path / ".sase" / "artifacts" / "index.jsonl"
    )
    assert indexed == [stored]


def test_store_default_agent_artifact_returns_none_for_missing_source(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    result = store_default_agent_artifact(
        tmp_path / "does-not-exist.png",
        artifacts_dir,
        artifacts_root=tmp_path / ".sase" / "artifacts",
    )
    assert result is None
    indexed = read_explicit_agent_artifact_index(
        tmp_path / ".sase" / "artifacts" / "index.jsonl"
    )
    assert indexed == []


def test_persist_default_agent_artifacts_unions_media_paths_and_xprompt(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    diff_image = workspace / "out" / "diff_image.png"
    prompt_image = workspace / "screenshots" / "before.png"
    video = workspace / "renders" / "demo.mp4"
    for path in (diff_image, prompt_image, video):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.suffix.encode())
    (artifacts_dir / "coder_prompt.md").write_text(
        "Use screenshots/before.png and a missing/absent.png\n",
        encoding="utf-8",
    )

    artifacts_root = tmp_path / ".sase" / "artifacts"
    index_path = artifacts_root / "index.jsonl"
    persisted = persist_default_agent_artifacts(
        artifacts_dir,
        image_paths=[str(diff_image), str(workspace / "ghost.png")],
        video_paths=[str(video), str(workspace / "missing.mp4")],
        workspace_dir=str(workspace),
        artifacts_root=artifacts_root,
        index_path=index_path,
    )

    persisted_sources = sorted(a.source_path or "" for a in persisted)
    assert persisted_sources == sorted([str(diff_image), str(prompt_image), str(video)])
    kinds_by_source = {artifact.source_path: artifact.kind for artifact in persisted}
    assert kinds_by_source == {
        str(diff_image): "image",
        str(prompt_image): "image",
        str(video): "file",
    }
    for artifact in persisted:
        assert artifact.explicit is False
        assert Path(artifact.path).is_file()

    # Idempotent: rerun produces same set with no duplicate index rows.
    persist_default_agent_artifacts(
        artifacts_dir,
        image_paths=[str(diff_image)],
        video_paths=[str(video)],
        workspace_dir=str(workspace),
        artifacts_root=artifacts_root,
        index_path=index_path,
    )
    indexed = read_explicit_agent_artifact_index(index_path)
    assert sorted(a.source_path or "" for a in indexed) == sorted(
        [str(diff_image), str(prompt_image), str(video)]
    )


def test_list_agent_artifacts_uses_indexed_media_when_persisted(
    tmp_path: Path,
) -> None:
    """When done.json marks artifacts as persisted, media comes from the
    JSONL index (and survive workspace deletion)."""

    artifacts_dir = _agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "sdd" / "research" / "diagram.png"
    video = workspace / "renders" / "demo.mp4"
    image.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")

    artifacts_root = tmp_path / ".sase" / "artifacts"
    index_path = artifacts_root / "index.jsonl"
    stored_image = store_default_agent_artifact(
        image,
        artifacts_dir,
        kind="image",
        artifacts_root=artifacts_root,
        workspace_dir=str(workspace),
    )
    stored_video = store_default_agent_artifact(
        video,
        artifacts_dir,
        kind="file",
        artifacts_root=artifacts_root,
        workspace_dir=str(workspace),
    )
    assert stored_image is not None
    assert stored_video is not None

    _write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "image_paths": [str(image)],
            "video_paths": [str(video)],
            "default_artifacts_persisted": True,
        },
    )

    # Workspace cleaned up, just like a recycled sase_<N> dir.
    shutil.rmtree(workspace)

    artifacts = list_agent_artifacts(artifacts_dir, index_path=index_path)
    rows_by_source = {
        a.source_path: a for a in artifacts if a.kind in {"image", "file"}
    }
    assert rows_by_source[str(image)].path == stored_image.path
    assert rows_by_source[str(image)].kind == "image"
    assert rows_by_source[str(video)].path == stored_video.path
    assert rows_by_source[str(video)].kind == "file"
    assert Path(rows_by_source[str(image)].path).is_file()
    assert Path(rows_by_source[str(video)].path).is_file()


def test_list_agent_artifacts_falls_back_to_legacy_synthesis_without_marker(
    tmp_path: Path,
) -> None:
    """Legacy agents (no ``default_artifacts_persisted`` marker) still get
    on-the-fly media synthesis from ``done.json``."""

    artifacts_dir = _agent_dir(tmp_path)
    image = tmp_path / "legacy.png"
    video = tmp_path / "legacy.mp4"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")
    _write_json(
        artifacts_dir / "done.json",
        {
            "image_paths": [str(image)],
            "video_paths": [str(video)],
        },
    )

    artifacts = list_agent_artifacts(
        artifacts_dir,
        index_path=tmp_path / ".sase" / "artifacts" / "index.jsonl",
    )
    assert [(a.kind, a.path) for a in artifacts] == [
        ("image", str(image)),
        ("file", str(video)),
    ]


def test_list_indexed_agent_artifacts_returns_explicit_and_default_rows(
    tmp_path: Path,
) -> None:
    artifacts_dir = _agent_dir(tmp_path)
    explicit_source = tmp_path / "explicit.md"
    explicit_source.write_text("explicit", encoding="utf-8")
    default_source = tmp_path / "workspace" / "image.png"
    default_source.parent.mkdir(parents=True)
    default_source.write_bytes(b"png")

    artifacts_root = tmp_path / ".sase" / "artifacts"
    index_path = artifacts_root / "index.jsonl"
    store_explicit_agent_artifact(
        explicit_source,
        artifacts_dir,
        label="Report",
        artifacts_root=artifacts_root,
    )
    store_default_agent_artifact(
        default_source,
        artifacts_dir,
        artifacts_root=artifacts_root,
    )

    indexed = list_indexed_agent_artifacts(artifacts_dir, index_path=index_path)
    explicit = list_explicit_agent_artifacts(artifacts_dir, index_path=index_path)

    assert {a.label for a in indexed} == {"Report", "image.png"}
    assert {a.explicit for a in indexed} == {True, False}
    assert [a.label for a in explicit] == ["Report"]
