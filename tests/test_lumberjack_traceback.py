"""Tests for lumberjack traceback capture.

Regression tests for the bug where ``error_digests`` were emitted with the
literal string ``"NoneType: None"`` as the traceback — the result of calling
``traceback.format_exc()`` outside any active ``except`` block.  Every error
path must now record a real traceback inside the ``except`` (via
``_capture_traceback``) or set an explicit placeholder for non-Python
failures (e.g. nonzero subprocess exits).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.axe.chop_runner import (
    NO_PYTHON_TRACEBACK as _NO_PYTHON_TRACEBACK,
    TRACEBACK_UNAVAILABLE as _TRACEBACK_UNAVAILABLE,
    _capture_traceback,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.lumberjack import (
    Lumberjack,
    _ChopResult,
)


def _make_lumberjack(tmp_path: Any) -> Lumberjack:
    """Construct a Lumberjack instance with one no-op chop, anchored at tmp_path."""
    chop = ChopConfig(name="probe", description="probe chop for tests")
    lj_config = LumberjackConfig(
        name="test",
        description="Run traceback test probes",
        interval=60,
        chops=[chop],
    )
    axe_config = AxeConfig()
    with patch("sase.axe.lumberjack.ensure_lumberjack_dirs", return_value=tmp_path):
        return Lumberjack("test", lj_config, axe_config)


def test_capture_traceback_inside_except_returns_real_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        captured = _capture_traceback()
    assert "RuntimeError: boom" in captured
    assert captured != _TRACEBACK_UNAVAILABLE


def test_capture_traceback_outside_except_returns_placeholder() -> None:
    captured = _capture_traceback()
    assert captured == _TRACEBACK_UNAVAILABLE
    assert "NoneType: None" not in captured


@pytest.mark.parametrize(
    ("result", "expected_traceback"),
    [
        (
            _ChopResult(
                chop_name="probe",
                executed=False,
                success=False,
                update_timestamp=False,
                error=RuntimeError("script not found"),
                traceback=_NO_PYTHON_TRACEBACK,
            ),
            _NO_PYTHON_TRACEBACK,
        ),
        (
            _ChopResult(
                chop_name="probe",
                executed=True,
                success=False,
                update_timestamp=False,
                error=RuntimeError("exit code 1: stderr line"),
                traceback=_NO_PYTHON_TRACEBACK,
            ),
            _NO_PYTHON_TRACEBACK,
        ),
        (
            _ChopResult(
                chop_name="probe",
                executed=True,
                success=False,
                update_timestamp=False,
                error=RuntimeError("real exception"),
                traceback="Traceback (most recent call last):\n  RuntimeError",
            ),
            "Traceback (most recent call last):\n  RuntimeError",
        ),
        (
            _ChopResult(
                chop_name="probe",
                executed=True,
                success=False,
                update_timestamp=False,
                error=RuntimeError("traceback explicitly missing"),
                traceback=None,
            ),
            _TRACEBACK_UNAVAILABLE,
        ),
    ],
)
def test_handle_error_never_emits_noneType_none(
    tmp_path: Any, result: _ChopResult, expected_traceback: str
) -> None:
    lj = _make_lumberjack(tmp_path)

    captured: list[dict[str, Any]] = []
    with patch("sase.axe.lumberjack.append_error", side_effect=captured.append):
        assert result.error is not None
        lj._handle_error(result.chop_name, result.error, result.traceback)

    assert len(captured) == 1
    error_info = captured[0]
    assert error_info["traceback"] == expected_traceback
    assert "NoneType: None" not in error_info["traceback"]
