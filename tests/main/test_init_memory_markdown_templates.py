"""Tests for generated ``sase/memory/*.md`` Markdown templates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd._agents_doc import parse_amd_agents_document
from sase.amd.init import plan_amd_memory_sync
from sase.main import init_memory_handler
from sase.main.init_memory.root_rendering import (
    generated_long_notes,
    render_generated_beads_memory_content,
)
from sase.memory.notes import (
    GeneratedLongMemoryNote,
    MemoryNote,
    parse_memory_note_text,
    render_children_section,
)
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    write,
)


def _sase_template(marker: str = "Custom SASE frame.") -> str:
    return f"""# Custom SASE

{marker}

{{% if project_name %}}
## Project `{{{{ project_name }}}}`
{{% endif %}}

## Repositories

{{{{ linked_repo_entries }}}}
"""


def _readme_template(marker: str = "Custom README frame.") -> str:
    return f"""# Custom Memory README

{marker}

{{% if memory_notes %}}
{{{{ memory_notes }}}}
{{% endif %}}

## Counts

- Total: {{{{ total_notes }}}}
- Short: {{{{ short_notes }}}}
- Long: {{{{ long_notes }}}}
- Lines: {{{{ total_lines }}}}
- Tokens: {{{{ total_tokens }}}}
"""


def _patch_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    use_chezmoi: bool = False,
) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=use_chezmoi,
    )
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    return project_root, home_root, config_dir


def test_default_beads_template_renders_canonical_long_note() -> None:
    content, error = render_generated_beads_memory_content()

    assert error is None
    assert content is not None
    relative_path = "sase/memory/sase_beads.md"
    note = parse_memory_note_text(content, relative_path)
    assert note.type == "long"
    assert note.parent == "AGENTS.md"
    assert note.description
    assert generated_long_notes(content)[relative_path].description == note.description
    assert generated_long_notes(content)[relative_path].parent == "AGENTS.md"


def test_generated_child_long_note_metadata_renders_single_pass(
    tmp_path: Path,
) -> None:
    write(tmp_path / "sase.yml", 'memory:\n  h1_title: "Managed Instructions"\n')
    write(
        tmp_path / "sase" / "memory" / "parent.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: Parent.\n---\n# Parent\n",
    )
    parent = parse_memory_note_text(
        (tmp_path / "sase" / "memory" / "parent.md").read_text(encoding="utf-8"),
        "sase/memory/parent.md",
    )
    generated = GeneratedLongMemoryNote(
        description="Generated child.",
        parent="sase/memory/parent.md",
    )
    generated_child = MemoryNote(
        path=Path("sase/memory/generated_child.md"),
        type="long",
        parent=generated.parent,
        description=generated.description,
        body="",
        frontmatter={},
        type_source="frontmatter",
        parent_source="frontmatter",
    )

    plan = plan_amd_memory_sync(
        tmp_path,
        generated_short_notes={},
        generated_long_notes={"sase/memory/generated_child.md": generated},
    )

    assert plan.blockers == ()
    assert plan.agents_content is not None
    assert "**`sase/memory/parent.md`**" in plan.agents_content
    assert "sase/memory/generated_child.md" not in plan.agents_content
    assert render_children_section((parent, generated_child), parent) == (
        "## Children\n\n"
        "The below files contain detailed reference material. When working in their "
        "domain, you\n"
        "MUST use your `/sase_memory_read` skill to review their contents. Do not "
        "read canonical\n"
        "memory files directly.\n\n"
        "**`sase/memory/generated_child.md`**  \n"
        "Generated child.\n"
    )


def test_root_memory_templates_beat_user_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, home_root, config_dir = _patch_roots(tmp_path, monkeypatch)
    write(config_dir / "memory-sase.template.md", _sase_template("User SASE."))
    write(
        config_dir / "memory-README.template.md",
        _readme_template("User README."),
    )
    write(
        home_root / "sase.yml",
        "memory_sase_template: templates/sase.md\n"
        "memory_readme_template: templates/readme.md\n",
    )
    write(home_root / "templates" / "sase.md", _sase_template("Root SASE."))
    write(
        home_root / "templates" / "readme.md",
        _readme_template("Root README."),
    )

    assert run_handler() == 0

    sase_memory = (home_root / "sase" / "memory" / "sase.md").read_text(
        encoding="utf-8"
    )
    readme = (home_root / "sase" / "memory" / "README.md").read_text(encoding="utf-8")
    assert "Root SASE." in sase_memory
    assert "User SASE." not in sase_memory
    assert "Root README." in readme
    assert "User README." not in readme


def test_user_memory_templates_resolve_from_chezmoi_source_config_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, _home_root, _config_dir = _patch_roots(
        tmp_path, monkeypatch, use_chezmoi=True
    )
    chezmoi_home = tmp_path / "chezmoi" / "home"
    chezmoi_home.mkdir(parents=True)
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)
    source_config_dir = chezmoi_home / "dot_config" / "sase"
    write(
        source_config_dir / "memory-sase.template.md",
        _sase_template("Chezmoi SASE."),
    )
    write(
        source_config_dir / "memory-README.template.md",
        _readme_template("Chezmoi README."),
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_handler() == 0

    assert "Chezmoi SASE." in (chezmoi_home / "sase" / "memory" / "sase.md").read_text()
    assert (
        "Chezmoi README."
        in (chezmoi_home / "sase" / "memory" / "README.md").read_text()
    )
    assert chezmoi_home / "sase" / "memory" / "sase.md" in deployed


def test_nested_memory_sase_and_readme_templates_override_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        "memory:\n"
        "  sase_template: templates/sase.md\n"
        "  readme_template: templates/readme.md\n",
    )
    write(project_root / "templates" / "sase.md", _sase_template("Nested SASE."))
    write(
        project_root / "templates" / "readme.md",
        _readme_template("Nested README."),
    )

    assert run_handler() == 0

    sase_memory = (project_root / "sase" / "memory" / "sase.md").read_text(
        encoding="utf-8"
    )
    readme = (project_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "Nested SASE." in sase_memory
    assert "Nested README." in readme


def test_default_sase_template_names_linked_and_sidecar_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        """
is_sase_managed: true
linked_repos:
  - name: core
    path: ../core
    description: Shared core.
