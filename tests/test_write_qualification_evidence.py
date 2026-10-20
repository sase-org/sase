"""Tests for the stdlib qualification evidence serializer."""

from __future__ import annotations

import importlib.util
import json
import sys
from hashlib import sha256
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "write_qualification_evidence"
INVENTORY = ROOT / ".github" / "release-qualification.json"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("write_qualification_evidence_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "write_qualification_evidence_tool",
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


def _binding_kwargs(**overrides: object) -> dict[str, object]:
    payload = {
        "repository": "sase-org/sase",
        "candidate_id": "candidate-abc",
        "generation": 1,
        "checked_out_sha": "a" * 40,
        "expected_core_version": "0.42.0",
        "installed_core_version": "0.42.0",
        "digest": "d" * 64,
        "workflow_run_id": 11,
        "job_id": 22,
        "job_name": "test (3.12)",
        "attempt": 1,
    }
    payload.update(overrides)
    return payload


def test_missing_session_is_invalid_not_green(tool: ModuleType, tmp_path: Path) -> None:
    binding = tool._binding(**_binding_kwargs())
    payload = tool.pytest_evidence(
        binding=binding,
        session=None,
        flaky_lines=[],
        invalid_reason="",
    )
    assert payload["kind"] == "pytest"
    assert payload["invalid"] is True
    assert "collected" not in payload
    assert "passed" not in payload
    out = tmp_path / "qualify-evidence-test-3.12.json"
    status = tool.main(
        [
            "--kind",
            "pytest",
            "--out",
            str(out),
            "--session-report",
            str(tmp_path / "missing.json"),
            "--job-name",
            "test (3.12)",
            "--job-id",
            "22",
            "--candidate-id",
            "candidate-abc",
            "--generation",
            "1",
        ]
    )
    assert status == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["invalid"] is True
    assert written["kind"] == "pytest"


def test_session_report_becomes_pytest_evidence(
    tool: ModuleType, tmp_path: Path
) -> None:
    session = tmp_path / "session.json"
    session.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "pytest_session",
                "collected": 2,
                "passed": 1,
                "failed": 1,
                "errors": 0,
                "skipped": 0,
                "collection_failed": False,
                "exit_status": 1,
                "first_failing_node_ids": ["tests/test_qualification.py::test_breaks"],
                "flaky_lines": [],
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "job.log"
    log.write_text("FLAKY: tests/test_qualification.py::test_flaky\n", encoding="utf-8")
    out = tmp_path / "qualify-evidence-test-3.12.json"
    status = tool.main(
        [
            "--kind",
            "pytest",
            "--out",
            str(out),
            "--session-report",
            str(session),
            "--job-log",
            str(log),
            "--inventory",
            str(INVENTORY),
            "--job-name",
            "test (3.12)",
            "--job-id",
            "99",
            "--workflow-run-id",
            "12",
            "--attempt",
            "1",
            "--candidate-id",
            "candidate-abc",
            "--generation",
            "2",
            "--checked-out-sha",
            "b" * 40,
            "--expected-core-version",
            "0.42.0",
            "--installed-core-version",
            "0.42.0",
            "--repository",
            "sase-org/sase",
        ]
    )
    assert status == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["collected"] == 2
    assert payload["failed"] == 1
    assert payload["binding"]["job_id"] == 99
    assert payload["binding"]["generation"] == 2
    digest = sha256(INVENTORY.read_bytes()).hexdigest()
    assert payload["binding"]["inventory_digest"] == digest
    assert payload["flaky_lines"] == ["FLAKY: tests/test_qualification.py::test_flaky"]


def test_command_evidence_keeps_missing_binding_names(tool: ModuleType) -> None:
    stderr = (
        "sase_core_rs 0.41.0 is missing 2 of 10 required binding(s):\n"
        "  feature_flag_state_get\n"
        "  federation_worker_main\n"
        "remedy: published core is missing required bindings\n"
    )
    names = tool.parse_missing_bindings(stderr)
    assert names == ["feature_flag_state_get", "federation_worker_main"]
    payload = tool.command_evidence(
        binding=tool._binding(**_binding_kwargs(job_name="lint")),
        steps=[],
        missing_bindings=names,
        diagnostics=[],
    )
    assert payload["kind"] == "command"
    assert payload["missing_bindings"] == names
    assert payload["steps"][0]["name"] == "Preflight core bindings"
    assert payload["steps"][0]["conclusion"] == "failure"
    assert "collected" not in payload


def test_skipped_steps_are_dropped(tool: ModuleType) -> None:
    steps = tool.completed_steps(
        [
            "Preflight core bindings=skipped",
            "Check pinned core bindings=success",
            "Install dependencies=failure",
        ]
    )
    assert [step["name"] for step in steps] == [
        "Check pinned core bindings",
        "Install dependencies",
    ]
    assert steps[0]["exit_status"] == 0
    assert steps[1]["conclusion"] == "failure"


class _FakeHeaders(dict):  # type: ignore[type-arg]
    def get(self, key: object, default: object = None) -> object:
        return super().get(key, default)


class _FakeResponse:
    def __init__(self, payload: object, link: str) -> None:
        self._payload = payload
        self.headers = _FakeHeaders({"Link": link})

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _install_jobs_transport(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[dict[str, object]],
    *,
    fail_after: int | None = None,
) -> dict[str, int]:
    """Serve canned attempt-jobs pages with Link pagination; count requests."""
    import urllib.error
    import urllib.request

    calls = {"count": 0}

    def fake_urlopen(request: object, timeout: object = 30) -> _FakeResponse:
        calls["count"] += 1
        if fail_after is not None and calls["count"] > fail_after:
            raise urllib.error.URLError("transport exploded")
        url = request.full_url if hasattr(request, "full_url") else str(request)  # type: ignore[union-attr]
        if "page-next" in url:
            return _FakeResponse(pages[1], "")
        link = (
            '<https://api.github.com/page-next>; rel="next"' if len(pages) > 1 else ""
        )
        return _FakeResponse(pages[0], link)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "sase-org/sase")
    return calls


