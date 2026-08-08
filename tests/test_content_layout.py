from pathlib import Path

import pytest

from sase.content_layout import (
    LayoutCollisionError,
    _resolve_content_layout,
    chezmoi_source_path,
    discover_project_root,
    display_path,
    resolve_memory_file_sources,
    resolve_project_layout,
    resolve_xprompt_file_sources,
)
from sase.core.paths import shorten_path


def test_project_home_and_chezmoi_named_paths_are_canonical() -> None:
    layout = _resolve_content_layout(
        project_root="/workspace/demo",
        home_root="/home/alice",
        chezmoi_source_root="/dotfiles/home",
        project="demo",
    )

    assert layout.schema_version == 5
    assert layout.project is not None
    project = layout.project
    assert project.config.canonical.path == Path("/workspace/demo/sase/sase.yml")
    assert project.config.write_path == project.config.canonical.path
    assert project.config.legacy[0].path == Path("/workspace/demo/sase.yml")
    assert project.xprompts.canonical.path == Path("/workspace/demo/sase/xprompts")
    assert tuple(entry.path for entry in project.xprompts.legacy) == (
        Path("/workspace/demo/.xprompts"),
        Path("/workspace/demo/xprompts"),
    )
    assert project.skills.path == Path("/workspace/demo/sase/skills")
    assert project.memory.canonical.path == Path("/workspace/demo/sase/memory")
    assert project.repos.path == Path("/workspace/demo/sase/repos")

    assert layout.home.xprompts.canonical.path == Path("/home/alice/sase/xprompts")
    assert layout.home.skills.path == Path("/home/alice/sase/skills")
    assert layout.home.memory.canonical.path == Path("/home/alice/sase/memory")
    assert layout.home.global_config.path == Path("/home/alice/.config/sase/sase.yml")
    assert layout.chezmoi is not None
    assert layout.chezmoi.xprompts.canonical.path == Path(
        "/dotfiles/home/sase/xprompts"
    )
    assert layout.chezmoi.skills.path == Path("/dotfiles/home/sase/skills")
    assert layout.chezmoi.memory.canonical.path == Path("/dotfiles/home/sase/memory")
    assert layout.chezmoi.global_config.path == Path(
        "/dotfiles/home/dot_config/sase/sase.yml"
    )
    assert layout.skill_sources[-1].id == "package_skills"
    assert layout.skill_sources[-1].locator == "package:xprompts/skills"


def test_path_classes_separate_tracked_generated_and_runtime_content() -> None:
    project = resolve_project_layout("/repo", home_root="/home/alice")

    assert project.config.canonical.tracking == "source_controlled"
    assert project.xprompts.canonical.tracking == "source_controlled"
    assert project.memory.canonical.tracking == "source_controlled"
    assert project.repos.tracking == "runtime_only"
    assert project.memory_readme.tracking == "generated"
    assert {entry.path.name for entry in project.agent_documents} == {
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "OPENCODE.md",
        "QWEN.md",
    }
    assert all(entry.tracking == "generated" for entry in project.agent_documents)


def test_missing_project_root_keeps_home_layout_available() -> None:
    layout = _resolve_content_layout(home_root="/home/alice")

    assert layout.project is None
    assert layout.home.namespace_root.path == Path("/home/alice/sase")
    assert layout.xprompt_sources[0].id == "home_canonical"
    assert all(
        not source.id.startswith("project_") for source in layout.xprompt_sources
    )


def test_legacy_only_config_is_read_but_writes_stay_canonical(
    tmp_path: Path,
) -> None:
    project = resolve_project_layout(tmp_path)
    legacy = project.config.legacy[0].path
    legacy.write_text("key: legacy\n")

    assert project.config.resolve_read("project config") == legacy
    assert project.config.write_path == tmp_path / "sase" / "sase.yml"


@pytest.mark.parametrize("field", ["config", "memory"])
def test_exclusive_content_reports_canonical_legacy_collision(
    tmp_path: Path,
    field: str,
) -> None:
    project = resolve_project_layout(tmp_path)
    compatible = getattr(project, field)
    canonical, legacy = compatible.candidates
    if field == "config":
        canonical.parent.mkdir(parents=True)
        canonical.write_text("canonical: true\n")
        legacy.write_text("legacy: true\n")
    else:
        canonical.mkdir(parents=True)
        legacy.mkdir()

    with pytest.raises(LayoutCollisionError, match="multiple canonical/legacy") as exc:
        compatible.resolve_read(f"project {field}")

    assert exc.value.paths == (canonical, legacy)


