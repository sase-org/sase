"""Coverage for finalizer declaration-channel context publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.finalizer_wire import FINALIZER_DEFERRAL_REASONS
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_CONTEXT_HOST_FILENAME,
    FINAL_SUBMISSION_HOST_FILENAME,
    load_accepted_host_repositories,
    publish_final_context,
    repository_state_digest,
    submit_final_manifest,
)
from sase.finalizers.declaration_context_evidence import COMMIT_DECLARATION_RULE
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.main.parser import create_parser

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
    write_run_start_baseline,
)


def test_final_parser_registers_context_and_submit() -> None:
    parser = create_parser(only="final")

    context_args = parser.parse_args(["final", "context", "-f", "json"])
    submit_args = parser.parse_args(["final", "submit", "-"])

    assert context_args.command == "final"
    assert context_args.final_subcommand == "context"
    assert context_args.format == "json"
    assert submit_args.final_subcommand == "submit"
    assert submit_args.manifest == "-"


def test_context_publishes_opaque_dirty_repository_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)

    publication = publish_final_context()

    context = publication.payload["context"]
    obligations = context["obligations"]
    assert publication.payload["submission_required"] is True
    assert context["run_id"] == "run-1"
    assert context["agent_id"] == "agent-1"
    assert context["turn_nonce"] == "nonce-1"
    assert context["requirements"][0]["trigger"] == "dirty_repository"
    assert context["requirements"][0]["submission_required"] is True
    assert obligations[0]["obligation_id"].startswith("repo-")
    assert obligations[0]["kind"] == "repository"
    assert obligations[0]["paths"] == ["src/app.py"]
    declaration = publication.payload["commit_declaration"]
    assert declaration["rule"] == COMMIT_DECLARATION_RULE
    assert declaration["default_action"] == "commit"
    assert declaration["deferral"]["reasons"] == list(FINALIZER_DEFERRAL_REASONS)
    assert (
        publication.payload["manifest_template"]["payloads"][0]["payload"]["deferrals"]
        == []
    )
    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_FILENAME).is_file()


def test_context_publishes_bounded_repository_commit_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {
        "src/app.py": ("M", "abc123"),
        "src/run.py": ("M", "run456"),
        "src/protected.py": ("M", "protected789"),
    }
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(tmp_path),
                changed_files=("src/app.py", "src/run.py", "src/protected.py"),
                kind="main",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        fingerprints=fingerprints,
        collect=lambda _root: dirty,
    )
    write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={
            "src/app.py": ("M", "abc123"),
            "src/protected.py": ("M", "protected789"),
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {
            "src/app.py": ("M", "abc123"),
            "src/protected.py": ("M", "protected789"),
        },
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_context_evidence.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: ("src/protected.py",),
    )
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/run.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    publication = publish_final_context()

    evidence = publication.payload["commit_declaration"]["repository_evidence"][0]
    assert evidence["repo_id"] == publication.context.obligations[0].obligation_id
    assert evidence["display_name"] == "main"
    assert evidence["run_written_paths"] == ["src/run.py"]
    assert evidence["already_dirty_at_run_start_paths"] == [
        "src/app.py",
        "src/protected.py",
    ]
    assert evidence["protected_paths"] == ["src/protected.py"]
    paths = {item["path"]: item for item in evidence["paths"]}
    assert paths["src/app.py"]["provenance"] == "already_dirty_at_run_start"
    assert paths["src/run.py"]["provenance"] == "new_since_run_start"
    assert paths["src/run.py"]["written_by_this_run"] is True
    assert paths["src/protected.py"]["protected"] is True
    assert str(tmp_path) not in json.dumps(publication.payload)


def test_context_caps_repository_obligation_paths_but_digests_full_dirty_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tuple(f"tests/snapshots/artifacts_{index:03}.png" for index in range(150))
    fingerprints = {path: ("M", f"digest-{index}") for index, path in enumerate(paths)}
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(tmp_path),
                changed_files=paths,
                kind="main",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        fingerprints=fingerprints,
        collect=lambda _root: dirty,
    )

    publication = publish_final_context()

    obligation = publication.payload["context"]["obligations"][0]
    assert obligation["paths"] == list(paths[:128])
    assert obligation["digest"] == repository_state_digest(
        publication.context.obligations[0].obligation_id,
        dirty.repos[0],
        paths,
    )
    evidence = publication.payload["commit_declaration"]["repository_evidence"][0]
    assert evidence["omitted_path_count"] == 50

    submit_final_manifest(valid_manifest(publication))
    records = load_accepted_host_repositories(tmp_path)
    assert records[0].path_count == len(paths)


def test_context_attributes_direct_write_to_linked_repo_by_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for run 20260825070100: a write into a linked/sidecar repo,
    recorded as an absolute tool-call path, must be attributed to this run
    even though the artifacts root (and `Path.cwd()`) is the primary
    workspace checkout, not the sidecar."""

    sidecar = tmp_path / "sase" / "repos" / "research"
    sidecar.mkdir(parents=True)
    changed_path = "202608/remove_direct_git_plugin_installs.md"
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="research",
                path=str(sidecar),
                changed_files=(changed_path,),
                kind="sdd",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(monkeypatch, tmp_path, collect=lambda _root: dirty)
    monkeypatch.setattr(
        "sase.finalizers.declaration_context_evidence.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: (),
    )
    written_file = sidecar / "202608" / "remove_direct_git_plugin_installs.md"
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Write",
                "tool_input_summary": {"file_path": str(written_file)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    publication = publish_final_context()

    evidence = publication.payload["commit_declaration"]["repository_evidence"][0]
    assert evidence["run_written_paths"] == [changed_path]
    paths = {item["path"]: item for item in evidence["paths"]}
    assert paths[changed_path]["written_by_this_run"] is True
    assert str(tmp_path) not in json.dumps(publication.payload)


def test_context_direct_write_matcher_rejects_sibling_prefix_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path under `<repo>-other/` must not be mistaken for a path under
    `<repo>/` just because the strings share a prefix."""

    repo = tmp_path / "repo"
    sibling = tmp_path / "repo-other"
    repo.mkdir()
    sibling.mkdir()
    changed_path = "src/app.py"
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=(changed_path,),
                kind="main",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(monkeypatch, tmp_path, collect=lambda _root: dirty)
    monkeypatch.setattr(
        "sase.finalizers.declaration_context_evidence.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: (),
    )
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Write",
                "tool_input_summary": {"file_path": str(sibling / changed_path)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    publication = publish_final_context()

    evidence = publication.payload["commit_declaration"]["repository_evidence"][0]
    assert evidence["run_written_paths"] == []
    paths = {item["path"]: item for item in evidence["paths"]}
    assert paths[changed_path]["written_by_this_run"] is False


def test_context_host_snapshot_is_not_model_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    submit_final_manifest(valid_manifest(publication))

    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_HOST_FILENAME).is_file()
    assert (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).is_file()
    records = load_accepted_host_repositories(tmp_path)
    assert records[0].path == str(tmp_path)
    assert records[0].obligation_id == publication.context.obligations[0].obligation_id
