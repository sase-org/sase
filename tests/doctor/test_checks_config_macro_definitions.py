"""Tests for doctor macro definition config checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor.checks_config_macros import check_config_macro_definitions
from sase.doctor.runner import DoctorContext


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def test_macro_definitions_ok_when_no_load_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.macro.loader.get_all_prompts",
        lambda *_args, **_kwargs: {"review": object()},
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = check_config_macro_definitions(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert "1 macro/workflow definition(s) loaded cleanly" == check.summary
    assert check.data["issues"] == ()


def test_macro_definitions_warns_with_skipped_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.macro.load_issues import record_load_issue

    def load_prompts_with_issue(*_args: object, **_kwargs: object) -> dict[str, object]:
        record_load_issue(
            "/tmp/bad.yml", "mapping values are not allowed", kind="workflow"
        )
        return {}

    monkeypatch.setattr("sase.macro.loader.get_all_prompts", load_prompts_with_issue)
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = check_config_macro_definitions(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "1 macro definition file(s) skipped or degraded"
    assert check.details == ("skipped: /tmp/bad.yml: mapping values are not allowed",)
    assert [dict(row) for row in check.data["issues"]] == [
        {
            "source": "/tmp/bad.yml",
            "error": "mapping values are not allowed",
            "kind": "workflow",
        }
    ]
