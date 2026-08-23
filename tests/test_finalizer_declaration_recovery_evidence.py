"""Unit tests for the declaration-recovery evidence brief."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerObligationWire,
)
from sase.finalizers.declaration import FinalContextPublication
from sase.finalizers.declaration_recovery_evidence import build_recovery_evidence
from sase.finalizers.declaration_store import (
    FINAL_CONTEXT_HOST_FILENAME,
    HostRepositoryRecord,
    write_host_repository_file,
)
from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path

_OBLIGATION_ID = "repo-test1"
_CHANGED_PATH = "src/existing.py"
_NEW_PATH = "src/created.py"


def _publication(
    tmp_path: Path,
    *,
    paths: tuple[str, ...] = (_CHANGED_PATH, _NEW_PATH),
    obligation_id: str = _OBLIGATION_ID,
    display_name: str = "main",
) -> FinalContextPublication:
    context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest="0" * 64,
        obligations=[
            FinalizerObligationWire(
                obligation_id=obligation_id,
                kind="repository",
                display_name=display_name,
                paths=list(paths),
            )
        ],
        context_digest="digest-1",
    )
    return FinalContextPublication(
        payload={},
        context=context,
        path=tmp_path / "final_context.json",
    )


def _write_host(
    artifacts: Path,
    *,
    repo_path: str,
    obligation_id: str = _OBLIGATION_ID,
) -> None:
    write_host_repository_file(
        artifacts / FINAL_CONTEXT_HOST_FILENAME,
        context_digest="digest-1",
        records=(
            HostRepositoryRecord(
                obligation_id=obligation_id,
                kind="main",
                name="main",
                path=repo_path,
            ),
        ),
    )


def _write_baseline(
    artifacts: Path,
    repositories: list[dict[str, object]],
) -> None:
    payload = {"schema_version": 1, "repositories": repositories}
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_baseline_without_repo_labels_paths_new_since_run_start(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    repo = tmp_path / "repo"
    artifacts.mkdir()
    repo.mkdir()
    _write_host(artifacts, repo_path=str(repo))
    _write_baseline(
        artifacts,
        [
            {
                "repo_id": "linked:beads",
                "path": normalize_path(str(tmp_path / "beads")),
                "kind": "linked",
                "name": "beads",
                "scope": "run_start",
                "fingerprints": {"extra.md": ["M", "abc"]},
            }
        ],
    )

    brief = build_recovery_evidence(
        context=_publication(artifacts),
        original_prompt="do the work",
        response_text="I edited the files.",
        artifacts_dir=str(artifacts),
    )

    assert f"- `{_CHANGED_PATH}` — new since run start" in brief
    assert f"- `{_NEW_PATH}` — new since run start" in brief
    assert "this run's own work" in brief
    assert "cannot rule out pre-existing dirt" not in brief


def test_fingerprinted_path_is_changed_others_are_new(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    repo = tmp_path / "repo"
    artifacts.mkdir()
    repo.mkdir()
    _write_host(artifacts, repo_path=str(repo))
    _write_baseline(
        artifacts,
        [
            {
                "repo_id": "main:main",
                "path": normalize_path(str(repo)),
                "kind": "main",
                "name": "main",
                "scope": "run_start",
                "fingerprints": {_CHANGED_PATH: ["M", "abc123"]},
            }
        ],
    )

    brief = build_recovery_evidence(
        context=_publication(artifacts),
        original_prompt="do the work",
        response_text="I edited the files.",
        artifacts_dir=str(artifacts),
    )

    assert f"- `{_CHANGED_PATH}` — changed since run start" in brief
    assert f"- `{_NEW_PATH}` — new since run start" in brief
    assert "this run's own work" in brief


def test_missing_baseline_labels_provenance_unknown_and_hedges(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    repo = tmp_path / "repo"
    artifacts.mkdir()
    repo.mkdir()
    _write_host(artifacts, repo_path=str(repo))

    brief = build_recovery_evidence(
        context=_publication(artifacts),
        original_prompt="do the work",
        response_text="I edited the files.",
        artifacts_dir=str(artifacts),
    )

    assert f"- `{_CHANGED_PATH}` — provenance unknown" in brief
    assert f"- `{_NEW_PATH}` — provenance unknown" in brief
    assert "cannot rule out pre-existing dirt" in brief
    assert "this run's own work" not in brief


def test_oversized_prompt_and_response_are_truncated(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prompt_head = "PROMPT_HEAD_UNIQUE"
    prompt_tail = "PROMPT_TAIL_UNIQUE"
    response_head = "RESPONSE_HEAD_UNIQUE"
    response_tail = "RESPONSE_TAIL_UNIQUE"
    original_prompt = prompt_head + ("p" * 3000) + prompt_tail
    response_text = response_head + ("r" * 5000) + response_tail

    brief = build_recovery_evidence(
        context=_publication(artifacts, paths=()),
        original_prompt=original_prompt,
        response_text=response_text,
        artifacts_dir=str(artifacts),
    )

    prompt_section, _, response_section = brief.partition(
        "## What this run reported doing before it stopped"
    )
    assert prompt_head in prompt_section
    assert prompt_tail not in prompt_section
    assert "truncated; showing" in prompt_section
    assert response_tail in response_section
    assert response_head not in response_section
    assert "truncated; showing" in response_section


def test_response_section_uses_tail_not_head(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    response_text = "HEAD_ONLY_TOKEN" + ("x" * 5000) + "TAIL_ONLY_TOKEN"

    brief = build_recovery_evidence(
        context=_publication(artifacts, paths=()),
        original_prompt=None,
        response_text=response_text,
        artifacts_dir=str(artifacts),
    )

    assert "## What this run reported doing before it stopped" in brief
    assert "TAIL_ONLY_TOKEN" in brief
    assert "HEAD_ONLY_TOKEN" not in brief


def test_malformed_or_absent_tool_calls_drops_written_files_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    publication = _publication(artifacts, paths=())

    absent = build_recovery_evidence(
        context=publication,
        original_prompt=None,
        response_text="",
        artifacts_dir=str(artifacts),
    )
    assert "## Files this run wrote directly" not in absent

    (artifacts / "tool_calls.jsonl").write_text(
        '{not json\n{"event": "ToolUse"}\n',
        encoding="utf-8",
    )
    malformed = build_recovery_evidence(
        context=publication,
        original_prompt=None,
        response_text="",
        artifacts_dir=str(artifacts),
    )
    assert "## Files this run wrote directly" not in malformed


def test_tool_calls_edit_and_write_rows_list_distinct_paths(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    rows = [
        {
            "event": "ToolUse",
            "tool_name": "Edit",
            "tool_input_summary": {"file_path": "src/sase/foo.py"},
        },
        {
            "event": "ToolUse",
            "tool_name": "Write",
            "tool_input_summary": {"file_path": "tests/test_foo.py"},
        },
        {
            "event": "ToolUse",
            "tool_name": "Edit",
            "tool_input_summary": {"file_path": "src/sase/foo.py"},
        },
        {
            "event": "ToolUse",
            "tool_name": "Read",
            "tool_input_summary": {"file_path": "README.md"},
        },
        {
            "event": "ToolResult",
            "tool_name": "Write",
            "tool_input_summary": {"file_path": "ignored.py"},
        },
        {
            "event": "ToolUse",
            "tool_name": "NotebookEdit",
            "tool_input_summary": {"file_path": "notes.ipynb"},
        },
    ]
    (artifacts / "tool_calls.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    brief = build_recovery_evidence(
        context=_publication(artifacts, paths=()),
        original_prompt=None,
        response_text="",
        artifacts_dir=str(artifacts),
    )

    assert "## Files this run wrote directly" in brief
    assert "- `src/sase/foo.py`" in brief
    assert "- `tests/test_foo.py`" in brief
    assert "- `notes.ipynb`" in brief
    assert brief.count("`src/sase/foo.py`") == 1
    assert "README.md" not in brief
    assert "ignored.py" not in brief


def test_unreadable_artifacts_dir_yields_empty_brief(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("nope\n", encoding="utf-8")

    brief = build_recovery_evidence(
        context=_publication(tmp_path),
        original_prompt="do the work",
        response_text="I edited the files.",
        artifacts_dir=str(not_a_dir),
    )

    assert brief == ""
