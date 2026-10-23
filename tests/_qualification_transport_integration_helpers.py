"""Shared builders for qualification transport integration tests.

Split from ``tests.test_qualification_transport_integration``. Not a conftest so
files opt in by importing the helpers directly. Names are public so the
``test_qualification_transport_integration_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests._release_candidate_tool_helpers import seal_kwargs

__all__ = [
    "COLLECT_SCRIPT",
    "CORE_VERSION",
    "FAKE_GH",
    "INVENTORY",
    "RELEASE_SCRIPT",
    "RELEASE_WORKFLOW",
    "REPO",
    "ROOT",
    "RUN_ID",
    "SHA",
    "WRITE_SCRIPT",
    "collect_tool_fixture",
    "fake_gh_fixture",
    "job_row",
    "manifest_kwargs",
    "produce_evidence",
    "qualify",
    "release_tool_fixture",
    "run_collect",
    "run_workflow_qualify",
    "seed_artifacts",
    "seed_jobs",
    "seed_zip",
    "session_report",
    "write_tool_fixture",
]


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


@pytest.fixture(scope="module", name="collect_tool")
def collect_tool_fixture() -> ModuleType:
    return _load("integration_collect_tool", COLLECT_SCRIPT)


@pytest.fixture(scope="module", name="release_tool")
def release_tool_fixture() -> ModuleType:
    return _load("integration_release_tool", RELEASE_SCRIPT)


@pytest.fixture(scope="module", name="write_tool")
def write_tool_fixture() -> ModuleType:
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


@pytest.fixture(name="fake_gh")
def fake_gh_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def manifest_kwargs() -> dict[str, object]:
    kwargs = seal_kwargs()
    kwargs["sha"] = SHA
    return kwargs  # type: ignore[return-value]


def job_row(
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


def seed_jobs(state: Path, attempt: int, rows: list[dict[str, object]]) -> None:
    """Serve the attempt jobs as a two-page slurp array, like `gh --slurp`."""
    first, second = rows[:2], rows[2:]
    pages = [
        {"total_count": len(rows), "jobs": first},
        {"total_count": len(rows), "jobs": second},
    ]
    (state / f"jobs_{RUN_ID}_{attempt}.json").write_text(
        json.dumps(pages), encoding="utf-8"
    )


def seed_artifacts(state: Path, names: list[str]) -> None:
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


def seed_zip(state: Path, artifact_id: int, payload_name: str, payload: bytes) -> None:
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


def produce_evidence(
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


def session_report(
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


def run_collect(
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


def qualify(
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


def run_workflow_qualify(
    tmp_path: Path,
    manifest_path: Path,
    *,
    tested_core_version: str = CORE_VERSION,
) -> tuple[dict[str, str], Path, dict[str, object]]:
    """Execute the actual evaluate step, including its upload-output wiring."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["qualify"]["steps"]
        if item.get("id") == "evaluate"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (tmp_path / "candidate").mkdir()
    shutil.copyfile(manifest_path, tmp_path / "candidate" / "candidate-manifest.json")
    (tmp_path / "tools").symlink_to(ROOT / "tools", target_is_directory=True)
    (tmp_path / ".github").symlink_to(ROOT / ".github", target_is_directory=True)
    output = tmp_path / "github-output"
    completed = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "REPOSITORY": REPO,
            "RUN_ID": str(RUN_ID),
            "RUN_ATTEMPT": "1",
            "CANDIDATE_ID": manifest["candidate_id"],
            "GENERATION": str(manifest["generation"]),
            "INTENDED_CORE": CORE_VERSION,
            "TESTED_CORE": tested_core_version,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert outputs["run-id"] == str(RUN_ID)
    assert outputs["attempt"] == "1"
    assert outputs["candidate-id"] == manifest["candidate_id"]
    assert outputs["generation"] == str(manifest["generation"])
    assert outputs["intended-core-version"] == CORE_VERSION
    assert outputs["tested-core-version"] == tested_core_version
    out = tmp_path / outputs["observation"]
    observation = json.loads(out.read_text(encoding="utf-8"))
    assert observation["asset"] == out.name
    assert outputs["verdict"] == observation["verdict"]
    assert outputs["token"] == observation["reason"]
    return outputs, out, observation
