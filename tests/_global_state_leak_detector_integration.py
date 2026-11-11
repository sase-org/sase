"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests._global_state_leak_detector import _drain_config_token_refresh_after_test


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
        "tests._conftest_runtime._drain_config_token_refresh",
        side_effect=RuntimeError("sase-config-token-refresh did not exit within 2.0s"),
    ):
        _drain_config_token_refresh_after_test()


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
