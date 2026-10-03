"""Tests for doctor retired macro directive checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor import checks_config
from sase.doctor.checks_config_macros import check_config_macro_directives
from sase.doctor.runner import DoctorContext, default_doctor_context
from sase.macro.models import Macro
from sase.macro.workflow_models import Workflow


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def _patch_macro_env(
    monkeypatch: pytest.MonkeyPatch,
    macros: dict[str, Macro],
    workflows: dict[str, Workflow] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.macro.loader.get_all_macros",
        lambda *_a, **_k: macros,
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_workflows",
        lambda *_a, **_k: workflows or {},
    )


def test_macro_directives_warns_with_name_source_and_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "research_swarm.md"
    macros = {
        "research_swarm": Macro(
            name="research_swarm",
            content="First line\n%wait(priority=20)\nDo work",
            source_path=str(source),
        ),
    }
    _patch_macro_env(monkeypatch, macros)

    check = check_config_macro_directives(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "1 xprompt definition(s) use retired directive syntax"
    assert "research_swarm" in check.details[0]
    assert str(source) in check.details[0]
    assert ":2: %wait(priority=20) — %wait(priority=...) has moved" in check.details[0]
    assert check.data["problems"][0]["name"] == "research_swarm"


def test_macro_directives_ok_when_definitions_are_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    macros = {
        "research_swarm": Macro(
            name="research_swarm",
            content="%w(builder, time=5m) %q(1, p=20)\nDo work",
            source_path=str(tmp_path / "research_swarm.md"),
        ),
    }
    _patch_macro_env(monkeypatch, macros)

    check = check_config_macro_directives(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert check.data["problems"] == ()


def test_macro_directives_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())
    spec_by_id = {spec.id: spec for spec in specs}

    assert "config.xprompt_directives" in spec_by_id
    assert spec_by_id["config.xprompt_directives"].group == "config"
