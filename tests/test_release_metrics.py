"""Release metric calculations use fixture histories with known answers."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "_release_metrics.py"


@pytest.fixture
def metrics():
    sys.path.insert(0, str(ROOT / "tools"))
    loader = SourceFileLoader("release_metrics_test_module", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "release_metrics_test_module", SCRIPT, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _time(now: datetime, *, days: int = 0, hours: int = 0) -> str:
    return (now + timedelta(days=days, hours=hours)).isoformat().replace("+00:00", "Z")


def _run(
    sha: str,
    workflow: str,
    *,
    jobs: list[dict[str, object]] | None = None,
    conclusion: str = "success",
) -> dict[str, object]:
    return {
        "sha": sha,
        "workflow": workflow,
        "run_id": sha[:5],
        "attempt": 1,
        "conclusion": conclusion,
        "url": f"https://example.test/{workflow}",
        "jobs": list(jobs or []),
    }


def _inventory() -> dict[str, object]:
    return {
        "checks": [
            {"id": "lint", "workflow": "ci.yml", "job_name": "lint"},
            {
                "id": "test-3.12",
                "workflow": "ci.yml",
                "job_name": "test (3.12)",
            },
            {
                "id": "exercise",
                "workflow": "release.yml",
                "job_name": "exercise",
                "required_legs": list(range(4)),
            },
        ]
    }


def test_release_green_requires_exact_sha_and_every_n1_blocker(metrics) -> None:
    sha = "a" * 40
    jobs = [
        {"name": "lint", "conclusion": "success"},
        {"name": "test (3.12)", "conclusion": "success"},
    ]
    exercise_jobs = [
        {"name": f"exercise (linux, {index})", "conclusion": "success"}
        for index in range(4)
    ]
    result = metrics.assess_release_green(
        sha,
        master_gate_runs=[_run(sha, "master-gate.yml")],
        full_ci_runs=[_run(sha, "full.yml", jobs=jobs)],
        release_runs=[_run(sha, "release.yml", jobs=exercise_jobs)],
        inventory=_inventory(),
    )
    assert result["release_green"] is True

    missing_exercise = metrics.assess_release_green(
        sha,
        master_gate_runs=[_run(sha, "master-gate.yml")],
        full_ci_runs=[_run(sha, "full.yml", jobs=jobs)],
        release_runs=[_run(sha, "release.yml", jobs=exercise_jobs[:-1])],
        inventory=_inventory(),
    )
    assert missing_exercise["release_green"] is False
    assert any(
        job["conclusion"] == "missing_or_red"
        for job in missing_exercise["evidence"]["n1_blocking_jobs"]
    )

    wrong_sha = "b" * 40
    wrong = metrics.assess_release_green(
        sha,
        master_gate_runs=[_run(wrong_sha, "master-gate.yml")],
        full_ci_runs=[_run(wrong_sha, "full.yml", jobs=jobs)],
        release_runs=[_run(wrong_sha, "release.yml", jobs=exercise_jobs)],
        inventory=_inventory(),
    )
    assert wrong["release_green"] is False
    assert wrong["missing"] == ["master_gate", "full_ci", "n1_blocking_jobs"]


def test_all_figures_have_known_fixture_values_and_explicit_denominators(
    metrics,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    start = now - timedelta(days=28)
    sha_a = "a" * 40
    sha_b = "b" * 40
    releases = [
        {
            "version": "1.0.0",
            "confirmed_at": _time(now, days=-20),
            "yanked": True,
            "notes": "",
        },
        {
            "version": "1.1.0",
            "confirmed_at": _time(now, days=-10),
            "yanked": False,
            "notes": "Fixes 1.0.0 and corrects its regression",
        },
    ]
    snapshot = {
        "commits": [
            {
                "sha": sha_a,
                "committed_at": _time(now, days=-22),
                "parents": ["1" * 40],
            },
            {
                "sha": sha_b,
                "committed_at": _time(now, days=-12),
                "parents": [sha_a],
            },
        ],
        "green_by_sha": {
            sha_a: {"release_green": True},
            sha_b: {"release_green": True},
        },
        "release_commits": [
            {
                "published_at": _time(now, days=-20),
                "commits": [
                    {
                        "sha": sha_a,
                        "committed_at": _time(now, days=-22, hours=0),
                    }
                ],
            },
            {
                "published_at": _time(now, days=-10),
                "commits": [
                    {
                        "sha": sha_b,
                        "committed_at": _time(now, days=-12),
                    }
                ],
            },
        ],
        "confirmed_releases": releases,
        "github_releases": [
            {
                "tag": "v1.2.0",
                "created_at": _time(now, days=-5),
                "assets": [{"kind": "abandoned"}],
            }
        ],
        "tags": [
            {
                "name": "v1.3.0",
                "committed_at": _time(now, days=-4),
            }
        ],
        "pypi_sase_files": [
            {"version": "1.0.0", "yanked": True},
            {"version": "1.1.0", "yanked": False},
        ],
        "issues": [
            {
                "family": "INSTALL_BROKEN",
                "title": "INSTALL_BROKEN for 1.0.0",
                "opened_at": _time(now, days=-19),
            }
        ],
        "core_lag_seconds": 3600,
        "core_lag_intervals": 1,
    }
    report = metrics.calculate_metrics(
        snapshot, inventory=_inventory(), now=now, window_days=28
    )
    figures = report["metrics"]
    assert figures["days_since_last_confirmed_release"]["value"] == pytest.approx(10.0)
    assert figures["landing_to_pypi_lead_time"]["p50"] == pytest.approx(48.0)
    assert figures["landing_to_pypi_lead_time"]["p90"] == pytest.approx(48.0)
    assert figures["time_to_release_green"]["target_hours"] == 6
    assert figures["core_lag_hours"]["value"] == pytest.approx(1.0)
    assert figures["burned_versions_per_week"]["value"] == pytest.approx(0.5)
    assert figures["change_fail_rate"]["percent"] == pytest.approx(50.0)
    assert figures["change_fail_rate"]["numerator"] == 1
    for figure in figures.values():
        assert "numerator" in figure
        assert "denominator" in figure
        assert figure["window"]["start"] == start.isoformat().replace("+00:00", "Z")
        assert figure["window"]["end"] == now.isoformat().replace("+00:00", "Z")


def test_empty_samples_render_as_na_instead_of_zero_percent(metrics) -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    report = metrics.calculate_metrics(
        {
            "commits": [],
            "release_commits": [],
            "green_by_sha": {},
            "confirmed_releases": [],
            "github_releases": [],
            "tags": [],
            "pypi_sase_files": [],
            "issues": [],
        },
        inventory=_inventory(),
        now=now,
        window_days=28,
    )
    for name in (
        "days_since_last_confirmed_release",
        "landing_to_pypi_lead_time",
        "time_to_release_green",
        "change_fail_rate",
    ):
        assert report["metrics"][name]["display"] == "n/a (0 of 0)"
    assert report["metrics"]["change_fail_rate"]["percent"] is None
    rendered = metrics.render_markdown(report)
    assert "n/a (0 of 0)" in rendered


def test_core_lag_sums_uncontained_pin_time_and_uses_complete_release_boundary(
    metrics, monkeypatch
) -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    start = now - timedelta(hours=6)
    release_a = start + timedelta(hours=1)
    release_b = start + timedelta(hours=5)

    class Facts:
        def read_commits(self, **_kwargs):
            return []

        def read_ref_sha(self, _ref):
            return "c" * 40

        def read_source_pin(self, sha):
            return "d" * 40 if sha.startswith("d") else "b" * 40

    class Health:
        @staticmethod
        def _core_compare(pin, version):
            del pin
            if version == "0.1.0":
                return "behind"
            if version == "0.2.0":
                return "ahead"
            return "behind"

        @staticmethod
        def _core_workflow_text(_version):
            return "  EXPECTED_DIST_SUFFIXES: |\n    .tar.gz\n"

    def fake_ensure(pin, *, pypi_metadata, **_kwargs):
        versions = set(pypi_metadata["releases"])
        if "0.2.0" in versions:
            return metrics.Pinned("0.2.0", ())
        return metrics.CoreLag(pin, None)

    monkeypatch.setattr(metrics, "ensure_core", fake_ensure)
    core_payload = {
        "releases": {
            "0.1.0": [
                {
                    "filename": "sase_core_rs-0.1.0.tar.gz",
                    "yanked": False,
                }
            ],
            "0.2.0": [
                {
                    "filename": "sase_core_rs-0.2.0.tar.gz",
                    "yanked": False,
                }
            ],
        }
    }
    files = [
        {
            "filename": "sase_core_rs-0.1.0.tar.gz",
            "version": "0.1.0",
            "uploaded_at": release_a.isoformat().replace("+00:00", "Z"),
            "yanked": False,
        },
        {
            "filename": "sase_core_rs-0.2.0.tar.gz",
            "version": "0.2.0",
            "uploaded_at": release_b.isoformat().replace("+00:00", "Z"),
            "yanked": False,
        },
    ]
    seconds, intervals, unverifiable, unverifiable_pins = metrics._core_lag_for_window(
        Facts(),
        Health(),
        start=start,
        end=now,
        core_payload=core_payload,
        core_files=files,
    )
    assert seconds == pytest.approx(5 * 3600)
    assert intervals == 1
    assert unverifiable == []
    assert unverifiable_pins == []


def test_core_lag_treats_legacy_tags_without_completeness_contract_as_unknown(
    metrics,
) -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    start = now - timedelta(days=2)

    class Facts:
        @staticmethod
        def read_commits(**_kwargs):
            return []

        @staticmethod
        def read_ref_sha(_ref):
            return "a" * 40

        @staticmethod
        def read_source_pin(_sha):
            return "b" * 40

    class Health:
        workflow_reads: list[str] = []

        @staticmethod
        def _core_workflow_text(version):
            Health.workflow_reads.append(version)
            return "jobs:\n  release:\n    steps: []\n"

    seconds, intervals, unverifiable, unverifiable_pins = metrics._core_lag_for_window(
        Facts(),
        Health(),
        start=start,
        end=now,
        core_payload={"releases": {"0.1.0": [], "0.2.0": []}},
        core_files=[],
    )
    assert seconds == pytest.approx(timedelta(days=2).total_seconds())
    assert intervals == 1
    assert "0.1.0" in unverifiable or "0.2.0" in unverifiable
    assert Health.workflow_reads
    assert unverifiable_pins == []


def test_core_lag_counts_unreadable_pins_and_reports_them(metrics, monkeypatch) -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    start = now - timedelta(days=1)
    published = start + timedelta(hours=1)

    class Facts:
        @staticmethod
        def read_commits(**_kwargs):
            return []

        @staticmethod
        def read_ref_sha(_ref):
            return "a" * 40

        @staticmethod
        def read_source_pin(_sha):
            return "b" * 40

    class Health:
        @staticmethod
        def _core_workflow_text(_version):
            return "  EXPECTED_DIST_SUFFIXES: |\n    .tar.gz\n"

        @staticmethod
        def _core_compare(_pin, _version):
            raise metrics.CoreEnsureError("unreadable compare")

    monkeypatch.setattr(
        metrics,
        "ensure_core",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            metrics.CoreEnsureError("unreadable compare")
        ),
    )
    seconds, intervals, versions, pins = metrics._core_lag_for_window(
        Facts(),
        Health(),
        start=start,
        end=now,
        core_payload={
            "releases": {
                "0.1.0": [
                    {
                        "filename": "sase_core_rs-0.1.0.tar.gz",
                        "yanked": False,
                    }
                ]
            }
        },
        core_files=[
            {
                "filename": "sase_core_rs-0.1.0.tar.gz",
                "version": "0.1.0",
                "uploaded_at": published.isoformat().replace("+00:00", "Z"),
                "yanked": False,
            }
        ],
    )
    assert seconds == pytest.approx(timedelta(days=1).total_seconds())
    assert intervals == 1
    assert versions == []
    assert pins == [
        {
            "pin": "b" * 40,
            "reason": "unreadable compare",
        }
    ]


def test_pypi_history_requires_timestamps_digests_and_yank_state(metrics) -> None:
    response = {
        "releases": {
            "1.0.0": [
                {
                    "filename": "sase-1.0.0.tar.gz",
                    "digests": {"sha256": "a" * 64},
                    "yanked": False,
                    "upload_time_iso_8601": "2026-10-20T00:00:00Z",
                }
            ]
        }
    }
    rows = metrics.pypi_history(response, "sase")
    assert rows[0]["version"] == "1.0.0"
    invalid = json.loads(json.dumps(response))
    invalid["releases"]["1.0.0"][0].pop("upload_time_iso_8601")
    with pytest.raises(metrics.MetricsError):
        metrics.pypi_history(invalid, "sase")


def test_commit_range_reader_subtracts_base_reachability_without_compare_cap() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from _release_watch_facts import ReleaseFactsReader

    reader = object.__new__(ReleaseFactsReader)

    def read_commits(*, branch, **_kwargs):
        rows = [
            {
                "sha": "a" * 40,
                "committed_at": "2026-10-19T00:00:00Z",
            }
        ]
        if branch == "v1.1.0":
            rows.append(
                {
                    "sha": "b" * 40,
                    "committed_at": "2026-10-20T00:00:00Z",
                }
            )
        return rows

    reader.read_commits = read_commits
    result = reader.read_commits_between_refs(
        "v1.0.0",
        "v1.1.0",
        since="2026-10-01T00:00:00Z",
        until="2026-10-21T00:00:00Z",
    )
    assert result == [{"sha": "b" * 40, "committed_at": "2026-10-20T00:00:00Z"}]


def test_job_reads_retry_transient_github_server_errors(metrics, monkeypatch) -> None:
    class Facts:
        attempts = 0

        @staticmethod
        def read_jobs(_run_id, _attempt):
            from _release_watch_transport import ReleaseTransportError

            Facts.attempts += 1
            if Facts.attempts == 1:
                raise ReleaseTransportError("jobs", "HTTP 502")
            return [{"name": "lint", "conclusion": "success"}]

    monkeypatch.setattr(metrics.time, "sleep", lambda _delay: None)
    rows = [{"sha": "a" * 40, "run_id": "1", "attempt": 1}]
    result = metrics._attach_jobs(rows, {"a" * 40}, Facts())
    assert Facts.attempts == 2
    assert result[0]["jobs"] == [{"name": "lint", "conclusion": "success"}]


def test_tag_history_includes_commit_timestamp_for_burned_version_metric() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from _release_watch_facts import ReleaseFactsReader

    reader = object.__new__(ReleaseFactsReader)
    reader._all_release_records = lambda: []
    reader._tag_refs = lambda: [("v1.0.0", "a" * 40)]
    reader._api = lambda _path: {
        "commit": {"committer": {"date": "2026-10-15T00:00:00Z"}}
    }
    assert reader.read_tags(
        since="2026-10-01T00:00:00Z", until="2026-10-20T00:00:00Z"
    ) == [
        {
            "name": "v1.0.0",
            "peeled_sha": "a" * 40,
            "committed_at": "2026-10-15T00:00:00Z",
            "has_manifest": False,
        }
    ]


def test_metrics_tool_paths_are_present() -> None:
    assert (ROOT / "tools" / "release_metrics").is_file()
    assert (ROOT / "tools" / "_release_metrics.py").is_file()
