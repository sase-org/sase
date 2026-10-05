"""Tests for doctor macro input-type config checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor import checks_config
from sase.doctor.checks_config_macros import (
    check_config_macro_definitions,
    check_config_macro_input_types,
)
from sase.doctor.runner import DoctorContext, default_doctor_context


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def test_macro_input_types_ok_when_no_input_type_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.macro.loader.get_all_prompts",
        lambda *_args, **_kwargs: {"pr": object()},
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )
    check = check_config_macro_input_types(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert check.summary == "No macro input-type issues"
    assert check.data["issues"] == ()
    assert check.data["loaded_count"] == 1


def test_macro_input_types_reports_string_warning_and_unknown_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.macro.load_issues import record_load_issue

    warning = "input `items` uses deprecated type `string`; use `line` instead"
    error = "input `mode` has unknown type `enmu`; did you mean `enum`?"

    def load_prompts_with_issues(
        *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        record_load_issue("string.yml", warning, kind="input_type_warning")
        record_load_issue("unknown.yml", error, kind="input_type")
        return {"ok": object()}

    monkeypatch.setattr("sase.macro.loader.get_all_prompts", load_prompts_with_issues)
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = check_config_macro_input_types(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "2 macro input-type issue(s)"
    assert check.details == (
        f"warning: string.yml: {warning}",
        f"error: unknown.yml: {error}",
    )
    assert "enum" in check.details[1]


def test_macro_definitions_ignores_input_type_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.macro.load_issues import record_load_issue

    def load_prompts_with_warning(
        *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        record_load_issue(
            "string.yml",
            "input `items` uses deprecated type `string`; use `line` instead",
            kind="input_type_warning",
        )
        return {"ok": object()}

    monkeypatch.setattr("sase.macro.loader.get_all_prompts", load_prompts_with_warning)
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = check_config_macro_definitions(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert check.data["issues"] == ()


def test_macro_input_types_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())
    spec_by_id = {spec.id: spec for spec in specs}

    assert "config.macro_input_types" in spec_by_id
    assert spec_by_id["config.macro_input_types"].group == "config"
