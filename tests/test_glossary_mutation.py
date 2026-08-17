"""Tests for the shared glossary add/delete engine."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.content_layout import resolve_project_config_write_path
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.mutation import (
    GlossaryConflictError,
    GlossaryMutationError,
    GlossaryValidationError,
    add_glossary_term,
    delete_glossary_term,
)
from sase.glossary.resolution import GlossaryLookupError
from sase.xprompt import glossary_catalog as catalog_mod

_SORTED_GLOSSARY = """# keep this comment
timezone: UTC  # tz
memory:
  h1_title: Demo
  glossary:
    Alpha:
      definition: >-
        First term stands alone.
    Gamma:
      aliases:
        - g
      definition: >-
        Third term mentions Alpha.
"""


def _record(
    project_name: str,
    workspace: Path,
    *,
    display_name: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def _install_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str | None,
    *,
    key: str = "gh_demo__app",
    display_name: str = "demo",
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config_path = resolve_project_config_write_path(workspace)
    if body is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(body, encoding="utf-8")
    record = _record(key, workspace, display_name=display_name)
    monkeypatch.setattr(
        catalog_mod, "list_project_records", lambda *_a, **_kw: [record]
    )
    return config_path


def test_add_creates_first_term_without_existing_glossary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        "# keep this comment\ntimezone: UTC  # tz\n",
    )

    outcome = add_glossary_term(
        "demo", "Widget Box", "A container for widgets.", aliases=("box",)
    )

    assert outcome.created_section is True
    assert outcome.project_name == "demo"
    assert outcome.term == "Widget Box"
    assert outcome.aliases == ("box",)
    assert outcome.config_path == str(config_path)
    text = config_path.read_text(encoding="utf-8")
    assert "# keep this comment" in text
    assert "# tz" in text
    assert "timezone: UTC" in text
    loaded = yaml.safe_load(text)
    assert loaded["memory"]["glossary"]["Widget Box"]["definition"].startswith(
        "A container"
    )
    assert loaded["memory"]["glossary"]["Widget Box"]["aliases"] == ["box"]
    assert "definition: >-" in text


def test_add_into_sorted_map_lands_in_sorted_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    original = config_path.read_text(encoding="utf-8")

    outcome = add_glossary_term("demo", "Beta", "The middle term.")

    assert outcome.created_section is False
    text = config_path.read_text(encoding="utf-8")
    keys = list(yaml.safe_load(text)["memory"]["glossary"])
    assert keys == ["Alpha", "Beta", "Gamma"]
    assert "# keep this comment" in text
    assert "# tz" in text
    assert "h1_title: Demo" in text
    assert "timezone: UTC" in text
    alpha_block = original[original.index("    Alpha:") : original.index("    Gamma:")]
    assert alpha_block in text
    gamma_block = original[original.index("    Gamma:") :]
    assert gamma_block in text
    assert "    Beta:\n" in text
    assert "definition: >-" in text


def test_add_with_aliases_writes_alias_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)

    outcome = add_glossary_term(
        "demo",
        "Delta",
        "A fourth term.",
        aliases=("d", "fourth"),
    )

    assert outcome.aliases == ("d", "fourth")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["memory"]["glossary"]["Delta"]["aliases"] == ["d", "fourth"]


def test_add_duplicate_term_rejects_and_leaves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    original = config_path.read_bytes()

    with pytest.raises(GlossaryValidationError) as exc:
        add_glossary_term("demo", "Alpha", "A colliding definition.")

    assert exc.value.diagnostics
    assert all(item.severity == "error" for item in exc.value.diagnostics)
    assert config_path.read_bytes() == original


def test_add_alias_colliding_with_existing_term_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    original = config_path.read_bytes()

    with pytest.raises(GlossaryValidationError) as exc:
        add_glossary_term("demo", "Other", "Collides via alias.", aliases=("Alpha",))

    assert exc.value.diagnostics
    assert config_path.read_bytes() == original


def test_add_rejects_blank_newline_and_separator_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)

    with pytest.raises(GlossaryMutationError, match="nonblank"):
        add_glossary_term("demo", "   ", "A definition.")
    with pytest.raises(GlossaryMutationError, match="single-line"):
        add_glossary_term("demo", "Bad\nTerm", "A definition.")
    with pytest.raises(GlossaryMutationError, match="separators"):
        add_glossary_term("demo", "---", "A definition.")


def test_delete_by_exact_term_alias_and_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)

    by_alias = delete_glossary_term("demo", "g")
    assert by_alias.term == "Gamma"
    assert by_alias.aliases == ("g",)
    assert by_alias.referenced_by == ()
    assert "Gamma" not in yaml.safe_load(config_path.read_text())["memory"]["glossary"]
    assert "sase glossary add" in by_alias.restore_command
    assert "-a g" in by_alias.restore_command
    assert "-p demo" in by_alias.restore_command

    add_glossary_term("demo", "Widget Box", "A unique box.")
    by_prefix = delete_glossary_term("demo", "widget b")
    assert by_prefix.term == "Widget Box"

    exact_path = _install_project(
        tmp_path / "exact",
        monkeypatch,
        _SORTED_GLOSSARY,
    )
    by_term = delete_glossary_term("demo", "Alpha")
    assert by_term.term == "Alpha"
    assert by_term.referenced_by == ("Gamma",)
    assert "Alpha" not in yaml.safe_load(exact_path.read_text())["memory"]["glossary"]


def test_delete_unknown_term_raises_lookup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)

    with pytest.raises(
        GlossaryLookupError, match="unknown glossary term: xyzzy"
    ) as exc:
        delete_glossary_term("demo", "xyzzy")
    assert exc.value.candidates == ()


def test_delete_preserves_unrelated_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    original = config_path.read_text(encoding="utf-8")
    gamma_start = original.index("    Gamma:")

    delete_glossary_term("demo", "Gamma")

    written = config_path.read_text(encoding="utf-8")
    assert written == original[:gamma_start]
    assert "# keep this comment" in written
    assert "timezone: UTC  # tz" in written
    assert "    Alpha:" in written
    assert "Gamma" not in written


def test_conflict_raises_and_leaves_file_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.glossary import mutation as mutation_mod

    config_path = _install_project(tmp_path, monkeypatch, _SORTED_GLOSSARY)
    real_read = mutation_mod._read_optional_bytes
    calls = {"n": 0}

    def flaky_read(path: Path) -> bytes | None:
        data = real_read(path)
        calls["n"] += 1
        if calls["n"] == 1 and path == config_path:
            config_path.write_text("changed: true\n", encoding="utf-8")
        return data

    monkeypatch.setattr(mutation_mod, "_read_optional_bytes", flaky_read)

    with pytest.raises(GlossaryConflictError, match="reload and retry"):
        add_glossary_term("demo", "Beta", "The middle term.")

    assert config_path.read_text(encoding="utf-8") == "changed: true\n"


def test_unknown_project_and_delete_without_glossary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(
        tmp_path,
        monkeypatch,
        "timezone: UTC\n",
        display_name="demo",
    )

    with pytest.raises(GlossaryCliError, match="did not resolve"):
        add_glossary_term("missing", "Term", "A definition.")
    with pytest.raises(GlossaryCliError, match="no glossary configured"):
        delete_glossary_term("demo", "Term")


def test_add_missing_config_file_creates_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, None)

    outcome = add_glossary_term("demo", "First", "The first term.")

    assert outcome.created_section is True
    assert config_path.is_file()
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["memory"]["glossary"]["First"]["definition"] == "The first term."
    assert "definition: >-" in config_path.read_text(encoding="utf-8")
