"""Launch-time prompt-artifact staging coverage."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import subprocess
from types import SimpleNamespace

import sase_core_rs

from sase.core.prompt_artifact_staging import (
    _prune_prompt_artifact_pool,
    capture_prompt_file_ref,
    stage_prompt_artifact,
)


def _rows(workspace: Path) -> list[dict[str, object]]:
    manifest = workspace / ".sase/artifacts/prompt-artifacts.jsonl"
    return list(sase_core_rs.prompt_artifact_manifest_parse(manifest.read_bytes()))


def _stage_in_process(workspace: str, artifacts_dir: str, raw_ref: str) -> None:
    source = Path(workspace) / "source.txt"
    stage_prompt_artifact(
        raw_ref=raw_ref,
        expanded_ref=raw_ref,
        resolved_path=source,
        ref_kind="file",
        label=source.name,
        workspace_root=workspace,
        agent_artifacts_dir=artifacts_dir,
    )


def _stage_file(
    workspace: Path,
    artifacts_dir: Path,
    source: Path,
    *,
    raw_ref: str = "@source.txt",
) -> dict[str, object]:
    record = stage_prompt_artifact(
        raw_ref=raw_ref,
        expanded_ref=raw_ref,
        resolved_path=source,
        ref_kind="file",
        label=source.name,
        workspace_root=workspace,
        agent_artifacts_dir=artifacts_dir,
    )
    assert record is not None
    return dict(record)


def test_same_bytes_produce_one_pool_file_and_two_manifest_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("same bytes", encoding="utf-8")
    artifacts_dir = tmp_path / "run"

    first = _stage_file(tmp_path, artifacts_dir, source, raw_ref="@first")
    second = _stage_file(tmp_path, artifacts_dir, source, raw_ref="@second")

    assert first["pool_relpath"] == second["pool_relpath"]
    assert len(list((tmp_path / ".sase/artifacts/pool").iterdir())) == 1
    assert [row["raw_ref"] for row in _rows(tmp_path)] == ["@first", "@second"]


def test_changed_bytes_at_same_path_produce_distinct_pool_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("first", encoding="utf-8")
    artifacts_dir = tmp_path / "run"
    first = _stage_file(tmp_path, artifacts_dir, source)

    source.write_text("second", encoding="utf-8")
    second = _stage_file(tmp_path, artifacts_dir, source)

    assert first["sha256"] != second["sha256"]
    assert first["pool_relpath"] != second["pool_relpath"]
    assert len(list((tmp_path / ".sase/artifacts/pool").iterdir())) == 2


def test_clean_tracked_file_is_vcs_backed_but_dirty_file_is_pooled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "tracked.txt"
    source.write_text("clean", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    record = SimpleNamespace(name="primary", path=str(repo), clones=())
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.collect_repo_inventory",
        lambda: SimpleNamespace(records=(record,)),
    )
    artifacts_dir = tmp_path / "run"

    clean = _stage_file(repo, artifacts_dir, source)
    source.write_text("dirty", encoding="utf-8")
    dirty = _stage_file(repo, artifacts_dir, source)

    assert clean["vcs_repo"] == "primary"
    assert clean["vcs_relpath"] == "tracked.txt"
    assert clean["pool_relpath"] is None
    assert dirty["vcs_repo"] is None
    assert dirty["pool_relpath"] is not None
    assert len(list((repo / ".sase/artifacts/pool").iterdir())) == 1


def test_oversized_file_is_recorded_without_pool_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(b"large")
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.capture_file_exceeds_size_limit",
        lambda _size: True,
    )

    record = _stage_file(tmp_path, tmp_path / "run", source)

    assert record["skipped_reason"] == "too-large"
    assert record["pool_relpath"] is None
    assert not (tmp_path / ".sase/artifacts/pool").exists()


def test_concurrent_staging_keeps_manifest_well_formed(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("shared", encoding="utf-8")
    artifacts_dir = tmp_path / "run"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_stage_in_process,
            args=(str(tmp_path), str(artifacts_dir), f"@ref-{index}"),
        )
        for index in range(6)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    rows = _rows(tmp_path)
    assert len(rows) == 6
    assert {row["raw_ref"] for row in rows} == {f"@ref-{index}" for index in range(6)}


def test_pool_gc_only_removes_terminal_published_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("published bytes", encoding="utf-8")
    artifacts_dir = tmp_path / "run"
    record = _stage_file(tmp_path, artifacts_dir, source)
    pool_path = tmp_path / ".sase/artifacts" / str(record["pool_relpath"])
    artifacts_dir.mkdir()
    (artifacts_dir / "done.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    (artifacts_dir / "commit_state.json").write_text(
        json.dumps({"completed_steps": ["publish_prompt_archive"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging.get_artifact_capture_pool_max_bytes",
        lambda: 1,
    )

    assert _prune_prompt_artifact_pool(tmp_path) == 1
    assert not pool_path.exists()
    assert len(_rows(tmp_path)) == 1


def test_non_file_reference_records_locator_without_pooling(tmp_path: Path) -> None:
    record = stage_prompt_artifact(
        raw_ref="@bug:sase#42",
        expanded_ref="#42 https://example.test/issues/42",
        resolved_path=None,
        ref_kind="bug",
        label="sase#42",
        locator="sase#42",
        workspace_root=tmp_path,
        agent_artifacts_dir=tmp_path / "run",
    )

    assert record is not None
    assert record["locator"] == "sase#42"
    assert record["pool_relpath"] is None
    assert len(_rows(tmp_path)) == 1


def test_file_ref_capture_writes_captured_copy_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "bob" / "gtd.md"
    source.parent.mkdir()
    source.write_text("original", encoding="utf-8")

    record = capture_prompt_file_ref(
        source=source,
        logical_path="bob:gtd.md",
        root_name="bob",
        authored_path="~/bob/gtd.md",
        raw_ref="@file:~/bob/gtd.md",
        expanded_ref="@file:~/bob/gtd.md",
        workspace_root=tmp_path,
        agent_artifacts_dir=tmp_path / "run",
    )

    assert record is not None
    pool_path = tmp_path / ".sase/artifacts" / str(record["pool_relpath"])
    assert pool_path.read_text(encoding="utf-8") == "original"
    assert record["logical_path"] == "bob:gtd.md"
    assert record["root_name"] == "bob"
    assert record["authored_path"] == "~/bob/gtd.md"
    assert record["origin"] == "ref"
    assert str(record["object_relpath"]).startswith("files/objects/sha256/")
    assert _rows(tmp_path)[0]["sha256"] == record["sha256"]


def test_file_ref_capture_is_stable_after_source_mutation(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("first", encoding="utf-8")

    record = capture_prompt_file_ref(
        source=source,
        logical_path="bob:source.txt",
        root_name="bob",
        authored_path=str(source),
        raw_ref=f"@file:{source}",
        expanded_ref=f"@file:{source}",
        workspace_root=tmp_path,
        agent_artifacts_dir=tmp_path / "run",
    )
    assert record is not None
    pool_path = tmp_path / ".sase/artifacts" / str(record["pool_relpath"])
    source.write_text("second", encoding="utf-8")

    assert pool_path.read_text(encoding="utf-8") == "first"
    assert (
        sase_core_rs.prompt_artifact_manifest_parse(
            (tmp_path / ".sase/artifacts/prompt-artifacts.jsonl").read_bytes()
        )[0]["sha256"]
        == record["sha256"]
    )


def test_file_ref_capture_reuses_pool_for_duplicate_bytes(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")

    first_record = capture_prompt_file_ref(
        source=first,
        logical_path="bob:first.md",
        root_name="bob",
        authored_path=str(first),
        raw_ref=f"@file:{first}",
        expanded_ref=f"@file:{first}",
        workspace_root=tmp_path,
        agent_artifacts_dir=tmp_path / "run",
    )
    second_record = capture_prompt_file_ref(
        source=second,
        logical_path="bob:second.md",
        root_name="bob",
        authored_path=str(second),
        raw_ref=f"@file:{second}",
        expanded_ref=f"@file:{second}",
        workspace_root=tmp_path,
        agent_artifacts_dir=tmp_path / "run",
    )

    assert first_record is not None
    assert second_record is not None
    assert first_record["sha256"] == second_record["sha256"]
    assert len(list((tmp_path / ".sase/artifacts/pool").iterdir())) == 1


def test_file_ref_capture_returns_none_without_artifacts_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    record = capture_prompt_file_ref(
        source=source,
        logical_path="bob:source.txt",
        root_name="bob",
        authored_path=str(source),
        raw_ref=f"@file:{source}",
        expanded_ref=f"@file:{source}",
        workspace_root=tmp_path,
    )

    assert record is None
    assert not (tmp_path / ".sase/artifacts").exists()
