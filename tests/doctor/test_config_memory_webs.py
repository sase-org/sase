"""Doctor coverage for memory-web validation."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_config_memory_webs import check_config_memory_webs
from sase.doctor.runner import DoctorContext
from sase.feature_flags import override_flags


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_doctor_memory_webs_skips_when_flag_disabled(tmp_path: Path) -> None:
    context = DoctorContext(
        cwd=tmp_path / "project",
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(tmp_path / "home")},
    )

    with override_flags(memory_webs=False):
        check = check_config_memory_webs(context)

    assert check.status == "OK"
    assert check.data["enabled"] is False


def test_doctor_memory_webs_reports_validation_blockers(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(
        project / "sase" / "memory" / "terms.md",
        "---\ntype: core\nparent: AGENTS.md\nweb: true\n---\n\nTerms.\n",
    )
    _write(
        project / "sase" / "memory" / "terms" / "alpha.md",
        "---\ntype: core\n---\n\nBad strand.\n",
    )
    home.mkdir()
    context = DoctorContext(
        cwd=project,
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(home)},
    )

    with override_flags(memory_webs=True):
        check = check_config_memory_webs(context)

    assert check.status == "ERROR"
    assert any("must not declare type" in detail for detail in check.details)
