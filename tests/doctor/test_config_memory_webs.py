"""Doctor coverage for memory-web validation."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_config_memory_webs import check_config_memory_webs
from sase.doctor.runner import DoctorContext


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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

    check = check_config_memory_webs(context)

    assert check.status == "ERROR"
    assert any("must not declare type" in detail for detail in check.details)


def test_doctor_memory_webs_blocks_dual_glossary_sources(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(
        project / "sase" / "sase.yml",
        "memory:\n  glossary:\n    Workspace:\n"
        "      definition: A numbered project checkout.\n",
    )
    _write(
        project / "sase" / "memory" / "glossary.md",
        "---\ntype: core\nparent: AGENTS.md\nweb: true\nroster: inline\n"
        "roster_label: GLOSSARY TERMS\n---\n\nGlossary descriptor.\n",
    )
    _write(
        project / "sase" / "memory" / "glossary" / "workspace.md",
        "---\nkeyword: Workspace\n---\n\nA numbered project checkout.\n",
    )
    home.mkdir()
    context = DoctorContext(
        cwd=project,
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(home)},
    )

    check = check_config_memory_webs(context)

    assert check.status == "ERROR"
    assert any("sase memory web migrate glossary" in detail for detail in check.details)
