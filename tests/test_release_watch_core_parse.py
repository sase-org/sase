"""Core release PR parsing, reader, and argument tests for the release watcher.

Shared builders live in ``tests._release_watch_helpers``.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests._release_watch_helpers import (
    SHA,
    core_check,
    core_pr,
    run_payload,
    watch,
)

__all__ = [
    "test_core_ci_state_classification",
    "test_core_cut_flag_requires_await_core_version",
    "test_core_release_pr_prefers_latest_entry_per_workflow_check",
    "test_core_release_pr_selection_and_parsing",
    "test_core_release_pr_selection_none_and_ambiguous",
    "test_exit_codes_append_core_ci_red",
    "test_parse_run_reads_event",
    "test_reader_core_signal_is_inactive_unless_awaiting_core",
    "test_reader_reads_core_pr_and_release_plz_runs_while_awaiting",
    "test_reader_validate_checks_core_workflow_only_when_awaiting",
]

RELEASE_BRANCH = "release-plz-2026-10-17T12-30-37Z"


def rollup_entry(
    name: str,
    conclusion: str = "SUCCESS",
    *,
    status: str = "COMPLETED",
    workflow: str = "CI",
    started: str = "2026-10-18T12:44:00Z",
    url: str | None = None,
) -> dict[str, object]:
    return {
        "__typename": "CheckRun",
        "name": name,
        "conclusion": conclusion,
        "status": status,
        "workflowName": workflow,
        "startedAt": started,
        "detailsUrl": url or f"https://github.com/sase-org/sase-core/job/{name}",
    }


def pr_row(
    *,
    number: int = 331,
    title: str = "chore: release v0.42.0",
    branch: str = RELEASE_BRANCH,
    rollup: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "number": number,
        "title": title,
        "headRefName": branch,
        "headRefOid": "E5EBD9613B2517B4E1584024E0E825019B3BF35F",
        "url": f"https://github.com/sase-org/sase-core/pull/{number}",
        "statusCheckRollup": rollup if rollup is not None else [],
    }


def test_exit_codes_append_core_ci_red() -> None:
    assert watch.EXIT_CODES["CORE_CI_RED"] == 19
    assert watch.EXIT_CODES["STOPPED"] == 18
    assert len(set(watch.EXIT_CODES.values())) == len(watch.EXIT_CODES)


def test_core_release_pr_selection_and_parsing() -> None:
    payload = [
        pr_row(number=7, title="feat: unrelated", branch="feature-x"),
        pr_row(
            number=8,
            title="chore: release v0.41.0 extra",
            branch=RELEASE_BRANCH,
        ),
        pr_row(
            rollup=[
                rollup_entry("fmt", "SUCCESS"),
                rollup_entry("macos", "FAILURE"),
                rollup_entry("maturin", "", status="IN_PROGRESS"),
                {
                    "__typename": "StatusContext",
                    "context": "legacy/ci",
                    "state": "PENDING",
                    "targetUrl": "https://ci.example/1",
                },
            ]
        ),
    ]

    parsed = watch.parse_core_release_pr(payload)

    assert parsed is not None
    assert (parsed.number, parsed.version) == (331, "0.42.0")
    assert parsed.head_sha == "e5ebd9613b2517b4e1584024e0e825019b3bf35f"
    assert {check.name: check.status for check in parsed.checks} == {
        "fmt": "success",
        "macos": "failure",
        "maturin": "pending",
        "legacy/ci": "pending",
    }
    assert [(c.name, c.url) for c in parsed.failed_checks] == [
        ("macos", "https://github.com/sase-org/sase-core/job/macos")
    ]
    assert parsed.ci_state == "failing"


def test_core_release_pr_selection_none_and_ambiguous() -> None:
    assert watch.parse_core_release_pr([]) is None
    assert (
        watch.parse_core_release_pr(
            [pr_row(branch="release-plz-nightly"), pr_row(title="chore: release 0.1")]
        )
        is None
    )
    with pytest.raises(ValueError, match="2 open core release PRs: #331, #332"):
        watch.parse_core_release_pr([pr_row(), pr_row(number=332)])
    with pytest.raises(ValueError, match="must be a list"):
        watch.parse_core_release_pr({"not": "a list"})
    bad = pr_row()
    bad["headRefOid"] = ""
    with pytest.raises(ValueError, match="headRefOid"):
        watch.parse_core_release_pr([bad])


def test_core_release_pr_prefers_latest_entry_per_workflow_check() -> None:
    parsed = watch.parse_core_release_pr(
        [
            pr_row(
                rollup=[
                    # An old title run failed, a later edit passed: green.
                    rollup_entry(
                        "title",
                        "FAILURE",
                        workflow="PR Title",
                        started="2026-10-18T12:00:00Z",
                    ),
                    rollup_entry(
                        "title",
                        "SUCCESS",
                        workflow="PR Title",
                        started="2026-10-18T12:10:00Z",
                    ),
                    # A queued re-run outranks the older completed result.
                    rollup_entry("unit", "SUCCESS", started="2026-10-18T12:00:00Z"),
                    rollup_entry(
                        "unit",
                        "",
                        status="QUEUED",
                        started="0001-01-01T00:00:00Z",
                    ),
                    # The same name in another workflow is a separate check.
                    rollup_entry("unit", "SUCCESS", workflow="Other"),
                ]
            )
        ]
    )

    assert parsed is not None
    assert sorted((c.name, c.status) for c in parsed.checks) == [
        ("title", "success"),
        ("unit", "pending"),
        ("unit", "success"),
    ]
    assert parsed.ci_state == "pending"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((), "no_checks"),
        (("success", "skipped", "neutral"), "green"),
        (("success", "pending"), "pending"),
        (("success", "unknown"), "pending"),
        (("failure", "success"), "red"),
        (("cancelled", "timed_out"), "red"),
        (("failure", "pending"), "failing"),
    ],
)
def test_core_ci_state_classification(statuses: tuple[str, ...], expected: str) -> None:
    checks = tuple(core_check(f"c{i}", status) for i, status in enumerate(statuses))

    assert core_pr(*checks).ci_state == expected


def test_parse_run_reads_event() -> None:
    payload = {**run_payload(), "event": "Workflow_Dispatch"}

    assert watch.parse_run(payload, "run").event == "workflow_dispatch"
    assert watch.parse_run(run_payload(), "run").event == ""
    with pytest.raises(ValueError, match="event"):
        watch.parse_run({**run_payload(), "event": 5}, "run")


class RecordingGh:
    def __init__(self, repo: str, answers: dict[tuple[str, ...], object]) -> None:
        self.repo = repo
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def json(self, *args: str) -> object:
        self.calls.append(args)
        return self.answers[args[:2]]

    def text(self, *args: str) -> str:
        self.calls.append(args)
        return ""


def core_reader(
    *, await_core: str | None, answers: dict[tuple[str, ...], object] | None = None
) -> tuple[Any, RecordingGh]:
    core_gh = RecordingGh("sase-org/sase-core", answers or {})
    reader = watch.GithubReader(
        "sase-org/sase",
        "0.18.0",
        SHA,
        RecordingGh("sase-org/sase", {}),
        await_core_version=await_core,
        core_gh=core_gh,  # type: ignore[arg-type]
    )
    return reader, core_gh


def test_reader_reads_core_pr_and_release_plz_runs_while_awaiting() -> None:
    run_rows = [
        {
            **run_payload(run_id=1),
            "event": "schedule",
            "createdAt": "2026-10-14T01:00:00Z",
        },
        {**run_payload(run_id=2), "event": "workflow_dispatch"},
    ]
    reader, core_gh = core_reader(
        await_core="0.42.0",
        answers={
            ("pr", "list"): [pr_row(rollup=[rollup_entry("fmt", "SUCCESS")])],
            ("run", "list"): run_rows,
        },
    )
    reader.get_json = lambda _url, _timeout: {
        "info": {"version": "0.41.0"},
        "releases": {"0.41.0": [{"upload_time_iso_8601": "2026-10-14T09:00:00Z"}]},
    }

    assert reader.read_signal("core_pypi")[0] == "0.41.0"
    state = reader.read_signal("core_pr")

    assert state.active and state.pr is not None
    assert state.pr.ci_state == "green"
    assert [item.run_id for item in state.runs] == [2, 1]
    assert [item.event for item in state.runs] == ["workflow_dispatch", "schedule"]
    pr_call, run_call = core_gh.calls
    assert pr_call[:3] == ("pr", "list", "--state") and "open" in pr_call
    assert "number,title,headRefName,headRefOid,url,statusCheckRollup" in pr_call
    assert run_call[:4] == ("run", "list", "--workflow", "release-plz.yml")
    assert run_call[-1].endswith(",event")


@pytest.mark.parametrize(
    ("await_core", "published"),
    [
        (None, "0.41.0"),
        ("0.42.0", None),
        ("0.42.0", "0.42.0"),
        ("0.42.0", "0.43.1"),
    ],
)
def test_reader_core_signal_is_inactive_unless_awaiting_core(
    await_core: str | None, published: str | None
) -> None:
    reader, core_gh = core_reader(await_core=await_core)
    reader.published_core = published

    state = reader.read_signal("core_pr")

    assert state == watch.CoreReleaseState()
    assert not state.active
    assert core_gh.calls == []


def test_reader_validate_checks_core_workflow_only_when_awaiting() -> None:
    reader, core_gh = core_reader(await_core=None)
    reader.gh.validate = lambda: None  # type: ignore[attr-defined]
    reader.validate()
    assert core_gh.calls == []

    awaiting, awaiting_gh = core_reader(await_core="0.42.0")
    awaiting.gh.validate = lambda: None  # type: ignore[attr-defined]
    awaiting.validate()
    assert awaiting_gh.calls == [("workflow", "view", "release-plz.yml")]


def test_core_cut_flag_requires_await_core_version() -> None:
    argv = ["--fixed-sha", SHA]

    assert watch.parse_args(argv).dispatch_core_cut is False
    options = watch.parse_args([*argv, "-c", "0.42.0", "--dispatch-core-cut"])
    assert options.dispatch_core_cut is True
    with pytest.raises(watch.WatcherError, match="requires --await-core-version"):
        watch.parse_args([*argv, "--dispatch-core-cut"])
