"""Regression tests for the unscanned-write guard (phase sase-1tj.2)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sase._repo_inventory_models import RepoCloneRecord, RepoRecord


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(path: Path, tracked_name: str = "tracked.txt") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / tracked_name).write_text("base\n", encoding="utf-8")
    _git("add", tracked_name, cwd=path)
    _git("commit", "-m", "init", cwd=path)
    return path


def _record_from(inventory: object) -> object:
    return inventory


def _fake_record(name: str, own: Path | None, other: Path | None) -> RepoRecord:
    clones: list[RepoCloneRecord] = []
    if own is not None:
        clones.append(RepoCloneRecord(workspace_num=1, path=str(own), exists=True))
    if other is not None:
        clones.append(RepoCloneRecord(workspace_num=0, path=str(other), exists=True))
    return RepoRecord(
        name=name,
        kind="linked",
        project="sase",
        project_key="sase",
        path=str(other or own or ""),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=tuple(clones),
    )


def _primary_record(path: Path, project: str = "sase") -> RepoRecord:
    return RepoRecord(
        name=project,
        kind="primary",
        project=project,
        project_key=f"gh_{project}",
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=(),
    )


def test_unopened_second_checkout_flagged_open_and_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    second = _init_repo(tmp_path / "second")
    stray = second / "202611" / "report.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# stray\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened-research", other=second)

    class _Inventory:
        records = (_primary_record(main), record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray),), include_run_paths=False
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry["checkout"] == str(second.resolve(strict=False))
    assert entry["repo_relative_path"] == os.path.join("202611", "report.md")
    assert entry["status"] == "untracked"
    assert entry["repo_name"] == "research"
    assert entry["action"] == "open_and_move"
    assert "sase repo open research" in str(entry["instruction"])


def test_same_write_not_flagged_once_checkout_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    second = _init_repo(tmp_path / "second")
    stray = second / "report.md"
    stray.write_text("# stray\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase._linked_repo_markers import record_opened_external_repo

    record_opened_external_repo("ext", str(second), reason="test open", opened_at="now")

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened-research", other=second)

    class _Inventory:
        records = (_primary_record(main), record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray),), include_run_paths=False
    )
    assert entries == ()


def test_main_workspace_write_not_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    local = main / "notes.md"
    local.write_text("# local\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(local),), include_run_paths=False
    )
    assert entries == ()


def test_clean_ignored_and_nongit_paths_not_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    second = _init_repo(tmp_path / "second")
    (second / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    _git("add", ".gitignore", cwd=second)
    _git("commit", "-m", "ignore", cwd=second)
    ignored = second / "ignored.log"
    ignored.write_text("x\n", encoding="utf-8")
    clean_tracked = second / "tracked.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    entries = find_unscanned_writes(
        str(main),
        artifacts,
        extra_paths=(str(clean_tracked), str(ignored), str(outside)),
        include_run_paths=False,
    )
    assert entries == ()


def test_nested_unopened_repo_flagged_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    nested = main / "nested"
    _init_repo(nested)
    stray = nested / "scratch.md"
    stray.write_text("# scratch\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase import repo_inventory as inventory_module

    record = _fake_record("nested-repo", own=nested, other=None)

    class _Inventory:
        records = (_primary_record(main), record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray),), include_run_paths=False
    )
    assert len(entries) == 1
    assert entries[0]["action"] == "open"
    assert entries[0]["repo_name"] == "nested-repo"


def test_git_error_drops_candidate_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    missing_parent = tmp_path / "gone" / "file.md"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    entries = find_unscanned_writes(
        str(main),
        artifacts,
        extra_paths=(str(missing_parent),),
        include_run_paths=False,
    )
    assert entries == ()


def test_explicit_artifact_source_flagged_without_tool_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state import _unscanned_writes as mod

    main = _init_repo(tmp_path / "main")
    second = _init_repo(tmp_path / "second")
    stray = second / "report.md"
    stray.write_text("# stray\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    class _Artifact:
        label = "Report"
        source_path = str(stray)
        path = str(artifacts / "snap.md")

    import sase.core.artifact_file_facade as facade

    monkeypatch.setattr(
        facade, "list_explicit_artifact_files", lambda _root: [_Artifact()]
    )

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened-research", other=second)

    class _Inventory:
        records = (_primary_record(main), record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = mod.find_unscanned_writes(str(main), artifacts)
    assert len(entries) == 1
    assert entries[0]["path"] == str(stray)


def test_tool_call_absolute_paths_used_relative_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    second = _init_repo(tmp_path / "second")
    stray = second / "report.md"
    stray.write_text("# stray\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    rows = [
        {
            "event": "ToolUse",
            "tool_name": "Write",
            "tool_input_summary": {"file_path": str(stray)},
        },
        {
            "event": "ToolUse",
            "tool_name": "Write",
            "tool_input_summary": {"file_path": "relative/notes.md"},
        },
    ]
    (artifacts / "tool_calls.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened-research", other=second)

    class _Inventory:
        records = (_primary_record(main), record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(str(main), artifacts)
    assert len(entries) == 1
    assert entries[0]["path"] == str(stray)


def test_final_context_payload_carries_unscanned_writes_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import sase.finalizers._declaration_context as ctx

    entry = {
        "path": "/other/report.md",
        "checkout": "/other",
        "repo_relative_path": "report.md",
        "status": "untracked",
        "repo_name": "research",
        "action": "open_and_move",
        "instruction": "Run `sase repo open research`, then move the file.",
    }
    monkeypatch.setattr(ctx, "_unscanned_writes_entries", lambda _root: [entry])
    monkeypatch.setattr(
        ctx, "build_commit_declaration_context", lambda **k: {"rule": "r"}
    )
    monkeypatch.setattr(ctx, "manifest_template", lambda _c: {"template": True})
    monkeypatch.setattr(ctx, "finalizer_wire_to_json_dict", lambda _c: {"wire": True})
    monkeypatch.setattr(ctx, "context_requires_submission", lambda _c: False)
    monkeypatch.setattr(ctx, "now_iso", lambda: "now")

    plan = SimpleNamespace(entries=[])
    context = SimpleNamespace(
        requirements=[], obligations=[], assigned_bead=None, handoff=None
    )
    payload = ctx._context_payload(
        plan,
        context,
        root=tmp_path,
        host_records=(),  # type: ignore[arg-type]
    )
    assert payload["unscanned_writes"] == [entry]
    assert payload["submission_required"] is False
    assert payload["commit_declaration"] == {"rule": "r"}
    assert payload["manifest_template"] == {"template": True}


def test_final_context_unscanned_writes_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers._declaration_context as ctx

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("detector down")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state._unscanned_writes.find_unscanned_writes",
        _boom,
    )
    assert ctx._unscanned_writes_entries(tmp_path) == []


def test_artifact_create_warns_inside_agent_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from sase.artifact_cli.create import handle_create

    second = _init_repo(tmp_path / "second")
    source = second / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_WORKSPACE_DIR", str(tmp_path / "main"))
    (tmp_path / "main").mkdir(exist_ok=True)

    args = argparse.Namespace(
        path=str(source), label="Report", kind=None, move=False, bead=None
    )
    rc = handle_create(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "outside the commit scan" in captured.err


def test_artifact_create_unchanged_outside_agent_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    from sase.artifact_cli.create import handle_create

    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    args = argparse.Namespace(
        path=str(source), label="Report", kind=None, move=False, bead=None
    )
    rc = handle_create(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "SASE_AGENT=1" in captured.err


def test_skill_text_covers_unscanned_writes() -> None:
    from pathlib import Path as _Path

    final = _Path("src/sase/macros/skills/sase_final.md").read_text(encoding="utf-8")
    repo = _Path("src/sase/macros/skills/sase_repo.md").read_text(encoding="utf-8")
    assert "unscanned_writes" in final
    assert "submission_required" in final
    assert "same\nrepo-relative path under the printed path" in repo or (
        "same" in repo and "repo-relative path under the printed path" in repo
    )
