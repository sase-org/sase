"""Producer-to-consumer qualification transport integration tests.

Drives the real workflow command wiring (``fetch-evidence``, the bundle
collector, ``release_candidate qualify``/``evaluate``, and the draft attach
block from ``release.yml``) against a fake Actions transport: a ``gh``
executable on PATH serving canned jobs pages, run-scoped artifacts, evidence
zips, and a fake draft release.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests._release_candidate_tool_helpers import seal_kwargs as _seal_kwargs


ROOT = Path(__file__).resolve().parents[1]
COLLECT_SCRIPT = ROOT / "tools" / "collect_qualification_jobs"
RELEASE_SCRIPT = ROOT / "tools" / "release_candidate"
WRITE_SCRIPT = ROOT / "tools" / "write_qualification_evidence"
INVENTORY = ROOT / ".github" / "release-qualification.json"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

RUN_ID = 700
REPO = "sase-org/sase"
SHA = "b" * 40
CORE_VERSION = "0.42.0"


def _load(name: str, path: Path) -> ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def collect_tool() -> ModuleType:
    return _load("integration_collect_tool", COLLECT_SCRIPT)


@pytest.fixture(scope="module")
def release_tool() -> ModuleType:
    return _load("integration_release_tool", RELEASE_SCRIPT)


@pytest.fixture(scope="module")
def write_tool() -> ModuleType:
    return _load("integration_write_tool", WRITE_SCRIPT)


FAKE_GH = """#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path

state = Path(os.environ["FAKE_GH_DIR"])
log = state / "calls.log"


def record(argv):
    with log.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(argv) + "\\n")


def main(argv):
    record(argv)
    if argv[:1] == ["api"]:
        endpoint = argv[1]
        if "/attempts/" in endpoint and endpoint.endswith("/jobs"):
            run = endpoint.split("/runs/")[1].split("/")[0]
            attempt = endpoint.split("/attempts/")[1].split("/")[0]
            sys.stdout.write((state / f"jobs_{run}_{attempt}.json").read_text())
            return 0
        if "/actions/runs/" in endpoint and endpoint.endswith("/artifacts"):
            sys.stdout.write((state / "artifacts.json").read_text())
            return 0
        if "/actions/artifacts/" in endpoint and endpoint.endswith("/zip"):
            artifact_id = endpoint.split("/actions/artifacts/")[1].split("/")[0]
            sys.stdout.buffer.write((state / "zips" / f"{artifact_id}.zip").read_bytes())
            return 0
        print(f"unknown api endpoint {endpoint}", file=sys.stderr)
        return 1
    if argv[:1] == ["release"]:
        action = argv[1]
        if action == "view":
            tag = argv[2]
            remote = state / "remote" / tag
            names = sorted(p.name for p in remote.glob("*") if p.is_file()) if remote.is_dir() else []
            if names:
                sys.stdout.write("\\n".join(names) + "\\n")
            return 0
        if action == "download":
            tag = argv[2]
            pattern = argv[argv.index("-p") + 1]
            dest = Path(argv[argv.index("-D") + 1])
            src = state / "remote" / tag / pattern
            if not src.is_file():
                print(f"asset {pattern} not found", file=sys.stderr)
                return 1
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest / pattern)
            return 0
        if action == "upload":
            tag = argv[2]
            files = [item for item in argv[3:] if not item.startswith("-")]
            remote = state / "remote" / tag
            remote.mkdir(parents=True, exist_ok=True)
            for item in files:
                shutil.copy(item, remote / Path(item).name)
            return 0
        print(f"unknown release action {action}", file=sys.stderr)
        return 1
    print(f"unknown command {argv[:1]}", file=sys.stderr)
    return 1


