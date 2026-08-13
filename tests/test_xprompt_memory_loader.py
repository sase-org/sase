"""Xprompt-memory discovery, validation, and expansion behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.memory.read_log import memory_read_log_path
from sase.xprompt.load_issues import collect_xprompt_load_issues
from sase.xprompt._trace import ExpansionTrace
from sase.xprompt.loader import get_all_xprompts, get_xprompt_or_workflow
from sase.xprompt.loader_memory import MEMORY_LOAD_ISSUE_KIND, load_memory_xprompts
from sase.xprompt.loader_sources import load_xprompt_from_file, load_xprompts_from_files
from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.processor import process_xprompt_references_with_catalog
from sase.xprompt.reserved_namespaces import RESERVED_MEMORY_NAMESPACE_ISSUE_KIND


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _memory_note(
    body: str,
    *,
    note_type: str = "long",
    description: str = "Memory note.",
) -> str:
    return (
        "---\n"
        f"type: {note_type}\n"
        "parent: AGENTS.md\n"
        f"description: {description}\n"
        "---\n"
        "\n"
        f"{body}"
    )


@pytest.fixture
def home_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_memory_loader_creates_namespaced_no_arg_xprompt(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(
        project / "sase" / "memory" / "glossary.md",
        _memory_note("# Glossary\n", note_type="long", description="Terms."),
    )
    _write(project / "sase" / "memory" / "README.md", "# Ignored\n")
    _write(project / "sase" / "memory" / "nested" / "ignored.md", "# Ignored\n")

    xprompts = load_memory_xprompts(project_root=project, home_root=home_root)

    assert set(xprompts) == {"memory/glossary"}
    glossary = xprompts["memory/glossary"]
    assert glossary.inputs == []
    assert glossary.content == "# Glossary\n"
    assert glossary.description == "Terms."
    assert glossary.memory_type == "long"
    assert glossary.source_path == str(project / "sase" / "memory" / "glossary.md")


def test_memory_loader_collapses_block_description(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(
        project / "sase" / "memory" / "glossary.md",
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: |-\n"
        "  Lead.\n"
        "\n"
        "  - One\n"
        "\n"
        "  Trailer.\n"
        "---\n"
        "\n"
        "# Glossary\n",
    )

    xprompts = load_memory_xprompts(project_root=project, home_root=home_root)

    assert xprompts["memory/glossary"].description == "Lead. - One Trailer."


def test_project_memory_shadows_home_memory(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(project / "sase" / "memory" / "foo.md", _memory_note("project\n"))
    _write(home_root / "sase" / "memory" / "foo.md", _memory_note("home\n"))

    xprompts = load_memory_xprompts(project_root=project, home_root=home_root)

    assert xprompts["memory/foo"].content == "project\n"


def test_memory_loader_falls_back_to_home(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(home_root / "sase" / "memory" / "foo.md", _memory_note("home\n"))

    xprompts = load_memory_xprompts(project_root=project, home_root=home_root)

    assert xprompts["memory/foo"].content == "home\n"


def test_invalid_memory_type_and_stem_record_load_issues(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(
        project / "sase" / "memory" / "bad_type.md",
        _memory_note("bad\n", note_type="stale"),
    )
    _write(
        project / "sase" / "memory" / "bad-name.md",
        _memory_note("bad\n"),
    )

    with collect_xprompt_load_issues() as issues:
        xprompts = load_memory_xprompts(project_root=project, home_root=home_root)

    assert xprompts == {}
    assert [issue.kind for issue in issues] == [
        MEMORY_LOAD_ISSUE_KIND,
        MEMORY_LOAD_ISSUE_KIND,
    ]
    errors = [issue.error for issue in issues]
    assert any("declare `type: short` or `type: long`" in error for error in errors)
    assert any(
        "cannot be referenced as `#memory/bad-name`" in error for error in errors
    )


def test_ordinary_xprompt_cannot_claim_memory_namespace(
    tmp_path: Path,
    home_root: Path,
) -> None:
    _write(
        home_root / "sase" / "xprompts" / "rogue.md",
        "---\nname: memory/foo\n---\n\nbody\n",
    )

    with collect_xprompt_load_issues() as issues:
        xprompts = load_xprompts_from_files()

    assert "memory/foo" not in xprompts
    assert [issue.kind for issue in issues] == [RESERVED_MEMORY_NAMESPACE_ISSUE_KIND]
    assert "reserved xprompt-memory reference `#memory/foo`" in issues[0].error


def test_direct_markdown_xprompt_cannot_claim_memory_namespace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rogue.md"
    _write(path, "---\nname: memory/foo\n---\n\nbody\n")

    with collect_xprompt_load_issues() as issues:
        xprompt = load_xprompt_from_file(path)

    assert xprompt is None
    assert [issue.kind for issue in issues] == [RESERVED_MEMORY_NAMESPACE_ISSUE_KIND]


def test_config_xprompt_cannot_claim_memory_namespace() -> None:
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    with collect_xprompt_load_issues() as issues:
        parsed = parse_xprompt_entries({"memory/foo": "body"}, "config")

    assert parsed == {}
    assert [issue.kind for issue in issues] == [RESERVED_MEMORY_NAMESPACE_ISSUE_KIND]


def test_expansion_requires_memory_prefix_and_recurses_without_children(
    tmp_path: Path,
    home_root: Path,
) -> None:
    project = tmp_path / "repo"
    _write(project / "sase" / "memory" / "foo.md", _memory_note("Foo #memory/bar\n"))
    _write(project / "sase" / "memory" / "bar.md", _memory_note("Bar\n"))
    catalog = load_memory_xprompts(project_root=project, home_root=home_root)

    expanded = process_xprompt_references_with_catalog(
        "#memory/foo and #foo",
        catalog,
    )

    assert expanded == "Foo Bar\n\n and #foo"
    assert "## Children" not in expanded


def test_memory_expansion_does_not_append_audit_events(
    tmp_path: Path,
    home_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    _write(project / "sase" / "memory" / "foo.md", _memory_note("Foo\n"))
    monkeypatch.chdir(project)
    log_path = memory_read_log_path(cwd=project)
    assert not log_path.exists()

    expanded = process_xprompt_references_with_catalog(
        "#memory/foo",
        load_memory_xprompts(project_root=project, home_root=home_root),
    )

    assert expanded == "Foo\n"
    assert not log_path.exists()


def test_get_all_xprompts_loads_selected_registered_project_memory(
    tmp_path: Path,
    home_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tmp_path / "current"
    selected = tmp_path / "selected"
    _write(current / "sase" / "memory" / "foo.md", _memory_note("current\n"))
    _write(selected / "sase" / "memory" / "foo.md", _memory_note("selected\n"))
    monkeypatch.chdir(current)
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "current")
    monkeypatch.setattr(
        "sase.xprompt.loader.known_project_namespaces",
        lambda: {"selected": selected},
    )

    xprompts = get_all_xprompts(project="selected")

    assert xprompts["memory/foo"].content == "selected\n"


def test_direct_lookup_and_trace_include_memory_metadata(
    tmp_path: Path,
    home_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    _write(project / "sase" / "memory" / "foo.md", _memory_note("Foo\n"))
    monkeypatch.chdir(project)

    xprompt = get_xprompt_or_workflow("memory/foo")
    trace = ExpansionTrace()
    expanded = process_xprompt_references_with_catalog(
        "#memory/foo",
        get_all_xprompts(),
        trace=trace,
    )

    assert xprompt is not None
    assert getattr(xprompt, "memory_type", None) == "long"
    assert expanded == "Foo\n"
    assert [(record.name, record.source_path) for record in trace.records] == [
        ("memory/foo", str(project / "sase" / "memory" / "foo.md"))
    ]


def test_memory_type_propagates_to_converted_workflow() -> None:
    workflow = xprompt_to_workflow(
        XPrompt(name="memory/foo", content="Foo", memory_type="long")
    )

    assert workflow.memory_type == "long"