def _scoped_pages() -> list[dict[str, object]]:
    return [
        {
            "total_count": 3,
            "jobs": [
                {"id": 101, "name": "qualify-ci / lint"},
                {"id": 102, "name": "other-ci / lint"},
            ],
        },
        {
            "total_count": 3,
            "jobs": [{"id": 103, "name": "qualify-ci / test (3.12)"}],
        },
    ]


def test_scoped_identity_resolves_full_caller_prefix_across_pages(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="lint",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert (job_id, error) == (101, "")
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="test (3.12)",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert (job_id, error) == (103, "")


def test_scoped_identity_rejects_wrong_caller_and_suffix_bait(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="test (3.12)",
        caller_job="other-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert job_id is None
    assert "no exact job" in error
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="ci / lint",
        caller_job="qualify",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert job_id is None
    assert "no exact job" in error


def test_scoped_identity_rejects_ambiguous_matches(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(
        monkeypatch,
        [
            {"total_count": 2, "jobs": [{"id": 201, "name": "qualify-ci / lint"}]},
            {"total_count": 2, "jobs": [{"id": 202, "name": "qualify-ci / lint"}]},
        ],
    )
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="lint",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert job_id is None
    assert "ambiguous" in error


def test_scoped_identity_needs_credentials_and_complete_pages(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    monkeypatch.delenv("GITHUB_TOKEN")
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="lint",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert job_id is None
    assert "GITHUB_TOKEN" in error


def test_scoped_identity_reports_partial_pagination(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages(), fail_after=1)
    job_id, error = tool.resolve_job_id(
        explicit=None,
        job_name="lint",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert job_id is None
    assert "partial pagination" in error


def test_unscoped_lookup_stays_best_effort_for_source_callers(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    monkeypatch.delenv("GITHUB_TOKEN")
    job_id, error = tool.resolve_job_id(
        explicit=None, job_name="lint", run_id=700, attempt=1
    )
    assert (job_id, error) == (None, "")


def test_explicit_job_id_skips_the_transport(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_jobs_transport(monkeypatch, _scoped_pages())
    monkeypatch.delenv("GITHUB_TOKEN")
    job_id, error = tool.resolve_job_id(
        explicit=77,
        job_name="lint",
        caller_job="qualify-ci",
        run_id=700,
        attempt=1,
        strict=True,
    )
    assert (job_id, error) == (77, "")
    assert calls["count"] == 0


def test_scoped_identity_failure_is_invalid_command_evidence(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    monkeypatch.delenv("GITHUB_TOKEN")
    out = tmp_path / "qualify-evidence-lint.json"
    status = tool.main(
        [
            "--kind",
            "command",
            "--out",
            str(out),
            "--job-name",
            "lint",
            "--caller-job",
            "qualify-ci",
            "--workflow-run-id",
            "700",
            "--attempt",
            "1",
            "--step",
            "Check pinned core bindings=success",
        ]
    )
    assert status == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["binding"]["job_id"] is None
    assert any("GITHUB_TOKEN" in line for line in payload["diagnostics"])


def test_scoped_identity_failure_is_invalid_pytest_evidence(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_jobs_transport(monkeypatch, _scoped_pages())
    out = tmp_path / "qualify-evidence-test.json"
    status = tool.main(
        [
            "--kind",
            "pytest",
            "--out",
            str(out),
            "--job-name",
            "lint",
            "--caller-job",
            "no-such-caller",
            "--workflow-run-id",
            "700",
            "--attempt",
            "1",
        ]
    )
    assert status == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["invalid"] is True
    assert "no exact job" in " ".join(payload["diagnostics"])


def test_print_inventory_digest_matches_bytes(
    tool: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    status = tool.main(["--print-inventory-digest", "--inventory", str(INVENTORY)])
    assert status == 0
    assert capsys.readouterr().out.strip() == sha256(INVENTORY.read_bytes()).hexdigest()


def test_bind_manifest_refuses_core_version_mismatch(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = tmp_path / "candidate-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_id": "candidate-xyz",
                "generation": 3,
                "core_version": "0.41.0",
            }
        ),
        encoding="utf-8",
    )
    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")
    status = tool.bind_manifest(manifest, "0.42.0", github_output)
    assert status == 1
    assert github_output.read_text(encoding="utf-8") == ""


def test_bind_manifest_writes_identity(tool: ModuleType, tmp_path: Path) -> None:
    manifest = tmp_path / "candidate-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "candidate_id": "candidate-xyz",
                "generation": 3,
                "core_version": "0.42.0",
            }
        ),
        encoding="utf-8",
    )
    github_output = tmp_path / "github_output"
    github_output.write_text("core-source=published\n", encoding="utf-8")
    status = tool.bind_manifest(manifest, "0.42.0", github_output)
    assert status == 0
    text = github_output.read_text(encoding="utf-8")
    assert "candidate-id=candidate-xyz" in text
    assert "generation=3" in text
