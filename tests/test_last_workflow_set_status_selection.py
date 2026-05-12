"""Phase 2 unit tests for ``tools/last_workflow_set_status``.

Covers run parsing, deduplication, SHA grouping, and run-set selection.
Shared helpers live in ``_last_workflow_set_status_helpers``.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from _last_workflow_set_status_helpers import (
    fake_runner,
    load_script,
    make_run,
)


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return load_script()


def test_parse_runs_skips_invalid_entries(script: types.ModuleType) -> None:
    payload = [
        # missing identifying fields
        {"workflowName": "CI"},
        # not a dict
        "junk",
        # valid
        {
            "databaseId": 1,
            "workflowName": "CI",
            "workflowDatabaseId": 100,
            "headSha": "abc",
            "headBranch": "master",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-05-11T10:00:00Z",
            "updatedAt": "2026-05-11T10:01:00Z",
            "event": "push",
            "attempt": 1,
            "displayTitle": "msg",
            "url": "https://example/runs/1",
        },
    ]
    runs = script.parse_runs(payload)
    assert len(runs) == 1
    assert runs[0].workflow_name == "CI"
    assert runs[0].head_sha == "abc"
    assert runs[0].passed
    assert runs[0].is_terminal


def test_parse_runs_rejects_non_array(script: types.ModuleType) -> None:
    with pytest.raises(script.GhJsonError):
        script.parse_runs({"oops": True})


def test_dedup_keeps_highest_attempt(script: types.ModuleType) -> None:
    older = make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        conclusion="failure",
        workflow_id=1,
        database_id=1,
        updated_at="2026-05-11T10:00:00Z",
    )
    rerun = make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=2,
        conclusion="success",
        workflow_id=1,
        database_id=2,
        updated_at="2026-05-11T11:00:00Z",
    )
    deduped = script.dedup_runs([older, rerun])
    assert len(deduped) == 1
    assert deduped[0].attempt == 2
    assert deduped[0].conclusion == "success"


def test_dedup_tiebreaks_on_updated_at(script: types.ModuleType) -> None:
    earlier = make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        workflow_id=1,
        database_id=1,
        updated_at="2026-05-11T09:00:00Z",
    )
    later = make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        workflow_id=1,
        database_id=2,
        updated_at="2026-05-11T11:00:00Z",
    )
    deduped = script.dedup_runs([earlier, later])
    assert len(deduped) == 1
    assert deduped[0].database_id == 2


def test_group_by_sha_newest_first(script: types.ModuleType) -> None:
    older = make_run(
        script,
        workflow="CI",
        sha="old",
        created_at="2026-05-10T00:00:00Z",
        workflow_id=1,
        database_id=1,
    )
    newer = make_run(
        script,
        workflow="CI",
        sha="new",
        created_at="2026-05-11T00:00:00Z",
        workflow_id=1,
        database_id=2,
    )
    groups = script.group_by_sha([older, newer])
    assert [sha for sha, _ in groups] == ["new", "old"]


def test_select_skips_incomplete_groups(script: types.ModuleType) -> None:
    runs = [
        # newest SHA still in progress
        make_run(
            script,
            workflow="CI",
            sha="new",
            created_at="2026-05-11T12:00:00Z",
            status="in_progress",
            conclusion="",
            workflow_id=1,
            database_id=1,
        ),
        # older complete SHA
        make_run(
            script,
            workflow="CI",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=1,
            database_id=2,
        ),
        make_run(
            script,
            workflow="Deploy",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=2,
            database_id=3,
        ),
    ]
    result = script.select_run_set(runs)
    assert result.run_set is not None
    assert result.run_set.head_sha == "old"
    assert result.skipped_incomplete == 1


def test_select_requires_named_workflows(script: types.ModuleType) -> None:
    # Newest SHA has CI but not Deploy → skipped via --require.
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="new",
            created_at="2026-05-11T00:00:00Z",
            workflow_id=1,
            database_id=1,
        ),
        make_run(
            script,
            workflow="CI",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=1,
            database_id=2,
        ),
        make_run(
            script,
            workflow="Deploy",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=2,
            database_id=3,
        ),
    ]
    result = script.select_run_set(runs, require=("CI", "Deploy"))
    assert result.run_set is not None
    assert result.run_set.head_sha == "old"
    assert result.skipped_missing_required == 1


def test_select_returns_none_when_no_complete_set(
    script: types.ModuleType,
) -> None:
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="x",
            status="in_progress",
            conclusion="",
            workflow_id=1,
            database_id=1,
        ),
    ]
    result = script.select_run_set(runs)
    assert result.run_set is None
    assert result.skipped_incomplete == 1


@pytest.mark.parametrize(
    "conclusion,expected_pass",
    [
        ("success", True),
        ("skipped", True),
        ("neutral", True),
        ("failure", False),
        ("cancelled", False),
        ("timed_out", False),
        ("startup_failure", False),
    ],
)
def test_pass_conclusion_classification(
    script: types.ModuleType, conclusion: str, expected_pass: bool
) -> None:
    run = make_run(
        script,
        workflow="CI",
        sha="aaa",
        conclusion=conclusion,
    )
    assert run.passed is expected_pass


def test_list_runs_uses_correct_arguments(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    payload = json.dumps(
        [
            {
                "databaseId": 1,
                "workflowName": "CI",
                "workflowDatabaseId": 10,
                "headSha": "abc",
                "headBranch": "master",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-05-11T00:00:00Z",
                "updatedAt": "2026-05-11T00:00:00Z",
                "event": "push",
                "attempt": 1,
                "displayTitle": "t",
                "url": "https://example",
            }
        ]
    )
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=fake_runner(stdout=payload, capture=capture),
    )
    runs = client.list_runs(branch="master", events=("push",), limit=42)
    assert len(runs) == 1
    argv = capture[0]
    assert "run" in argv and "list" in argv
    assert "--branch" in argv and "master" in argv
    assert "--event" in argv and "push" in argv
    assert "--limit" in argv and "42" in argv
    assert argv[-2:] == ["--repo", "o/r"]


def test_format_human_no_set(script: types.ModuleType) -> None:
    result = script.SelectionResult(
        run_set=None, skipped_incomplete=2, skipped_missing_required=1
    )
    text = script.format_human(result, branch="master")
    assert "No fully-completed" in text
    assert "Skipped 2" in text
    assert "Skipped 1" in text


def test_format_json_run_set_shape(script: types.ModuleType) -> None:
    runs = (
        make_run(script, workflow="CI", sha="abc"),
        make_run(script, workflow="Deploy", sha="abc", conclusion="failure"),
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="t",
        created_at="2026-05-11T00:00:00Z",
        runs=runs,
    )
    result = script.SelectionResult(run_set=run_set)
    payload = json.loads(script.format_json(result, branch="master"))
    assert payload["ok"] is False
    assert payload["run_set"]["head_sha"] == "abc"
    assert {r["workflow_name"] for r in payload["run_set"]["runs"]} == {
        "CI",
        "Deploy",
    }
