"""Phase 3 unit tests for ``tools/last_workflow_set_status``.

Covers failure diagnostics: job/check-run/annotation parsing, log-tail
aggregation, and the diagnostic blocks rendered by ``main`` in both
human and JSON output. Shared helpers live in
``_last_workflow_set_status_helpers``.
"""

from __future__ import annotations

import json
import types

import pytest

from _last_workflow_set_status_helpers import (
    StubClient,
    install_stub,
    load_script,
    make_annotation,
    make_check_run,
    make_job,
    make_run,
)


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return load_script()


def test_parse_jobs_handles_steps(script: types.ModuleType) -> None:
    payload = {
        "jobs": [
            {
                "databaseId": 7,
                "name": "build",
                "status": "completed",
                "conclusion": "failure",
                "url": "https://example/job/7",
                "steps": [
                    {
                        "name": "Setup",
                        "status": "completed",
                        "conclusion": "success",
                        "number": 1,
                    },
                    {
                        "name": "Test",
                        "status": "completed",
                        "conclusion": "failure",
                        "number": 4,
                    },
                ],
            }
        ]
    }
    jobs = script.parse_jobs(payload)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.name == "build"
    assert not job.passed
    failed_steps = job.failed_steps
    assert len(failed_steps) == 1
    assert failed_steps[0].number == 4
    assert failed_steps[0].name == "Test"


def test_parse_check_runs_skips_invalid(script: types.ModuleType) -> None:
    payload = {
        "check_runs": [
            {"name": "no-id"},
            {
                "id": 99,
                "name": "build",
                "status": "completed",
                "conclusion": "failure",
            },
        ]
    }
    out = script.parse_check_runs(payload)
    assert len(out) == 1
    assert out[0].check_run_id == 99
    assert not out[0].passed
    assert out[0].is_terminal


