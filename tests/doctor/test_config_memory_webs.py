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


def test_doctor_memory_webs_ignores_retired_config_glossary_key(
    tmp_path: Path,
) -> None:
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

    assert check.status == "OK"
    assert check.details == ()


def test_doctor_memory_webs_warns_on_unresolved_strand_link(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(
        project / "sase" / "memory" / "terms.md",
        "---\nweb: true\nroster: inline\n---\n\nTerms.\n",
    )
    _write(
        project / "sase" / "memory" / "terms" / "alpha.md",
        "---\nkeyword: Alpha Term\n---\n\nSee [[missing-target]].\n",
    )
    home.mkdir()
    context = DoctorContext(
        cwd=project,
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(home)},
    )

    check = check_config_memory_webs(context)

    assert check.status == "WARN"
    assert any(
        "unresolved memory link [[missing-target]]" in detail
        for detail in check.details
    )
    assert all(detail.startswith("project:") for detail in check.details)


def test_doctor_memory_webs_warns_on_supersession_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(
        project / "sase" / "memory" / "terms.md",
        "---\nweb: true\nroster: inline\n---\n\nTerms.\n",
    )
    _write(
        project / "sase" / "memory" / "terms" / "alpha.md",
        "---\n"
        "keyword: Alpha Term\n"
        "metadata:\n"
        "  status: superseded\n"
        "  superseded_by: terms/beta\n"
        "---\n"
        "Old body with no back-link.\n",
    )
    _write(
        project / "sase" / "memory" / "terms" / "beta.md",
        "---\nkeyword: Beta Term\n---\n\nNew body.\n",
    )
    home.mkdir()
    context = DoctorContext(
        cwd=project,
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(home)},
    )

    check = check_config_memory_webs(context)

    assert check.status == "WARN"
    assert any(
        "strand body has no [[...]] link resolving to superseded_by target "
        "'terms/beta'" in detail
        for detail in check.details
    )
    assert all(detail.startswith("project:") for detail in check.details)


def test_doctor_memory_webs_warns_on_flat_note_link_issues(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(
        project / "sase" / "memory" / "lint.md",
        "---\n"
        "type: reference\n"
        "parent: AGENTS.md\n"
        "description: Lint notes.\n"
        "link_reference: bogus\n"
        "link_rendering: sideways\n"
        "---\n"
        "See [[no-such.md]].\n",
    )
    home.mkdir()
    context = DoctorContext(
        cwd=project,
        project=None,
        sase_home=tmp_path / "state",
        env={"HOME": str(home)},
    )

    check = check_config_memory_webs(context)

    assert check.status == "WARN"
    details = "\n".join(check.details)
    assert "link_reference must be explicit, implicit, or none" in details
    assert "link_rendering must be reference or inline" in details
    assert "unresolved memory link [[no-such.md]]" in details
