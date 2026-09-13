"""Tests for doctor retired xprompt directive checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor import checks_config
from sase.doctor.checks_config_xprompts import check_config_xprompt_directives
from sase.doctor.runner import DoctorContext, default_doctor_context
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def _patch_xprompt_env(
    monkeypatch: pytest.MonkeyPatch,
    xprompts: dict[str, XPrompt],
    workflows: dict[str, Workflow] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda *_a, **_k: xprompts,
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_workflows",
        lambda *_a, **_k: workflows or {},
    )


def test_xprompt_directives_warns_with_name_source_and_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "research_swarm.md"
    xprompts = {
        "research_swarm": XPrompt(
            name="research_swarm",
            content="First line\n%wait(priority=20)\nDo work",
            source_path=str(source),
        ),
    }
    _patch_xprompt_env(monkeypatch, xprompts)

    check = check_config_xprompt_directives(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "1 xprompt definition(s) use retired directive syntax"
    assert "research_swarm" in check.details[0]
    assert str(source) in check.details[0]
    assert ":2: %wait(priority=20) — %wait(priority=...) has moved" in check.details[0]
    assert check.data["problems"][0]["name"] == "research_swarm"


def test_xprompt_directives_ok_when_definitions_are_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "research_swarm": XPrompt(
            name="research_swarm",
            content="%w(builder, time=5m) %q(1, p=20)\nDo work",
            source_path=str(tmp_path / "research_swarm.md"),
        ),
    }
    _patch_xprompt_env(monkeypatch, xprompts)

    check = check_config_xprompt_directives(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert check.data["problems"] == ()


def test_xprompt_directives_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())
    spec_by_id = {spec.id: spec for spec in specs}

    assert "config.xprompt_directives" in spec_by_id
    assert spec_by_id["config.xprompt_directives"].group == "config"