def test_parse_paginated_check_runs_flattens_pages(
    script: types.ModuleType,
) -> None:
    payload = [
        {
            "check_runs": [
                {
                    "id": 11,
                    "name": "lint",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        {
            "check_runs": [
                {
                    "id": 22,
                    "name": "test",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        },
    ]

    out = script.parse_paginated_check_runs(payload)

    assert [run.check_run_id for run in out] == [11, 22]


def test_parse_annotations_uses_check_run_identity(
    script: types.ModuleType,
) -> None:
    check_run = make_check_run(script, name="build", check_run_id=42)
    payload = [
        {
            "path": "src/x.py",
            "start_line": 10,
            "end_line": 11,
            "annotation_level": "failure",
            "title": "BOOM",
            "message": "exploded",
        }
    ]
    out = script.parse_annotations(payload, check_run=check_run)
    assert len(out) == 1
    assert out[0].check_run_id == 42
    assert out[0].check_run_name == "build"
    assert out[0].path == "src/x.py"


def test_parse_paginated_annotations_flattens_pages(
    script: types.ModuleType,
) -> None:
    check_run = make_check_run(script, name="build", check_run_id=42)
    payload = [
        [
            {
                "path": "src/a.py",
                "start_line": 1,
                "end_line": 1,
                "annotation_level": "failure",
                "title": "A",
                "message": "first page",
            }
        ],
        [
            {
                "path": "src/b.py",
                "start_line": 2,
                "end_line": 2,
                "annotation_level": "failure",
                "title": "B",
                "message": "second page",
            }
        ],
    ]

    out = script.parse_paginated_annotations(payload, check_run=check_run)

    assert [ann.path for ann in out] == ["src/a.py", "src/b.py"]
    assert {ann.check_run_id for ann in out} == {42}


def test_diagnostics_collects_annotations_and_logs_together(
    script: types.ModuleType,
) -> None:
    """Generic annotations must not suppress the log tail.

    Real CI annotations often only say ``Process completed with exit code 1``;
    callers need the failed-log tail too, so the diagnostic carries both.
    """
    failed_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
        workflow_id=10,
    )
    other_run = make_run(
        script,
        workflow="Deploy",
        sha="abc",
        conclusion="success",
        database_id=200,
        workflow_id=20,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run, other_run),
    )
    failing_check_run = make_check_run(
        script, name="build", check_run_id=555, conclusion="failure"
    )
    annotation = make_annotation(
        script,
        check_run=failing_check_run,
        path=".github",
        title="failure",
        message="Process completed with exit code 1.",
    )
    stub = StubClient(
        jobs_by_run={
            100: [
                make_job(script, name="build", conclusion="failure", database_id=1),
            ]
        },
        check_runs_by_sha={"abc": [failing_check_run]},
        annotations_by_check_run={555: [annotation]},
        logs_by_run={100: "line A\nROOT CAUSE: explosion\n"},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_ANNOTATIONS_AND_LOGS
    assert diag.annotations == (annotation,)
    assert diag.log_tail == ("line A", "ROOT CAUSE: explosion")
    # Both endpoints must be hit so generic annotations cannot hide the log.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_annotations_alone_when_log_empty(
    script: types.ModuleType,
) -> None:
    """When the log endpoint returns nothing, annotations stand on their own."""
    failed_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    cr = make_check_run(script, name="build", check_run_id=42, conclusion="failure")
    annotation = make_annotation(script, check_run=cr)
    stub = StubClient(
        jobs_by_run={100: [make_job(script, name="build", conclusion="failure")]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={42: [annotation]},
        logs_by_run={100: ""},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_ANNOTATIONS
    assert diag.annotations == (annotation,)
    assert diag.log_tail == ()
    # Even with annotations present, the log endpoint is attempted exactly once.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_log_fetch_error_degrades_cleanly_with_annotations(
    script: types.ModuleType,
) -> None:
    """If annotations succeed but the log fetch raises, the failure is recorded."""
    failed_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    cr = make_check_run(script, name="build", check_run_id=99, conclusion="failure")
    annotation = make_annotation(script, check_run=cr)
    log_error = script.GhCommandError(
        ["gh", "run", "view", "100", "--log-failed"],
        1,
        "log archive expired",
    )
    stub = StubClient(
        jobs_by_run={100: [make_job(script, name="build", conclusion="failure")]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={99: [annotation]},
        logs_by_run={100: log_error},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_ANNOTATIONS
    assert diag.annotations == (annotation,)
    assert diag.log_tail == ()
    assert "log archive expired" in diag.log_error
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_logs_tailed_to_requested_lines(
    script: types.ModuleType,
) -> None:
    failed_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    log = "\n".join(f"line {i}" for i in range(100))
    stub = StubClient(
        jobs_by_run={100: [make_job(script, name="build", conclusion="failure")]},
        # No matching check-runs → fall back to logs.
        check_runs_by_sha={"abc": []},
        logs_by_run={100: log},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=5)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_LOGS
    assert diag.log_tail == (
        "line 95",
        "line 96",
        "line 97",
        "line 98",
        "line 99",
    )
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_jobs_only_when_logs_empty(
    script: types.ModuleType,
) -> None:
    failed_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    failing_job = make_job(
        script,
        name="build",
        conclusion="failure",
        steps=(
            script.JobStep(
                name="Compile",
                status="completed",
                conclusion="failure",
                number=2,
            ),
        ),
    )
    stub = StubClient(
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: ""},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=20)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_JOBS_ONLY
    assert diag.failed_jobs == (failing_job,)
    assert diag.annotations == ()
    assert diag.log_tail == ()
    # We still attempt the log fetch exactly once, even when annotations
    # are absent and the log turns out to be empty.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_cancelled_run_does_not_retry_log(
    script: types.ModuleType,
) -> None:
    cancelled_run = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="cancelled",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(cancelled_run,),
    )
    log_error = script.GhCommandError(
        ["gh", "run", "view", "100", "--log-failed"],
        1,
        "no logs available for cancelled run",
    )
    stub = StubClient(
        jobs_by_run={100: [make_job(script, name="build", conclusion="cancelled")]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: log_error},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_JOBS_ONLY
    assert diag.log_tail == ()
    assert "cancelled" in diag.log_error
    # Crucially, exactly one log fetch attempt — no retry loop.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_multiple_failed_workflows_reported_independently(
    script: types.ModuleType,
) -> None:
    run_a = make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
        workflow_id=10,
    )
    run_b = make_run(
        script,
        workflow="Lint",
        sha="abc",
        conclusion="failure",
        database_id=200,
        workflow_id=20,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(run_a, run_b),
    )
    cr_a = make_check_run(script, name="build", check_run_id=11, conclusion="failure")
    annotation_a = make_annotation(
        script, check_run=cr_a, path="a.py", title="A failed"
    )
    stub = StubClient(
        jobs_by_run={
            100: [make_job(script, name="build", conclusion="failure")],
            200: [make_job(script, name="ruff", conclusion="failure")],
        },
        # Only run_a has a matching check-run; run_b falls back to logs.
        check_runs_by_sha={"abc": [cr_a]},
        annotations_by_check_run={11: [annotation_a]},
        logs_by_run={200: "tail line 1\ntail line 2\n"},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=5)

    assert len(diagnostics) == 2
    by_run = {d.run.database_id: d for d in diagnostics}
    diag_a = by_run[100]
    diag_b = by_run[200]
    assert diag_a.source == script.DIAG_SOURCE_ANNOTATIONS
    assert diag_a.annotations == (annotation_a,)
    assert diag_b.source == script.DIAG_SOURCE_LOGS
    assert diag_b.log_tail == ("tail line 1", "tail line 2")
    # Both runs now hit the log endpoint so generic annotations on run_a
    # could not hide a real failure tail there either.
    assert stub.fetch_failed_log_calls == [100, 200]


def test_main_failing_set_includes_diagnostics(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
            workflow_id=10,
        ),
        make_run(
            script,
            workflow="Deploy",
            sha="abc",
            conclusion="success",
            database_id=200,
            workflow_id=20,
        ),
    ]
    failing_job = make_job(
        script,
        name="build",
        conclusion="failure",
        steps=(
            script.JobStep(
                name="Test",
                status="completed",
                conclusion="failure",
                number=3,
            ),
        ),
    )
    cr = make_check_run(script, name="build", check_run_id=42, conclusion="failure")
    annotation = make_annotation(script, check_run=cr, path="src/x.py", title="oops")
    stub = StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={42: [annotation]},
    )
    install_stub(script, monkeypatch, stub)

    code = script.main(["--json"])
    assert code == script.EXIT_FAIL
    payload = json.loads(capsys.readouterr().out)
    diags = payload["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["source"] == script.DIAG_SOURCE_ANNOTATIONS
    assert diags[0]["annotations"][0]["path"] == "src/x.py"
    # Only the failed run should have been queried for jobs.
    assert stub.list_jobs_calls == [100]


def test_main_human_output_renders_annotations_and_logs_together(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both annotation and log sections must appear when both are present."""
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
        ),
    ]
    failing_job = make_job(script, name="build", conclusion="failure")
    cr = make_check_run(script, name="build", check_run_id=7, conclusion="failure")
    annotation = make_annotation(
        script,
        check_run=cr,
        path=".github/workflows/ci.yml",
        title="failure",
        message="Process completed with exit code 1.",
    )
    stub = StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={7: [annotation]},
        logs_by_run={100: "noise\nROOT CAUSE: blew up\n"},
    )
    install_stub(script, monkeypatch, stub)

    code = script.main(["--tail", "5"])
    assert code == script.EXIT_FAIL
    out = capsys.readouterr().out
    assert "annotations for failed check-runs" in out
    assert ".github/workflows/ci.yml" in out
    assert "Process completed with exit code 1." in out
    assert "log tail (last" in out
    assert "ROOT CAUSE: blew up" in out


def test_main_json_diagnostics_includes_annotations_and_log_tail(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON output must carry both annotations and the log tail."""
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
        ),
    ]
    failing_job = make_job(script, name="build", conclusion="failure")
    cr = make_check_run(script, name="build", check_run_id=33, conclusion="failure")
    annotation = make_annotation(script, check_run=cr, path="src/x.py", title="oops")
    stub = StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={33: [annotation]},
        logs_by_run={100: "first\nsecond\nthird\n"},
    )
    install_stub(script, monkeypatch, stub)

    code = script.main(["--json", "--tail", "2"])
    assert code == script.EXIT_FAIL
    payload = json.loads(capsys.readouterr().out)
    diags = payload["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["source"] == script.DIAG_SOURCE_ANNOTATIONS_AND_LOGS
    assert diags[0]["annotations"][0]["path"] == "src/x.py"
    assert diags[0]["log_tail"] == ["second", "third"]


def test_main_human_output_renders_diagnostic_block(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
        ),
    ]
    failing_job = make_job(
        script,
        name="build",
        conclusion="failure",
    )
    stub = StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: "alpha\nbeta\ngamma\n"},
    )
    install_stub(script, monkeypatch, stub)

    code = script.main(["--tail", "2"])
    assert code == script.EXIT_FAIL
    out = capsys.readouterr().out
    assert "CI (failure detail)" in out
    assert "job: build" in out
    assert "log tail (last 2 line(s))" in out
    assert "beta" in out and "gamma" in out
    # Tail should have trimmed the earlier line.
    assert "alpha" not in out.split("log tail", 1)[1]
