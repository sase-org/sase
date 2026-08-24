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
    render_generated_project_long_memory_contents,
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


def _readme_template(
    marker: str = "Custom README frame.",
    *,
    legacy_counts: bool = False,
) -> str:
    core_count = "short_notes" if legacy_counts else "core_notes"
    reference_count = "long_notes" if legacy_counts else "reference_notes"
    return f"""# Custom Memory README

{marker}

{{% if memory_notes %}}
{{{{ memory_notes }}}}
{{% endif %}}

## Counts

- Total: {{{{ total_notes }}}}
- Core: {{{{ {core_count} }}}}
- Reference: {{{{ {reference_count} }}}}
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


def _generated_project_note(relative_path: str) -> str:
    contents, error = render_generated_project_long_memory_contents()
    assert error is None
    return contents[relative_path]


def test_default_beads_template_renders_canonical_long_note() -> None:
    content = _generated_project_note("sase/memory/sase_beads.md")

    relative_path = "sase/memory/sase_beads.md"
    note = parse_memory_note_text(content, relative_path)
    assert note.type == "reference"
    assert note.parent == "AGENTS.md"
    assert note.description
    generated = generated_long_notes({relative_path: content})[relative_path]
    assert generated.description == note.description
    assert generated.parent == "AGENTS.md"


def test_default_artifacts_template_renders_canonical_long_note() -> None:
    content = _generated_project_note("sase/memory/sase_artifacts.md")

    relative_path = "sase/memory/sase_artifacts.md"
    note = parse_memory_note_text(content, relative_path)
    assert note.type == "reference"
    assert note.parent == "AGENTS.md"
    assert note.description
    generated = generated_long_notes({relative_path: content})[relative_path]
    assert generated.description == note.description
    assert generated.parent == "AGENTS.md"


def test_plus_one_close_boundary_guidance_stays_current() -> None:
    generated = _generated_project_note("sase/memory/sase_beads.md")
    docs = Path("docs/beads.md").read_text(encoding="utf-8")
    generated_flat = " ".join(generated.split())
    docs_flat = " ".join(docs.split())

    stale_phrases = (
        "valid +1 to an `open` or `closed` task atomically promotes it to `ready`",
        "Adding new evidence to an `open` draft or `closed` task atomically promotes",
        "New evidence promotes `open` and `closed` tasks to `ready`",
        "Draft and closed tasks are promoted to ready",
    )
    for content in (generated_flat, docs_flat):
        for phrase in stale_phrases:
            assert phrase not in content
    for required in (
        "closed task promotes only when the reporter's observation window starts "
        "strictly after the current close",
        "Stale-window evidence is recorded, but the close remains standing",
        "`--verified-after-close` only for an actual reproduction on a tree that "
        "already contains the close",
    ):
        assert required in generated_flat
    for required in (
        "Closed tasks promote only when the report's `observed_since` window starts "
        "strictly after the current close",
        "`+1 after close` badge",
        "`recorded_after_current_close` boolean",
        "`--verified-after-close` asserts that the defect was reproduced on a tree "
        "already containing the close",
    ):
        assert required in docs_flat


def test_default_sizes_template_renders_canonical_child_long_note() -> None:
    content = _generated_project_note("sase/memory/sase_sizes.md")

    relative_path = "sase/memory/sase_sizes.md"
    note = parse_memory_note_text(content, relative_path)
    assert note.type == "reference"
    assert note.parent == "sase/memory/sase_beads.md"
    assert note.description
    generated = generated_long_notes({relative_path: content})[relative_path]
    assert generated.description == note.description
    assert generated.parent == "sase/memory/sase_beads.md"


def test_generated_project_long_notes_omit_feature_flags() -> None:
    contents, error = render_generated_project_long_memory_contents()

    assert error is None
    assert "sase/memory/sase_flags.md" not in contents
    assert set(contents) == {
        "sase/memory/sase_artifacts.md",
        "sase/memory/sase_beads.md",
        "sase/memory/sase_sizes.md",
    }


def test_generated_child_long_note_metadata_renders_single_pass(
    tmp_path: Path,
) -> None:
    write(tmp_path / "sase.yml", 'memory:\n  h1_title: "Managed Instructions"\n')
    write(
        tmp_path / "sase" / "memory" / "parent.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Parent.\n---\n# Parent\n",
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
        type="reference",
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
    assert "### 2.1 `sase/memory/parent.md`" in plan.agents_content
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


def test_tier2_renders_intro_then_h3_note_entries(tmp_path: Path) -> None:
    write(tmp_path / "sase.yml", 'memory:\n  h1_title: "Managed Instructions"\n')
    write(
        tmp_path / "sase" / "memory" / "parent.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Parent.\n---\n# Parent\n",
    )

    plan = plan_amd_memory_sync(
        tmp_path,
        generated_short_notes={},
        generated_long_notes={},
    )

    assert plan.blockers == ()
    assert plan.agents_content is not None
    content = plan.agents_content
    tier2_index = content.index("## 2. Tier 2 (reference) Memory")
    intro_index = content.index("The below files contain detailed reference material")
    note_index = content.index("### 2.1 `sase/memory/parent.md`")
    assert tier2_index < intro_index < note_index
    between_h2_and_intro = content[
        tier2_index + len("## 2. Tier 2 (reference) Memory") : intro_index
    ]
    assert between_h2_and_intro.strip() == ""
    assert "Long-Term Memory Files" not in content
    assert "Glossary Terms" not in content
    parsed = parse_amd_agents_document(content)
    assert tuple(entry.path for entry in parsed.long_memory_entries) == (
        "sase/memory/parent.md",
    )
    assert parsed.long_memory_entries[0].description == "Parent."


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


def test_readme_template_override_accepts_legacy_count_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, home_root, _config_dir = _patch_roots(tmp_path, monkeypatch)
    write(home_root / "sase.yml", "memory_readme_template: templates/readme.md\n")
    write(
        home_root / "templates" / "readme.md",
        _readme_template("Legacy counts.", legacy_counts=True),
    )

    assert run_handler() == 0

    readme = (home_root / "sase" / "memory" / "README.md").read_text(encoding="utf-8")
    assert "Legacy counts." in readme
    assert "- Core: 1" in readme
    assert "- Reference: 0" in readme


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

    def fake_deploy(paths: Iterable[Path], **_kwargs: object) -> int:
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

    assert any("core memory note" in blocker for blocker in plan.blockers)
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
    assert parsed.short_memory_paths == (
        "sase/memory/sase.md",
        "sase/memory/artifact_relations.md",
        "sase/memory/task_types.md",
    )
    assert "Custom SASE frame." in agents
    assert "/sase_final" not in agents
    assert plan_memory().actions == ()
