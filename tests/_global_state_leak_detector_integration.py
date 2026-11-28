"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests._global_state_leak_detector import _drain_config_token_refresh_after_test
from tests._tmp_leak_guard import DISABLED_ENV as TMP_LEAK_GUARD_DISABLED_ENV


_ROOT = Path(__file__).resolve().parents[1]


def test_report_only_mode_keeps_pytest_green_on_poison(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    pytester.makepyfile(
        """
        import sase

        sase._LEAK_FOR_TEST = {"value": "before"}

        def test_poison_global_state():
            sase._LEAK_FOR_TEST["value"] = "after"
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        timeout=60,
    )

    result.assert_outcomes(passed=1)


def test_fail_on_poison_mode_fails_pytest_on_poison(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    report_path = pytester.path / "leaks.json"
    pytester.makepyfile(
        """
        import sase

        sase._LEAK_FOR_TEST = {"value": "before"}

        def test_poison_global_state():
            sase._LEAK_FOR_TEST["value"] = "after"
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        "--sase-fail-on-global-leaks",
        f"--sase-global-leak-report={report_path}",
        timeout=60,
    )

    assert result.ret != 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["poisoning_changes"] == 1
    assert report["poisoning"][0]["worker_id"] == "controller"
    assert report["poisoning"][0]["worker_order"] == 1
    output = "\n".join(result.outlines)
    assert "test_poison_global_state" in output
    assert "global:sase._LEAK_FOR_TEST" in output


def test_drain_after_test_swallows_join_timeout() -> None:
    """A stuck worker stays for the after-snapshot instead of erroring the hook."""
    with patch(
        "tests._conftest_runtime._drain_config_producers_then_refresh",
        side_effect=RuntimeError("sase-config-token-refresh did not exit within 2.0s"),
    ):
        _drain_config_token_refresh_after_test()


def test_drain_after_test_runs_header_then_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The protocol hook keeps producer-first ordering before the snapshot."""
    order: list[str] = []
    monkeypatch.setattr(
        "tests._conftest_runtime._drain_header_enrichment_services_if_loaded",
        lambda **_kwargs: order.append("header"),
    )
    monkeypatch.setattr(
        "tests._conftest_runtime._drain_config_token_refresh",
        lambda **_kwargs: order.append("config"),
    )
    _drain_config_token_refresh_after_test()
    assert order == ["header", "config"]


def test_protocol_drain_clears_refresh_thread_restarted_after_fixtures(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Module-scoped ACE apps can restart the worker after autouse drain."""
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    report_path = pytester.path / "leaks.json"
    pytester.makeconftest(
        """
        import pytest

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(item, nextitem):
            yield
            from sase.config.core import current_config_token

            current_config_token()
        """
    )
    pytester.makepyfile(
        """
        def test_reads_config_token():
            from sase.config.core import current_config_token

            current_config_token()
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        "--sase-fail-on-global-leaks",
        f"--sase-global-leak-report={report_path}",
        timeout=60,
    )

    result.assert_outcomes(passed=1)
    assert result.ret == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["poisoning_changes"] == 0


def test_header_resolver_late_read_does_not_poison_leak_snapshot(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocking leak detection stays green through the producer-first drain."""
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    # This nested session loads the repo conftest and shares the outer suite's
    # private TMPDIR, so its session temp-leak guard would report entries the
    # outer suite's other xdist workers create meanwhile (sase-1vz).
    monkeypatch.setenv(TMP_LEAK_GUARD_DISABLED_ENV, "1")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    report_path = pytester.path / "leaks.json"
    worker_file = _ROOT / "tests/ace/tui/widgets/test_agent_display_header_worker.py"
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        f"{worker_file}::test_header_drain_waits_for_resolver_before_config_drain",
        f"{worker_file}::test_producer_then_config_drain_joins_late_refresh_thread",
        "--sase-detect-global-leaks",
        "--sase-fail-on-global-leaks",
        f"--sase-global-leak-report={report_path}",
        timeout=60,
    )
    result.assert_outcomes(passed=2)
    assert result.ret == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["poisoning_changes"] == 0
    assert report.get("errors") in (None, [])
