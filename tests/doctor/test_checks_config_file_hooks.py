"""Tests for the ``sase doctor`` file-hook config check."""

from __future__ import annotations

import pytest

from sase.config.file_hooks import _FileHookDiagnostic
from sase.doctor import checks_config
from sase.doctor.checks_config_file_hooks import check_config_file_hooks
from sase.doctor.runner import default_doctor_context


def test_file_hooks_check_ok_when_no_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_file_hooks.get_file_hook_diagnostics",
        lambda: (),
    )

    check = check_config_file_hooks()

    assert check.status == "OK"
    assert check.data["problems"] == ()


def test_file_hooks_check_reports_error_for_dropped_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_config_file_hooks.get_file_hook_diagnostics",
        lambda: (
            _FileHookDiagnostic(
                hook_name="research-highlights",
                source_layer="user",
                message="'research-highlights' is missing its plugin prefix; use "
                "'sase-research-artifacts@research-highlights'",
            ),
        ),
    )

    check = check_config_file_hooks()

    assert check.status == "ERROR"
    assert len(check.data["problems"]) == 1
    assert "research-highlights" in check.data["problems"][0]
    assert check.next_steps


def test_file_hooks_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())

    assert "config.file_hooks" in {spec.id for spec in specs}
