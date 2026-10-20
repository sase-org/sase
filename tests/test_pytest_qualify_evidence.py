"""Tiny-session tests for the opt-in qualification pytest reporter."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "tests._pytest_qualify_evidence"


def _isolate_nested_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    pythonpath = os.pathsep.join(
        part for part in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if part
    )
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    # Outer xdist workers export this; a nested controller is not a worker.
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)


def _run_session(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    report: Path,
    source: str,
    *args: str,
) -> pytest.RunResult:
    pytester.makepyfile(source)
    monkeypatch.setenv("SASE_QUALIFY_EVIDENCE_PATH", str(report))
    _isolate_nested_pytest(monkeypatch)
    return pytester.runpytest_subprocess("-p", PLUGIN, "-q", *args)


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_passing_session_records_counts(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    result = _run_session(
        pytester, monkeypatch, report, "def test_ok():\n    assert True\n"
    )
    result.assert_outcomes(passed=1)
    payload = _payload(report)
    assert payload["kind"] == "pytest_session"
    assert payload["collected"] == 1
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["errors"] == 0
    assert payload["skipped"] == 0
    assert payload["collection_failed"] is False
    assert payload["exit_status"] == 0
    assert payload["first_failing_node_ids"] == []
    assert payload["flaky_lines"] == []


def test_assertion_failure_records_node_id(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    result = _run_session(
        pytester,
        monkeypatch,
        report,
        "def test_breaks():\n    assert False\n",
    )
    result.assert_outcomes(failed=1)
    payload = _payload(report)
    assert payload["failed"] == 1
    assert payload["passed"] == 0
    assert payload["exit_status"] == 1
    assert any("test_breaks" in node for node in payload["first_failing_node_ids"])


def test_collection_failure_is_not_a_test_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    result = _run_session(
        pytester,
        monkeypatch,
        report,
        "def test_oops(:\n    pass\n",
    )
    assert result.ret != 0
    payload = _payload(report)
    assert payload["collection_failed"] is True
    assert payload["failed"] == 0


def test_zero_collection_records_empty_counts(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    monkeypatch.setenv("SASE_QUALIFY_EVIDENCE_PATH", str(report))
    _isolate_nested_pytest(monkeypatch)
    (pytester.path / "not_a_test.txt").write_text("no tests here\n", encoding="utf-8")
    result = pytester.runpytest_subprocess("-p", PLUGIN, "-q")
    payload = _payload(report)
    assert payload["collected"] == 0
    assert payload["passed"] == 0
    assert payload["collection_failed"] is False
    assert payload["exit_status"] == result.ret


def test_setup_error_is_counted_as_error(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    source = textwrap.dedent(
        """
        import pytest

        @pytest.fixture
        def boom():
            raise RuntimeError("setup exploded")

        def test_needs_boom(boom):
            assert True
        """
    )
    result = _run_session(pytester, monkeypatch, report, source)
    assert result.ret != 0
    payload = _payload(report)
    assert payload["errors"] == 1
    assert payload["failed"] == 0
    assert any("test_needs_boom" in node for node in payload["first_failing_node_ids"])


def test_nested_pytest_does_not_overwrite_outer_report(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    inner = pytester.path / "nested_suite.py"
    inner.write_text("def test_inner():\n    assert False\n", encoding="utf-8")
    source = textwrap.dedent(
        f"""
        import subprocess
        import sys

        def test_outer():
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "{PLUGIN}",
                    "-q",
                    r"{inner}",
                ],
                check=False,
            )
            assert True
        """
    )
    result = _run_session(pytester, monkeypatch, report, source)
    result.assert_outcomes(passed=1)
    payload = _payload(report)
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["exit_status"] == 0


def test_xdist_counts_each_node_once(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("xdist")
    report = tmp_path / "session.json"
    source = textwrap.dedent(
        """
        def test_one():
            assert True

        def test_two():
            assert True
        """
    )
    result = _run_session(pytester, monkeypatch, report, source, "-n", "2")
    result.assert_outcomes(passed=2)
    payload = _payload(report)
    assert payload["collected"] == 2
    assert payload["passed"] == 2
    assert payload["failed"] == 0


def test_flaky_lines_are_captured_verbatim(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    source = textwrap.dedent(
        """
        def test_mentions_flaky():
            print("FLAKY: tests/test_qualification.py::test_flaky")
            assert False
        """
    )
    result = _run_session(pytester, monkeypatch, report, source)
    result.assert_outcomes(failed=1)
    payload = _payload(report)
    assert "FLAKY: tests/test_qualification.py::test_flaky" in payload["flaky_lines"]


def test_inherited_xdist_worker_env_does_not_suppress_controller_report(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    pytester.makepyfile("def test_ok():\n    assert True\n")
    monkeypatch.setenv("SASE_QUALIFY_EVIDENCE_PATH", str(report))
    pythonpath = os.pathsep.join(
        part for part in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if part
    )
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    result = pytester.runpytest_subprocess("-p", PLUGIN, "-q")
    result.assert_outcomes(passed=1)
    payload = _payload(report)
    assert payload["collected"] == 1
    assert payload["passed"] == 1


def test_plugin_is_inert_without_evidence_path(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "session.json"
    monkeypatch.delenv("SASE_QUALIFY_EVIDENCE_PATH", raising=False)
    _isolate_nested_pytest(monkeypatch)
    pytester.makepyfile("def test_ok():\n    assert True\n")
    result = pytester.runpytest_subprocess("-p", PLUGIN, "-q")
    result.assert_outcomes(passed=1)
    assert not report.exists()