raise SystemExit(main(sys.argv[1:]))
"""


@pytest.fixture()
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a fake `gh` on PATH backed by a fresh state directory."""
    state = tmp_path / "gh-state"
    (state / "zips").mkdir(parents=True)
    (state / "remote").mkdir(parents=True)
    (state / "calls.log").write_text("", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("FAKE_GH_DIR", str(state))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    return state


def _manifest_kwargs() -> dict[str, object]:
    kwargs = _seal_kwargs()
    kwargs["sha"] = SHA
    return kwargs  # type: ignore[return-value]


def _job_row(
    name: str,
    job_id: int,
    *,
    run_attempt: int = 1,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict[str, object]:
    return {
        "id": job_id,
        "run_id": RUN_ID,
        "run_attempt": run_attempt,
        "name": f"qualify-ci / {name}",
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}/job/{job_id}",
        "started_at": "2026-10-19T20:00:00Z",
        "completed_at": "2026-10-19T20:10:00Z",
        "steps": [
            {"name": "setup", "status": "completed", "conclusion": "success"},
            {"name": "run", "status": "completed", "conclusion": conclusion},
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
        ],
    }


def _seed_jobs(state: Path, attempt: int, rows: list[dict[str, object]]) -> None:
    """Serve the attempt jobs as a two-page slurp array, like `gh --slurp`."""
    first, second = rows[:2], rows[2:]
    pages = [
        {"total_count": len(rows), "jobs": first},
        {"total_count": len(rows), "jobs": second},
    ]
    (state / f"jobs_{RUN_ID}_{attempt}.json").write_text(
        json.dumps(pages), encoding="utf-8"
    )


def _seed_artifacts(state: Path, names: list[str]) -> None:
    pages = [
        {
            "total_count": len(names),
            "artifacts": [
                {
                    "id": 1000 + index,
                    "name": name,
                    "expired": False,
                    "archive_download_url": f"https://api.github.com/artifacts/{name}",
                }
                for index, name in enumerate(names)
            ],
        }
    ]
    (state / "artifacts.json").write_text(json.dumps(pages), encoding="utf-8")


def _seed_zip(state: Path, artifact_id: int, payload_name: str, payload: bytes) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(payload_name, payload)
    (state / "zips" / f"{artifact_id}.zip").write_bytes(buffer.getvalue())


class _FakeHeaders(dict):  # type: ignore[type-arg]
    def get(self, key: object, default: object = None) -> object:
        return super().get(key, default)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.headers = _FakeHeaders({"Link": ""})

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _produce_evidence(
    write_tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    rows: list[dict[str, object]],
    attempt: int,
    candidate_id: str,
    generation: int,
    session_reports: dict[str, Path],
    bindings_stderr: str = "",
    lint_steps: tuple[str, str] = ("success", "success"),
    installed_core_version: str = CORE_VERSION,
) -> None:
    """Run the real evidence writer with a fake jobs transport resolving IDs.

    The fake transport serves the same scoped rows the fake `gh` serves, so
    resolved numeric identities agree with the consumer's job records.
    """
    import urllib.request

    def fake_urlopen(request: object, timeout: object = 30) -> _FakeResponse:
        return _FakeResponse({"total_count": len(rows), "jobs": rows})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    evidence_root = tmp_path / "evidence" / f"attempt-{attempt}"
    evidence_root.mkdir(parents=True, exist_ok=True)
    check_ids = {
        "lint": "lint",
        "test (3.12)": "test-3.12",
        "test (3.13)": "test-3.13",
        "test (3.14)": "test-3.14",
    }
    produced = []
    for row in rows:
        scoped = row.get("name", "")
        assert isinstance(scoped, str) and scoped.startswith("qualify-ci / ")
        name = scoped.split(" / ", 1)[1]
        if name not in check_ids or name in produced:
            continue
        produced.append(name)
        argv = [
            "--out",
            str(evidence_root / f"qualify-evidence-{check_ids[name]}.json"),
            "--inventory",
            str(INVENTORY),
            "--candidate-id",
            candidate_id,
            "--generation",
            str(generation),
            "--checked-out-sha",
            SHA,
            "--expected-core-version",
            CORE_VERSION,
            "--installed-core-version",
            installed_core_version,
            "--repository",
            REPO,
            "--workflow-run-id",
            str(RUN_ID),
            "--attempt",
            str(attempt),
            "--job-name",
            name,
            "--caller-job",
            "qualify-ci",
        ]
        if name == "lint":
            bindings_report = tmp_path / f"bindings-{attempt}.err"
            bindings_report.write_text(bindings_stderr, encoding="utf-8")
            argv.extend(
                [
                    "--kind",
                    "command",
                    "--bindings-report",
                    str(bindings_report),
                    "--step",
                    f"Preflight core bindings={lint_steps[0]}",
                    "--step",
                    f"Check pinned core bindings={lint_steps[1]}",
                ]
            )
        else:
            argv.extend(
                ["--kind", "pytest", "--session-report", str(session_reports[name])]
            )
        assert write_tool.main(argv) == 0
        written = json.loads(
            (evidence_root / f"qualify-evidence-{check_ids[name]}.json").read_text()
        )
        assert written["binding"]["job_id"] in {
            row["id"] for row in rows if row["name"] == f"qualify-ci / {name}"
        }, f"producer identity for {name} matches no fake transport row"


def _session_report(
    tmp_path: Path,
    name: str,
    *,
    failed: int = 0,
    collection_failed: bool = False,
) -> Path:
    path = tmp_path / f"session-{name}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "pytest_session",
                "collected": 2,
                "passed": 2 - failed,
                "failed": failed,
                "errors": 0,
                "skipped": 0,
                "collection_failed": collection_failed,
                "exit_status": 1 if (failed or collection_failed) else 0,
                "first_failing_node_ids": (
                    ["tests/test_qualification.py::test_breaks"] if failed else []
                ),
                "flaky_lines": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_collect(
    collect_tool: ModuleType,
    tmp_path: Path,
    manifest_path: Path,
    *,
    run_id: int = RUN_ID,
    attempts: int = 1,
) -> Path:
    argv = [
        "fetch-evidence",
        "--repo",
        REPO,
        "--run-id",
        str(run_id),
        "--attempts",
        str(attempts),
        "--jobs-dir",
        str(tmp_path / "jobs-pages"),
        "--artifacts-file",
        str(tmp_path / "artifacts-pages" / "run.json"),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--zips-dir",
        str(tmp_path / "zips"),
    ]
    assert collect_tool.main(argv) == 0
    bundle_argv = [
        "--inventory",
        str(INVENTORY),
        "--manifest",
        str(manifest_path),
        "--run-id",
        str(run_id),
        "--caller-job",
        "qualify-ci",
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--out",
        str(tmp_path / "jobs.json"),
    ]
    for attempt in range(1, attempts + 1):
        bundle_argv.extend(
            [
                "--attempt-jobs",
                f"{attempt}={tmp_path / 'jobs-pages' / f'attempt-{attempt}.json'}",
                "--attempt-artifacts",
                f"{attempt}={tmp_path / 'artifacts-pages' / 'run.json'}",
            ]
        )
    assert collect_tool.main(bundle_argv) == 0
    return tmp_path / "jobs.json"


def _seed_green_attempt(
    state: Path,
    tmp_path: Path,
    attempt: int,
    rows: list[dict[str, object]],
    checks: tuple[str, ...] = ("lint", "test-3.12", "test-3.13", "test-3.14"),
) -> None:
    names = [f"qualify-evidence-{check}-attempt-{attempt}" for check in checks]
    _seed_artifacts(state, names)
    for index, name in enumerate(names):
        leaf = f"qualify-evidence-{checks[index]}.json"
        payload = (tmp_path / "evidence" / f"attempt-{attempt}" / leaf).read_bytes()
        _seed_zip(state, 1000 + index, leaf, payload)
    _seed_jobs(state, attempt, rows)


def _qualify(
    release_tool: ModuleType,
    tmp_path: Path,
    manifest_path: Path,
    jobs_path: Path,
    *,
    attempt: int,
    asset: str,
) -> tuple[int, Path, dict[str, object]]:
    out = tmp_path / asset
    code = release_tool.main(
        [
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(INVENTORY),
            "--jobs",
            str(jobs_path),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            str(attempt),
            "--out",
            str(out),
        ]
    )
    observation = json.loads(out.read_text(encoding="utf-8"))
    return code, out, observation


def test_green_run_with_failed_advisory_passes(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**_manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        _job_row("lint", 101),
        _job_row("test (3.12)", 102),
        _job_row("test (3.13)", 103),
        _job_row("test (3.14)", 104),
        _job_row("visual-test", 105, conclusion="failure"),
    ]
    sessions = {
        name: _session_report(tmp_path, f"green-{name}")
        for name in ("test (3.12)", "test (3.13)", "test (3.14)")
    }
    _produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=sessions,
    )
    _seed_green_attempt(fake_gh, tmp_path, 1, rows)
    jobs_path = _run_collect(collect_tool, tmp_path, manifest_path)
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert (
        f"api repos/{REPO}/actions/runs/{RUN_ID}/attempts/1/jobs "
        "--paginate --slurp" in calls
    )
    assert (
        f"api repos/{REPO}/actions/runs/{RUN_ID}/artifacts --paginate --slurp" in calls
    )
    assert "/attempts/1/artifacts" not in calls
    assert calls.count(f"api repos/{REPO}/actions/artifacts/") == 4
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    code, out, observation = _qualify(
        release_tool, tmp_path, manifest_path, jobs_path, attempt=1, asset=asset
    )
    assert code == 0
    assert observation["asset"] == asset
    assert observation["verdict"] == "pass"
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "pass"
    assert result["workflow_run_id"] == RUN_ID
    assert result["current_attempt"] == 1
    assert result["rerun_eligible"] is False
    advisory = next(
        item for item in result["advisories"] if item["job_name"] == "visual-test"
    )
    assert "did not pass" in advisory["diagnostic"]
    assert out.is_file()


