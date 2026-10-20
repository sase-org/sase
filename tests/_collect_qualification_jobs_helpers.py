"""Shared builders for collect-qualification-jobs tests.

Split from ``tests.test_collect_qualification_jobs``. Not a conftest so
files opt in by importing the helpers directly. Names are public so the
``test_collect_qualification_jobs_*`` split modules can share them without
importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import load_tool as load_release_tool
from tests._release_qualification_test_support import _qualification_evidence

__all__ = [
    "INVENTORY",
    "ROOT",
    "SCRIPT",
    "blocking_artifact_names",
    "check_names_for_attempt",
    "collect_tool_fixture",
    "load_collect_tool",
    "qualification_entries",
    "qualification_job_row",
    "qualification_manifest",
    "release_tool_fixture",
    "run_collect",
    "write_artifact_pages",
    "write_job_pages",
    "write_pass_evidence",
]


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "collect_qualification_jobs"
INVENTORY = ROOT / ".github" / "release-qualification.json"


def load_collect_tool() -> ModuleType:
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


@pytest.fixture(scope="module", name="tool")
def collect_tool_fixture() -> ModuleType:
    return load_collect_tool()


@pytest.fixture(scope="module", name="release_tool")
def release_tool_fixture() -> ModuleType:
    return load_release_tool()


def qualification_manifest() -> dict[str, object]:
    return {
        "repository": "sase-org/sase",
        "candidate_id": "candidate-fact-reader",
        "generation": 1,
        "sha": "b" * 40,
        "core_version": "0.42.0",
    }


def qualification_entries() -> list[dict[str, object]]:
    inventory = json.loads(INVENTORY.read_bytes().decode("utf-8"))
    return [
        entry
        for entry in inventory["checks"]
        if entry["workflow"] == ".github/workflows/ci.yml"
    ]


def qualification_job_row(
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


def write_job_pages(
    path: Path, rows: list[dict[str, object]], *, paginated: bool
) -> None:
    page = {"total_count": len(rows), "jobs": rows}
    payload: object = [page] if paginated else page
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_artifact_pages(
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


def blocking_artifact_names(attempt: int) -> list[str]:
    return [
        f"qualify-evidence-{check_id}-attempt-{attempt}"
        for check_id in ("lint", "test-3.12", "test-3.13", "test-3.14")
    ]


def write_pass_evidence(
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
        entry["id"]: entry
        for entry in qualification_entries()
        if entry["disposition"] == "blocking"
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


def run_collect(
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


def check_names_for_attempt(bundle: dict[str, object], attempt: int) -> set[str]:
    snapshots = bundle["attempts"]
    assert isinstance(snapshots, list)
    snapshot = next(row for row in snapshots if row["attempt"] == attempt)
    return {str(row["job_name"]) for row in snapshot["jobs"]}
