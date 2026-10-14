"""Parse, GitHub-reader, and visual-drift tests for the release watcher.

Split from ``tests.test_release_watch``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tests._release_watch_helpers import (
    SHA,
    run,
    run_payload,
    watch,
    watch_api,
)

OTHER_SHA = "b" * 40

__all__ = [
    "OTHER_SHA",
    "test_bad_run_shape_fails_closed_as_parse_error",
    "test_core_version_meets_requires_stable_valid_versions",
    "test_fixed_sha_containment_uses_compare_and_records_failed_jobs",
    "test_gh_client_normalizes_machine_readable_environment",
    "test_mixed_job_log_without_visual_failure_is_not_drift",
    "test_mixed_job_log_fallback_preserves_visual_job_identity",
    "test_parse_args_await_core_version",
    "test_parse_args_rejects_malformed_await_core_version",
    "test_parse_arguments_rejects_bad_fixed_sha",
    "test_parse_run_completed_empty_or_invalid_conclusion_is_malformed",
    "test_parse_run_in_flight_empty_conclusion_is_valid",
    "test_visual_job_log_true_drift_and_test_failure_only",
    "test_visual_report_status_classifies_only_proven_drift",
    "test_visual_report_status_requires_a_complete_executed_line",
]


def test_bad_run_shape_fails_closed_as_parse_error() -> None:
    with pytest.raises(ValueError, match="headSha"):
        watch.parse_run({"databaseId": 1, "status": "completed"}, "run")


def test_fixed_sha_containment_uses_compare_and_records_failed_jobs() -> None:
    class Gh:
        repo = "sase-org/sase"

        def json(self, *args: str) -> object:
            if args[:2] == ("run", "view"):
                return {
                    "jobs": [
                        {
                            "name": "visual-test",
                            "conclusion": "failure",
                            "databaseId": 99,
                        }
                    ]
                }
            if args[0] == "api":
                sha = args[1].rsplit("...", 1)[-1]
                return {"status": "ahead" if sha == OTHER_SHA else "diverged"}
            raise AssertionError(args)

        def text(self, *args: str) -> str:
            if "--job" in args:
                return "SASE_VISUAL_REPORT_STATUS=drift"
            return "PNG snapshot differs from the committed golden"

    reader = watch.GithubReader("sase-org/sase", "0.18.0", SHA, Gh())
    reader._run_list = lambda *_args, **_kwargs: [
        run(
            10, sha=OTHER_SHA, conclusion="failure", jobs=(("visual-test", "failure"),)
        ),
        run(11, sha="c" * 40, conclusion="failure"),
        run(12, sha=SHA, status="in_progress", conclusion=None),
    ]

    selected = reader.full_ci()

    assert {item.run_id for item in selected} == {10, 12}
    failed = next(item for item in selected if item.run_id == 10)
    assert failed.failed_jobs == ("visual-test",)
    assert failed.visual_golden_drift
    assert "PNG snapshot differs" in failed.failed_excerpt


def test_parse_arguments_rejects_bad_fixed_sha() -> None:
    with pytest.raises(watch.WatcherError, match="--fixed-sha"):
        watch.parse_args(["--fixed-sha", "bad"])


def test_visual_report_status_classifies_only_proven_drift() -> None:
    negation = (
        "Visual screenshot check failed with status=failed (not golden drift). "
        "Inspect logs and partial captures; do not accept goldens from this run."
    )
    echo = (
        "printf 'Visual screenshot check failed with status=%s (not golden drift)\\n' "
        "failed\ngolden drift visual snapshot PNG snapshot differs"
    )
    mixed = (
        "lint job: snapshot mismatch in docs\n"
        "visual snapshot heading\n"
        "PNG snapshot differs from the committed golden"
    )
    assert not watch_api._is_visual_golden_drift(negation)
    assert not watch_api._is_visual_golden_drift(echo)
    assert not watch_api._is_visual_golden_drift(mixed)
    assert not watch_api._is_visual_golden_drift("SASE_VISUAL_REPORT_STATUS=failed")
    assert not watch_api._is_visual_golden_drift("SASE_VISUAL_REPORT_STATUS=missing")
    assert not watch_api._is_visual_golden_drift("SASE_VISUAL_REPORT_STATUS=partial")
    assert watch_api._is_visual_golden_drift("SASE_VISUAL_REPORT_STATUS=drift")


def test_visual_report_status_requires_a_complete_executed_line() -> None:
    prefixed = (
        "full / visual-test\tUNKNOWN STEP\t"
        "2026-10-14T19:36:44.6081766Z SASE_VISUAL_REPORT_STATUS=drift"
    )
    assert watch_api._is_visual_golden_drift(
        f"\x1b[36;1m{prefixed}\x1b[0m",
        job_name="full / visual-test",
        allow_unprefixed=False,
    )
    for text in (
        "echo SASE_VISUAL_REPORT_STATUS=drift",
        "printf 'SASE_VISUAL_REPORT_STATUS=drift\\n'",
        "SASE_VISUAL_REPORT_STATUS=drift trailing junk",
        "SASE_VISUAL_REPORT_STATUS=failed",
    ):
        assert not watch_api._is_visual_golden_drift(text)


def test_visual_job_log_true_drift_and_test_failure_only() -> None:
    class Gh:
        repo = "sase-org/sase"

        def __init__(self, marker: str) -> None:
            self.marker = marker

        def json(self, *args: str) -> object:
            if args[:2] == ("run", "view"):
                return {
                    "jobs": [
                        {
                            "name": "visual-test",
                            "conclusion": "failure",
                            "databaseId": 42,
                        },
                        {"name": "tests", "conclusion": "failure", "databaseId": 43},
                    ]
                }
            raise AssertionError(args)

        def text(self, *args: str) -> str:
            if "--job" in args and "42" in args:
                return self.marker
            return (
                "Visual screenshot check failed with status=failed (not golden drift)\n"
                "other job: visual snapshot PNG snapshot differs"
            )

    def classify(marker: str) -> bool:
        reader = watch.GithubReader("sase-org/sase", "0.18.0", SHA, Gh(marker))
        reader._run_list = lambda *_args, **_kwargs: [run(8, conclusion="failure")]
        selected = reader.full_ci()
        assert selected[0].failed_jobs == ("visual-test", "tests")
        return selected[0].visual_golden_drift

    assert classify(
        "visual-test\tUNKNOWN STEP\t"
        "2026-10-14T19:36:44.6081766Z SASE_VISUAL_REPORT_STATUS=drift"
    )
    assert not classify("SASE_VISUAL_REPORT_STATUS=failed\nassertion error")


def test_mixed_job_log_without_visual_failure_is_not_drift() -> None:
    class Gh:
        repo = "sase-org/sase"

        def json(self, *args: str) -> object:
            if args[:2] == ("run", "view"):
                return {
                    "jobs": [
                        {"name": "lint", "conclusion": "failure", "databaseId": 7},
                        {
                            "name": "visual-test",
                            "conclusion": "success",
                            "databaseId": 8,
                        },
                    ]
                }
            raise AssertionError(args)

        def text(self, *args: str) -> str:
            return (
                "SASE_VISUAL_REPORT_STATUS=drift\nvisual snapshot PNG snapshot differs"
            )

    reader = watch.GithubReader("sase-org/sase", "0.18.0", SHA, Gh())
    reader._run_list = lambda *_args, **_kwargs: [run(9, conclusion="failure")]
    selected = reader.full_ci()
    assert selected[0].failed_jobs == ("lint",)
    assert not selected[0].visual_golden_drift


def test_mixed_job_log_fallback_preserves_visual_job_identity() -> None:
    class Gh:
        repo = "sase-org/sase"

        def json(self, *args: str) -> object:
            if args[:2] == ("run", "view"):
                return {
                    "jobs": [
                        {
                            "name": "visual-test",
                            "conclusion": "failure",
                            "databaseId": 42,
                        },
                        {"name": "lint", "conclusion": "failure", "databaseId": 43},
                    ]
                }
            raise AssertionError(args)

        def text(self, *args: str) -> str:
            if "--job" in args:
                raise watch.WatcherError("job log unavailable")
            timestamp = "2026-10-14T19:36:44.6081766Z"
            return (
                f"full / lint\tLint\t{timestamp} "
                "SASE_VISUAL_REPORT_STATUS=drift\n"
                "SASE_VISUAL_REPORT_STATUS=drift"
            )

    reader = watch.GithubReader("sase-org/sase", "0.18.0", SHA, Gh())
    reader._run_list = lambda *_args, **_kwargs: [run(9, conclusion="failure")]
    selected = reader.full_ci()
    assert selected[0].failed_jobs == ("visual-test", "lint")
    assert not selected[0].visual_golden_drift


@pytest.mark.parametrize(
    ("published", "required", "expected"),
    (
        ("0.39.9", "0.40.0", False),
        ("0.40.0", "0.40.0", True),
        ("0.41.0", "0.40.0", True),
        ("0.40.0.post1", "0.40.0", True),
        ("0.41.0+build.2", "0.40.0", True),
        ("0.41.0rc1", "0.40.0", False),
        ("0.41.0.dev1", "0.40.0", False),
        ("0.41.0garbage", "0.40.0", False),
        ("0.40.0rc1", "0.40.0", False),
        ("0.40.0.dev1", "0.40.0", False),
        ("0.40.0garbage", "0.40.0", False),
    ),
)
def test_core_version_meets_requires_stable_valid_versions(
    published: str, required: str, expected: bool
) -> None:
    assert watch_api.core_version_meets(published, required) is expected


def test_gh_client_normalizes_machine_readable_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("CLICOLOR_FORCE", "1"),
        ("FORCE_COLOR", "1"),
        ("GH_FORCE_TTY", "1"),
        ("GH_TOKEN", "test-auth-token"),
    ):
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(watch_api.shutil, "which", lambda _exe: "/usr/bin/gh")
    calls: list[tuple[list[str], float, dict[str, str] | None]] = []

    def runner(
        argv: list[str], *, timeout: float, env: dict[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        effective_env = {**os.environ, **(env or {})}
        calls.append((argv, timeout, env))
        forced_color = (
            any(effective_env.get(name) for name in ("CLICOLOR_FORCE", "FORCE_COLOR"))
            or effective_env.get("GH_FORCE_TTY") != "0"
        )
        stdout = '\x1b[36m{"ok": true}\x1b[0m' if forced_color else '{"ok": true}'
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    client = watch_api.GhClient("sase-org/sase", runner=runner)
    assert client.json("api", "repos/sase-org/sase") == {"ok": True}
    assert client.json("run", "list", "--json", "status") == {"ok": True}

    api_argv, api_timeout, api_env = calls[0]
    assert api_argv == ["/usr/bin/gh", "api", "repos/sase-org/sase"]
    assert api_timeout == watch_api.GH_TIMEOUT
    assert api_env is not None and api_env["GH_REPO"] == "sase-org/sase"
    list_argv, list_timeout, list_env = calls[1]
    assert list_argv[-2:] == ["--repo", "sase-org/sase"]
    assert list_timeout == watch_api.GH_TIMEOUT
    assert list_env is not None
    for env in (api_env, list_env):
        assert env["GH_FORCE_TTY"] == "0"
        assert env["NO_COLOR"] == "1"
        assert env["CLICOLOR_FORCE"] == ""
        assert env["FORCE_COLOR"] == ""
        assert {**os.environ, **env}["GH_TOKEN"] == "test-auth-token"


def test_parse_run_completed_empty_or_invalid_conclusion_is_malformed() -> None:
    with pytest.raises(ValueError, match="conclusion is required"):
        watch.parse_run(run_payload(conclusion=""), "run")
    with pytest.raises(ValueError, match="conclusion is required"):
        watch.parse_run(run_payload(conclusion=None), "run")
    with pytest.raises(ValueError, match="valid terminal conclusion"):
        watch.parse_run(run_payload(conclusion="not-a-conclusion"), "run")


@pytest.mark.parametrize("status", sorted(watch.IN_FLIGHT))
def test_parse_run_in_flight_empty_conclusion_is_valid(status: str) -> None:
    parsed = watch.parse_run(run_payload(status=status, conclusion=""), "run")
    assert parsed.conclusion is None
    assert parsed.is_in_flight


def test_parse_args_await_core_version() -> None:
    opts = watch.parse_args(["--fixed-sha", SHA, "-c", "0.40.0"])
    assert opts.await_core_version == "0.40.0"


def test_parse_args_rejects_malformed_await_core_version() -> None:
    with pytest.raises(watch.WatcherError, match="await-core-version"):
        watch.parse_args(["--fixed-sha", SHA, "--await-core-version", "v0.40"])
    with pytest.raises(watch.WatcherError, match="await-core-version"):
        watch.parse_args(["--fixed-sha", SHA, "-c", "0.40.0rc1"])