def test_failed_only_retry_stays_green(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**_manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    first_rows = [
        _job_row("lint", 201),
        _job_row("test (3.12)", 202, conclusion="failure"),
        _job_row("test (3.13)", 203),
        _job_row("test (3.14)", 204),
    ]
    first_sessions = {
        "test (3.12)": _session_report(tmp_path, "red-312", failed=1),
        "test (3.13)": _session_report(tmp_path, "green-313"),
        "test (3.14)": _session_report(tmp_path, "green-314"),
    }
    _produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=first_rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=first_sessions,
    )
    retry_rows = [_job_row("test (3.12)", 302, run_attempt=2)]
    retry_sessions = {"test (3.12)": _session_report(tmp_path, "retry-312")}
    _produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=retry_rows,
        attempt=2,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=retry_sessions,
    )
    _seed_jobs(fake_gh, 1, first_rows)
    _seed_jobs(fake_gh, 2, retry_rows)
    names = [
        "qualify-evidence-lint-attempt-1",
        "qualify-evidence-test-3.12-attempt-1",
        "qualify-evidence-test-3.13-attempt-1",
        "qualify-evidence-test-3.14-attempt-1",
        "qualify-evidence-test-3.12-attempt-2",
    ]
    _seed_artifacts(fake_gh, names)
    for index, name in enumerate(names):
        check = name.removeprefix("qualify-evidence-").rsplit("-attempt-", 1)
        payload = (
            tmp_path
            / "evidence"
            / f"attempt-{check[1]}"
            / f"qualify-evidence-{check[0]}.json"
        ).read_bytes()
        _seed_zip(fake_gh, 1000 + index, f"qualify-evidence-{check[0]}.json", payload)
    jobs_path = _run_collect(collect_tool, tmp_path, manifest_path, attempts=2)
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt2.json"
    )
    code, _, observation = _qualify(
        release_tool, tmp_path, manifest_path, jobs_path, attempt=2, asset=asset
    )
    assert code == 0
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "pass"
    assert result["current_attempt"] == 2
    assert result["attempt_results"][0]["verdict"] == "red"
    assert result["attempt_results"][1]["verdict"] == "pass"