def test_xprompt_directories_use_canonical_first_wins(tmp_path: Path) -> None:
    project = resolve_project_layout(tmp_path)
    for candidate in project.xprompts.candidates:
        candidate.mkdir(parents=True, exist_ok=True)

    resolution = project.xprompts.resolve()

    assert resolution.collision is False
    assert resolution.selected == tmp_path / "sase" / "xprompts"
    assert resolution.shadowed == (
        tmp_path / ".xprompts",
        tmp_path / "xprompts",
    )


def test_xprompt_priority_contract_covers_every_source_and_shared_steps() -> None:
    layout = _resolve_content_layout(
        project_root="/repo",
        home_root="/home/alice",
        project="demo",
    )

    assert [source.id for source in layout.xprompt_sources] == [
        "project_canonical",
        "project_legacy_hidden",
        "project_legacy_visible",
        "home_canonical",
        "home_legacy_hidden",
        "home_legacy_visible",
        "home_project_canonical",
        "home_project_legacy_config",
        "project_config_canonical",
        "project_config_legacy",
        "user_config_overlays",
        "user_config",
        "plugin_config",
        "package_default_config",
        "plugin_resources",
        "package_defaults",
        "package_internal",
    ]
    assert [source.priority for source in layout.xprompt_sources] == list(range(1, 18))
    for source in layout.xprompt_sources[:8]:
        assert source.formats == ("md", "yml", "yaml")
        assert source.path is not None
        assert source.steps_path == source.path / "steps"
    assert layout.xprompt_sources[8].collision_group == "project_config"
    assert layout.xprompt_sources[8].collision_policy == "error"
    assert layout.xprompt_sources[10].ordering == "reverse_lexical_first_wins"
    assert layout.xprompt_sources[-1].steps_locator == "package:xprompts/steps"


def test_memory_source_contract_orders_project_before_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    home.mkdir()
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    sources = resolve_memory_file_sources(project_root=project, project="demo")

    assert [source.id for source in sources] == [
        "project_memory",
        "home_memory",
    ]
    assert [source.root for source in sources] == [project, home]
    assert [source.paths.write_path for source in sources] == [
        project / "sase" / "memory",
        home / "sase" / "memory",
    ]
    assert [source.formats for source in sources] == [("md",), ("md",)]


def test_discover_project_root_from_nested_and_missing_descendants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "package"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()

    assert discover_project_root(nested) == root
    assert discover_project_root(nested / "deleted" / "child") == root


def test_discover_project_root_resolves_symlinked_working_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "real" / "repo"
    nested = root / "src"
    nested.mkdir(parents=True)
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text("project: true\n")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    assert discover_project_root(alias / "src") == root.resolve()
    assert (
        display_path(
            alias / "src" / "module.py",
            project_root=alias,
            home_root=tmp_path / "home",
        )
        == "src/module.py"
    )


def test_deleted_cwd_degrades_to_home_only_xprompt_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def deleted_cwd(cls: type[Path]) -> Path:
        raise FileNotFoundError("cwd was removed")

    monkeypatch.setattr(Path, "cwd", classmethod(deleted_cwd))

    assert discover_project_root() is None
    assert all(
        not source.id.startswith("project_")
        for source in resolve_xprompt_file_sources(home_root=tmp_path)
    )


def test_chezmoi_remap_handles_canonical_legacy_and_external_paths() -> None:
    home = Path("/home/alice")
    source = Path("/dotfiles/home")

    assert (
        chezmoi_source_path(
            home / "sase" / "memory" / "note.md",
            home_root=home,
            source_root=source,
        )
        == source / "sase" / "memory" / "note.md"
    )
    assert (
        chezmoi_source_path(
            home / ".xprompts" / "ship.md",
            home_root=home,
            source_root=source,
        )
        == source / "dot_xprompts" / "ship.md"
    )
    assert chezmoi_source_path(
        "/workspace/sase/sase.yml",
        home_root=home,
        source_root=source,
    ) == Path("/workspace/sase/sase.yml")


def test_display_and_shorten_paths_only_replace_a_true_home_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path("/home/alice")

    assert display_path(home / "sase" / "memory", home_root=home) == ("~/sase/memory")
    assert display_path("/home/alice-other/file", home_root=home) == (
        "/home/alice-other/file"
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert shorten_path("/home/alice/sase/sase.yml") == "~/sase/sase.yml"
    assert shorten_path("/home/alice-other/sase.yml") == ("/home/alice-other/sase.yml")