""",
    )

    assert run_handler() == 0

    memory = (project_root / "sase" / "memory" / "sase.md").read_text(encoding="utf-8")
    assert "Configured linked and sidecar repositories for this context:" in memory


@pytest.mark.parametrize(
    ("key", "filename", "template", "expected_error"),
    [
        (
            "memory_sase_template",
            "sase.md",
            "# SASE\n\n{{ project_name }}\n",
            "template must contain {{ linked_repo_entries }}",
        ),
        (
            "memory_sase_template",
            "sase.md",
            "{% if %}\n",
            "template error",
        ),
        (
            "memory_sase_template",
            "sase.md",
            _sase_template("{{ unknown_value }}"),
            "unknown template placeholder {{ unknown_value }}",
        ),
        (
            "memory_readme_template",
            "readme.md",
            _readme_template().replace("{{ total_tokens }}", "missing"),
            "template must contain {{ total_tokens }}",
        ),
        (
            "memory_readme_template",
            "readme.md",
            "{% if %}\n",
            "template error",
        ),
        (
            "memory_readme_template",
            "readme.md",
            _readme_template("{{ unknown_value }}"),
            "unknown template placeholder {{ unknown_value }}",
        ),
    ],
)
def test_invalid_memory_template_blocks_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    filename: str,
    template: str,
    expected_error: str,
) -> None:
    project_root, home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        f"is_sase_managed: true\n{key}: templates/{filename}\n",
    )
    write(project_root / "templates" / filename, template)

    plan = plan_memory()

    assert any(expected_error in blocker for blocker in plan.blockers)
    assert run_handler() == 1
    assert not (project_root / "sase" / "memory").exists()
    assert not (home_root / "sase" / "memory").exists()


@pytest.mark.parametrize(
    "invalid_heading",
    ["# A second title", "#### Too Deep"],
)
def test_invalid_sase_template_structure_blocks_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_heading: str,
) -> None:
    project_root, home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nmemory_sase_template: templates/sase.md\n",
    )
    write(
        project_root / "templates" / "sase.md",
        _sase_template(invalid_heading),
    )

    plan = plan_memory()

    assert any("short memory note" in blocker for blocker in plan.blockers)
    assert run_handler() == 1
    assert not (project_root / "sase" / "memory").exists()
    assert not (home_root / "sase" / "memory").exists()


def test_custom_sase_template_round_trips_into_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        'memory:\n  h1_title: "Project Instructions"\n'
        "memory_sase_template: templates/sase.md\n",
    )
    write(project_root / "templates" / "sase.md", _sase_template())

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    parsed = parse_amd_agents_document(agents)
    assert parsed.short_memory_paths == ("sase/memory/sase.md",)
    assert "Custom SASE frame." in agents
    assert plan_memory().actions == ()
