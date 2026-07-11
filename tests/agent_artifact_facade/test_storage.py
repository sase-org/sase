import shutil
from pathlib import Path

from sase.core.agent_artifact_facade import (
    list_agent_artifacts,
    list_explicit_agent_artifacts,
    read_explicit_agent_artifact_index,
    store_default_agent_artifact,
    store_explicit_agent_artifact,
)

from .helpers import agent_dir, write_json


def test_explicit_plan_duplicate_does_not_add_second_plan_row(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    archived_plan = tmp_path / ".sase" / "plans" / "plan.md"
    sdd_plan = tmp_path / "workspace" / "sdd" / "plans" / "202605" / "plan.md"
    explicit_plan = tmp_path / "explicit-plan.md"
    for path in (archived_plan, sdd_plan, explicit_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    write_json(
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
    artifacts_dir = agent_dir(tmp_path)
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
    artifacts_dir = agent_dir(tmp_path)
    explicit_source = tmp_path / "report.md"
    explicit_source.write_text("# Report\n", encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_text("png", encoding="utf-8")
    write_json(
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
    artifacts_dir = agent_dir(tmp_path)
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
    artifacts_dir = agent_dir(tmp_path)
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
    artifacts_dir = agent_dir(tmp_path)
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