def test_probe_with_failed_setup_names_missing_bindings(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**_manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        _job_row("lint", 401, conclusion="failure"),
        _job_row("test (3.12)", 402),
        _job_row("test (3.13)", 403),
        _job_row("test (3.14)", 404),
    ]
    sessions = {
        name: _session_report(tmp_path, f"probe-{name}")
        for name in ("test (3.12)", "test (3.13)", "test (3.14)")
    }
    stderr = (
        "sase_core_rs 0.17.0 is missing 2 of 10 required binding(s):\n"
        "  federation_worker_main\n"
        "  feature_flag_state_get\n"
        "remedy: published core is missing required bindings\n"
    )
    _produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=sessions,
        bindings_stderr=stderr,
        lint_steps=("failure", "skipped"),
        installed_core_version="0.17.0",
    )
    _seed_green_attempt(fake_gh, tmp_path, 1, rows)
    jobs_path = _run_collect(collect_tool, tmp_path, manifest_path)
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    code, _, observation = _qualify(
        release_tool, tmp_path, manifest_path, jobs_path, attempt=1, asset=asset
    )
    assert code == release_tool.EXIT_REFUSED
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "red"
    assert result["rerun_eligible"] is False
    failure = next(item for item in result["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    diagnostics = " ".join(failure["diagnostics"])
    assert "federation_worker_main" in diagnostics
    assert "feature_flag_state_get" in diagnostics
    assert "QUALIFY_RED" in observation["reason"]


def test_api_failure_stays_typed_red_through_cli_and_steward(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
) -> None:
    manifest = release_tool.seal_manifest(**_manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # No jobs seed: the fake transport has no pages, so every fetch fails
    # and the caller records the workflow's typed-red fallback, verbatim.
    code = collect_tool.main(
        [
            "fetch-evidence",
            "--repo",
            REPO,
            "--run-id",
            str(RUN_ID),
            "--attempts",
            "1",
            "--jobs-dir",
            str(tmp_path / "jobs-pages"),
            "--artifacts-file",
            str(tmp_path / "artifacts-pages" / "run.json"),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--zips-dir",
            str(tmp_path / "zips"),
        ]
    )
    assert code == collect_tool.EXIT_ERROR
    fallback = tmp_path / "jobs.json"
    fallback.write_text(
        "qualification fact fetch failed; see the job log\n", encoding="utf-8"
    )
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(INVENTORY),
            "--jobs",
            str(fallback),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--out",
            str(tmp_path / asset),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == release_tool.EXIT_REFUSED
    observation = json.loads((tmp_path / asset).read_text(encoding="utf-8"))
    assert observation["asset"] == asset
    assert observation["verdict"] == "red"
    assert observation["reason"].startswith("QUALIFY_RED")
    result = observation["extra"]["qualification"]["result"]
    assert result["workflow_run_id"] == RUN_ID
    assert result["current_attempt"] == 1
    assert result["rerun_eligible"] is False
    assert result["input_error"] != ""
    assert "unreadable JSON" in result["input_error"]
    # The steward reads the same observation through the evaluate CLI.
    evaluated = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "evaluate",
            "--manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert evaluated.returncode == release_tool.EXIT_REFUSED
    payload = json.loads(evaluated.stdout)
    clause = next(
        item for item in payload["clauses"] if item["name"] == "qualification"
    )
    assert clause["ok"] is False
    assert "QUALIFY_RED" in clause["detail"]
    assert payload["rerun_eligible"] is False


def test_wrong_caller_and_duplicate_scoped_rows_stay_red(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    tmp_path: Path,
) -> None:
    manifest = release_tool.seal_manifest(**_manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        dict(_job_row("lint", 501), name="other-ci / lint"),
        _job_row("lint", 502),
        _job_row("lint", 503),
    ]
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"total_count": 3, "jobs": rows}), encoding="utf-8")
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text(json.dumps({"total_count": 0, "artifacts": []}))
    code = collect_tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            str(RUN_ID),
            "--caller-job",
            "qualify-ci",
            "--evidence-root",
            str(tmp_path),
            "--attempt-jobs",
            f"1={jobs_path}",
            "--attempt-artifacts",
            f"1={artifacts_path}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert code == 0
    bundle = json.loads((tmp_path / "bundle.json").read_text(encoding="utf-8"))
    assert sorted(row["job_id"] for row in bundle["attempts"][0]["jobs"]) == [502, 503]
    asset = "candidate-gen1-qualification-run700-attempt1.json"
    out = tmp_path / asset
    qualify_code = release_tool.main(
        [
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(INVENTORY),
            "--jobs",
            str(tmp_path / "bundle.json"),
            "--evidence-dir",
            str(tmp_path),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--out",
            str(out),
        ]
    )
    assert qualify_code == release_tool.EXIT_REFUSED
    result = json.loads(out.read_text(encoding="utf-8"))["extra"]["qualification"][
        "result"
    ]
    assert result["verdict"] == "red"
    failure = next(item for item in result["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    assert "ambiguous" in " ".join(failure["diagnostics"])


def _attach_block() -> str:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["qualify"]["steps"]
    attach = next(
        step
        for step in steps
        if step.get("name") == "Attach the qualification observation to the draft"
    )
    return attach["run"]


def _run_attach(
    block: str, tmp_path: Path, asset: str, tag: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, ASSET=asset, TAG=tag)
    return subprocess.run(
        ["bash", "-c", block],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        cwd=tmp_path,
        env=env,
    )


def test_draft_attach_uses_canonical_asset_bytes(fake_gh: Path, tmp_path: Path) -> None:
    block = _attach_block()
    assert 'gh release upload "${TAG}" "$ASSET"' in block
    asset = "candidate-gen1-qualification-run700-attempt1.json"
    body = json.dumps({"asset": asset, "verdict": "pass"})
    (tmp_path / asset).write_text(body, encoding="utf-8")
    tag = "v0.18.0"
    first = _run_attach(block, tmp_path, asset, tag)
    assert first.returncode == 0, first.stderr
    remote = fake_gh / "remote" / tag / asset
    assert remote.is_file()
    assert remote.read_text(encoding="utf-8") == body
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert f"release upload {tag} {asset}" in calls
    # Re-appending identical bytes is a no-op.
    uploads_before = calls.count(f"release upload {tag} {asset}")
    second = _run_attach(block, tmp_path, asset, tag)
    assert second.returncode == 0, second.stderr
    assert "already attached; skipping upload" in second.stdout
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert calls.count(f"release upload {tag} {asset}") == uploads_before
    # Conflicting bytes refuse without replacement.
    remote.write_text(json.dumps({"asset": asset, "verdict": "red"}), encoding="utf-8")
    third = _run_attach(block, tmp_path, asset, tag)
    assert third.returncode != 0
    assert "conflicting qualification observation" in third.stdout
    assert remote.read_text(encoding="utf-8") != body
