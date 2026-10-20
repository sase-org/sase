"""Tests for the qualification fact reader (tools/collect_qualification_jobs)."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import load_tool as _load_release_tool
from tests._release_qualification_test_support import _qualification_evidence


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "collect_qualification_jobs"
INVENTORY = ROOT / ".github" / "release-qualification.json"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("collect_qualification_jobs_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "collect_qualification_jobs_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


@pytest.fixture(scope="module")
def release_tool() -> ModuleType:
    return _load_release_tool()


def _manifest() -> dict[str, object]:
    return {
        "repository": "sase-org/sase",
        "candidate_id": "candidate-fact-reader",
        "generation": 1,
        "sha": "b" * 40,
        "core_version": "0.42.0",
    }


def _entries() -> list[dict[str, object]]:
    inventory = json.loads(INVENTORY.read_bytes().decode("utf-8"))
    return [
        entry
        for entry in inventory["checks"]
        if entry["workflow"] == ".github/workflows/ci.yml"
    ]


def _job_row(
    name: str,
    job_id: int,
    *,
    run_id: int = 700,
    run_attempt: int = 1,
    status: str = "completed",
    conclusion: str | None = "success",
    reporting: bool = True,
) -> dict[str, object]:
    steps = [{"name": "setup", "status": "completed", "conclusion": "success"}]
    if reporting:
        steps.extend(
            [
                {
                    "name": "Write qualification evidence",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "Upload qualification evidence",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        )
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "name": f"qualify-ci / {name}",
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/sase-org/sase/actions/runs/{run_id}/job/{job_id}",
        "started_at": "2026-10-19T20:00:00Z",
        "completed_at": "2026-10-19T20:10:00Z",
        "steps": steps,
    }


def _write_pages(path: Path, rows: list[dict[str, object]], *, paginated: bool) -> None:
    page = {"total_count": len(rows), "jobs": rows}
    payload: object = [page] if paginated else page
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_artifacts(
    path: Path, names: list[str], *, expired: set[str] = frozenset()
) -> None:
    rows = [
        {
            "id": 1000 + index,
            "name": name,
            "expired": name in expired,
            "archive_download_url": f"https://api.github.com/artifacts/{name}",
        }
        for index, name in enumerate(names)
    ]
    path.write_text(json.dumps({"total_count": len(rows), "artifacts": rows}))


def _blocking_artifact_names(attempt: int) -> list[str]:
    return [
        f"qualify-evidence-{check_id}-attempt-{attempt}"
        for check_id in ("lint", "test-3.12", "test-3.13", "test-3.14")
    ]


def _write_pass_evidence(
    release_tool: ModuleType,
    manifest: dict[str, object],
    tmp_path: Path,
    *,
    attempt: int,
    run_id: int,
    job_ids: dict[str, int],
    scenario: dict[str, str] | None = None,
) -> None:
    raw = INVENTORY.read_bytes()
    digest = release_tool._qualification.inventory_digest(raw)
    entries = {
        entry["id"]: entry for entry in _entries() if entry["disposition"] == "blocking"
    }
    scenario = scenario or {}
    for check_id, entry in entries.items():
        payload = _qualification_evidence(
            manifest,
            entry,
            digest=digest,
            run_id=run_id,
            job_id=job_ids[check_id],
            attempt=attempt,
            scenario=scenario.get(check_id, "pass"),
        )
        target = tmp_path / f"attempt-{attempt}" / f"qualify-evidence-{check_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")


def _run_collect(
    tool: ModuleType,
    tmp_path: Path,
    *,
    manifest_path: Path,
    jobs: dict[int, list[Path]],
    artifacts: dict[int, list[Path]] | None = None,
    run_id: int = 700,
    extra: list[str] | None = None,
) -> Path:
    argv = [
        "--inventory",
        str(INVENTORY),
        "--manifest",
        str(manifest_path),
        "--run-id",
        str(run_id),
        "--evidence-root",
        str(tmp_path),
        "--out",
        str(tmp_path / "jobs.json"),
    ]
    for attempt, paths in sorted(jobs.items()):
        for path in paths:
            argv.extend(["--attempt-jobs", f"{attempt}={path}"])
    for attempt, paths in sorted((artifacts or {}).items()):
        for path in paths:
            argv.extend(["--attempt-artifacts", f"{attempt}={path}"])
    argv.extend(extra or [])
    assert tool.main(argv) == 0
    return tmp_path / "jobs.json"


def _check_names(bundle: dict[str, object], attempt: int) -> set[str]:
    snapshots = bundle["attempts"]
    assert isinstance(snapshots, list)
    snapshot = next(row for row in snapshots if row["attempt"] == attempt)
    return {str(row["job_name"]) for row in snapshot["jobs"]}


def test_success_single_attempt_evaluates_green(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = _entries()
    job_ids = {str(entry["id"]): 2000 + index for index, entry in enumerate(entries)}
    rows = [
        _job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in entries
    ]
    jobs_path = tmp_path / "jobs-attempt-1.json"
    _write_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts-attempt-1.json"
    _write_artifacts(artifacts_path, _blocking_artifact_names(1))
    _write_pass_evidence(
        release_tool, manifest, tmp_path, attempt=1, run_id=700, job_ids=job_ids
    )
    bundle_path = _run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == 1
    assert bundle["repository"] == manifest["repository"]
    assert bundle["candidate_id"] == manifest["candidate_id"]
    assert bundle["generation"] == manifest["generation"]
    assert bundle["sha"] == manifest["sha"]
    assert bundle["expected_core_version"] == manifest["core_version"]
    assert bundle["workflow_run_id"] == 700
    assert bundle["current_attempt"] == 1
    assert _check_names(bundle, 1) == {
        "lint",
        "test (3.12)",
        "test (3.13)",
        "test (3.14)",
        "visual-test",
        "perf-floors",
        "tutorial-tests",
        "ace-page-group-isolation",
    }
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    assert "evidence" in loaded["attempts"][0]["jobs"][0]
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "pass", report["failures"]


def test_scope_is_exact_caller_prefix(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    decoys = [
        dict(_job_row("lint", 9001), name="lint"),
        dict(_job_row("lint", 9002), name="other-ci / lint"),
        dict(_job_row("lint", 9003), name="qualify-ci-extra / lint"),
        dict(_job_row("lint", 9004), name="qualify-ci"),
        dict(_job_row("lint", 9005), name="qualify-ci / lint / nested"),
    ]
    scoped = _job_row("lint", 9100)
    jobs_path = tmp_path / "jobs.json"
    _write_pages(jobs_path, decoys + [scoped], paginated=True)
    out = tmp_path / "bundle.json"
    status = tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            "700",
            "--evidence-root",
            str(tmp_path),
            "--attempt-jobs",
            f"1={jobs_path}",
            "--out",
            str(out),
        ]
    )
    assert status == 0
    captured = capsys.readouterr()
    # "qualify-ci / lint / nested" is caller-scoped but matches no inventory
    # check, so it is scoped yet unemitted: never suffix-matched to lint.
    assert "2 scoped row(s)" in captured.out
    assert "4 ignored row(s)" in captured.out
    bundle = json.loads(out.read_text(encoding="utf-8"))
    attempt_jobs = bundle["attempts"][0]["jobs"]
    assert [row["job_id"] for row in attempt_jobs] == [9100]
    assert attempt_jobs[0]["job_name"] == "lint"
    assert attempt_jobs[0]["matrix"] == {}


def test_rerun_carry_forward_evaluates_green(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = _entries()
    first_ids = {str(entry["id"]): 3000 + index for index, entry in enumerate(entries)}
    first_rows = []
    for entry in entries:
        check_id = str(entry["id"])
        conclusion = "failure" if check_id == "test-3.12" else "success"
        row = _job_row(
            str(entry["job"]["name"]), first_ids[check_id], conclusion=conclusion
        )
        if check_id == "test-3.12":
            row["steps"] = [
                {"name": "setup", "status": "completed", "conclusion": "success"},
                {"name": "run", "status": "completed", "conclusion": "failure"},
                {
                    "name": "Write qualification evidence",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "Upload qualification evidence",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        first_rows.append(row)
    jobs_1 = tmp_path / "jobs-attempt-1.json"
    _write_pages(jobs_1, first_rows, paginated=False)
    artifacts_1 = tmp_path / "artifacts-attempt-1.json"
    _write_artifacts(artifacts_1, _blocking_artifact_names(1))
    _write_pass_evidence(
        release_tool,
        manifest,
        tmp_path,
        attempt=1,
        run_id=700,
        job_ids=first_ids,
        scenario={"test-3.12": "tests"},
    )
    rerun_id = 4000
    jobs_2 = tmp_path / "jobs-attempt-2.json"
    _write_pages(
        jobs_2,
        [_job_row("test (3.12)", rerun_id, run_attempt=2, conclusion="success")],
        paginated=True,
    )
    artifacts_2 = tmp_path / "artifacts-attempt-2.json"
    _write_artifacts(artifacts_2, ["qualify-evidence-test-3.12-attempt-2"])
    _write_pass_evidence(
        release_tool,
        manifest,
        tmp_path,
        attempt=2,
        run_id=700,
        job_ids={"test-3.12": rerun_id, "lint": 0, "test-3.13": 0, "test-3.14": 0},
        scenario={"test-3.12": "pass"},
    )
    bundle_path = _run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_1], 2: [jobs_2]},
        artifacts={1: [artifacts_1], 2: [artifacts_2]},
        run_id=700,
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["current_attempt"] == 2
    first = {row["job_name"]: row for row in bundle["attempts"][0]["jobs"]}
    second = {row["job_name"]: row for row in bundle["attempts"][1]["jobs"]}
    assert second["lint"] == first["lint"]
    assert second["lint"]["evidence_file"] == "attempt-1/qualify-evidence-lint.json"
    assert second["test (3.12)"]["job_id"] == rerun_id
    assert second["test (3.12)"]["execution_attempt"] == 2
    assert second["test (3.12)"]["evidence_file"] == (
        "attempt-2/qualify-evidence-test-3.12.json"
    )
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=2,
    )
    assert report["verdict"] == "pass", report["failures"]


def test_missing_upload_is_typed_missing(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = _entries()
    job_ids = {str(entry["id"]): 5000 + index for index, entry in enumerate(entries)}
    rows = [
        _job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in entries
    ]
    jobs_path = tmp_path / "jobs.json"
    _write_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    _write_artifacts(
        artifacts_path,
        [name for name in _blocking_artifact_names(1) if "test-3.14" not in name],
    )
    _write_pass_evidence(
        release_tool, manifest, tmp_path, attempt=1, run_id=700, job_ids=job_ids
    )
    bundle_path = _run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    records = {row["job_name"]: row for row in bundle["attempts"][0]["jobs"]}
    assert records["test (3.14)"]["evidence_error_class"] == "missing"
    assert "evidence_file" not in records["test (3.14)"]
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "red"
    failure = next(item for item in report["failures"] if item["job"] == "test (3.14)")
    assert failure["failure_class"] == "missing"


def test_expired_and_unreadable_payloads_stay_typed(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        _job_row("lint", 6001),
        _job_row("test (3.12)", 6002),
        _job_row("test (3.13)", 6003),
        _job_row("test (3.14)", 6004),
    ]
    jobs_path = tmp_path / "jobs.json"
    _write_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    _write_artifacts(
        artifacts_path,
        _blocking_artifact_names(1),
        expired={"qualify-evidence-lint-attempt-1"},
    )
    evidence_dir = tmp_path / "attempt-1"
    evidence_dir.mkdir()
    (evidence_dir / "qualify-evidence-test-3.12.json").write_text(
        "not json", encoding="utf-8"
    )
    bundle_path = _run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    records = {
        row["job_name"]: row
        for row in json.loads(bundle_path.read_text(encoding="utf-8"))["attempts"][0][
            "jobs"
        ]
    }
    assert records["lint"]["evidence_error_class"] == "missing"
    assert "expired" in records["lint"]["evidence_error"]
    assert records["test (3.12)"]["evidence_error_class"] == "harness"
    assert records["test (3.13)"]["evidence_error_class"] == "missing"
    assert records["test (3.14)"]["evidence_error_class"] == "missing"


def test_duplicate_scoped_rows_are_preserved_for_refusal(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    jobs_path = tmp_path / "jobs.json"
    _write_pages(
        jobs_path, [_job_row("lint", 7001), _job_row("lint", 7002)], paginated=False
    )
    bundle_path = _run_collect(
        tool, tmp_path, manifest_path=manifest_path, jobs={1: [jobs_path]}
    )
    jobs = json.loads(bundle_path.read_text(encoding="utf-8"))["attempts"][0]["jobs"]
    assert sorted(row["job_id"] for row in jobs) == [7001, 7002]


def test_advisory_jobs_need_no_evidence(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocking = [entry for entry in _entries() if entry["disposition"] == "blocking"]
    job_ids = {str(entry["id"]): 8000 + index for index, entry in enumerate(blocking)}
    rows = [
        _job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in blocking
    ]
    jobs_path = tmp_path / "jobs.json"
    _write_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    _write_artifacts(artifacts_path, _blocking_artifact_names(1))
    _write_pass_evidence(
        release_tool, manifest, tmp_path, attempt=1, run_id=700, job_ids=job_ids
    )
    bundle_path = _run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert _check_names(bundle, 1) == {
        "lint",
        "test (3.12)",
        "test (3.13)",
        "test (3.14)",
    }
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "pass", report["failures"]
    assert len(report["advisories"]) == 4
    assert all(item["status"] == "missing" for item in report["advisories"])


def test_noncontiguous_attempts_refuse(tool: ModuleType, tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    jobs_1 = tmp_path / "jobs-1.json"
    _write_pages(jobs_1, [_job_row("lint", 9001)], paginated=False)
    jobs_3 = tmp_path / "jobs-3.json"
    _write_pages(jobs_3, [_job_row("lint", 9002, run_attempt=3)], paginated=False)
    status = tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            "700",
            "--evidence-root",
            str(tmp_path),
            "--attempt-jobs",
            f"1={jobs_1}",
            "--attempt-jobs",
            f"3={jobs_3}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert status == 2


def test_malformed_pages_refuse(tool: ModuleType, tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"total_count": 0}), encoding="utf-8")
    status = tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            "700",
            "--evidence-root",
            str(tmp_path),
            "--attempt-jobs",
            f"1={bad}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert status == 2
