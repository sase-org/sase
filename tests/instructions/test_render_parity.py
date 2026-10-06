"""Render CLI parity: legacy AGENTS.md coverage for fixture shapes and this repo.

Each fixture project shape plus a home is built in tmp with real memory
notes, its legacy ``AGENTS.md`` files are generated with the real
memory-units renderer, and :func:`legacy_parity` must pass for the root
render. Nothing here is committed: no generated fixtures live in the repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.instructions.compile import compile_bundle
from sase.instructions.parity import legacy_parity
from sase.main.parser import create_parser
from tests.instructions.fixture_compiler import (
    core_note,
    make_facts,
    reference_note,
    web_descriptor,
    web_strand,
    write,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def isolated_instructions_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bundle store and render cache at a tmp dir."""
    home = tmp_path / "ihome"
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(home))
    return home


pytestmark = pytest.mark.usefixtures("isolated_instructions_home")


def _patch_global_config(monkeypatch: pytest.MonkeyPatch, base: Path) -> Path:
    """Point the global config at a tmp dir with one home linked repo."""
    config_dir = base / "global-config"
    write(
        config_dir / "sase.yml",
        "repos:\n"
        "  linked:\n"
        "  - name: home-tool\n"
        "    description: Home tooling.\n"
        "    path: ../home-tool\n",
    )
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core.get_use_chezmoi", lambda: False)
    return config_dir


def _write_home(home_root: Path) -> None:
    """Write the shared home shape: title, sase.md, notes, shadowed note."""
    write(home_root / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')
    write(
        home_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture Home\n\nHome contract note.\n"),
    )
    write(
        home_root / "sase" / "memory" / "gotchas.md",
        core_note("# Gotchas\n\nHome gotchas.\n"),
    )
    write(
        home_root / "sase" / "memory" / "home_only.md",
        core_note("# Home Only\n\nHome-only core note.\n"),
    )
    write(
        home_root / "sase" / "memory" / "home_ref.md",
        reference_note("# Home Ref\n\nHome reference.\n", description="Home ref."),
    )
    write(
        home_root / "sase" / "memory" / "home_second_ref.md",
        reference_note(
            "# Second Home Ref\n\nMore home reference.\n",
            description="Second home ref.",
        ),
    )


def _write_webs(project_root: Path, *webs: str) -> None:
    for web in webs:
        write(
            project_root / "sase" / "memory" / f"{web}.md",
            web_descriptor(web.title(), f"Project {web}."),
        )
        write(
            project_root / "sase" / "memory" / web / "first.md",
            web_strand(f"First {web.title()}", f"The first {web} decision."),
        )


def _write_sase_like(project_root: Path) -> None:
    """Configured title, several core notes, refs with a child, webs, repos."""
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\n"
        'memory:\n  h1_title: "Fixture Project Instructions"\n'
        "repos:\n"
        "  linked:\n"
        "  - name: fixture-sidecar\n"
        "    description: Fixture sidecar.\n"
        "    path: ../fixture-sidecar\n"
        "  - name: fixture-docs\n"
        "    description: Fixture docs.\n"
        "    path: ../fixture-docs\n",
    )
    write(
        project_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture\n\nProject contract note.\n"),
    )
    write(
        project_root / "sase" / "memory" / "gotchas.md",
        core_note("# Gotchas\n\nProject gotchas.\n"),
    )
    write(
        project_root / "sase" / "memory" / "cli_rules.md",
        core_note("# CLI Rules\n\nProject CLI rules.\n"),
    )
    write(
        project_root / "sase" / "memory" / "parent.md",
        reference_note("# Parent\n\nParent reference.\n", description="Parent ref."),
    )
    # A flat child note parented at another reference note (like sase_sizes
    # under sase_beads): nested from the reference list, never a web strand
    # directory, so web discovery stays clean.
    write(
        project_root / "sase" / "memory" / "child.md",
        "---\ntype: reference\nparent: sase/memory/parent.md\n"
        "description: Child ref.\n---\n# Child\n\nChild reference.\n",
    )
    write(
        project_root / "sase" / "memory" / "second_ref.md",
        reference_note("# Second\n\nSecond reference.\n", description="Second ref."),
    )
    _write_webs(project_root, "decisions", "glossary", "task_types")


def _write_bob_like(project_root: Path) -> None:
    """Derived title, sase.md only, references, decisions/glossary/task_types."""
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    write(
        project_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture\n\nProject contract note.\n"),
    )
    write(
        project_root / "sase" / "memory" / "notes.md",
        reference_note("# Notes\n\nBob notes.\n", description="Bob notes."),
    )
    _write_webs(project_root, "decisions", "glossary", "task_types")


def _write_act_like(project_root: Path) -> None:
    """Derived title, sase.md, generated references, only the task_types web."""
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    write(
        project_root / "sase" / "memory" / "sase.md",
        core_note("# Fixture\n\nProject contract note.\n"),
    )
    write(
        project_root / "sase" / "memory" / "notes.md",
        reference_note("# Notes\n\nAct notes.\n", description="Act notes."),
    )
    _write_webs(project_root, "task_types")


def _render_legacy_files(
    project_root: Path, home_root: Path, *, project: str, config_dir: Path
) -> None:
    """Generate both legacy AGENTS.md files with the real units renderer."""
    from sase.amd._config import resolve_amd_h1_title
    from sase.amd.memory_units import (
        collect_memory_root_units,
        render_memory_root_units,
    )
    from sase.main.init_memory.config import (
        linked_entries_from_config,
        project_config_read_path,
    )
    from sase.main.init_memory.root_planning import (
        memory_web_root_plan,
        retired_note_relative_paths,
    )
    from sase.main.init_memory.root_rendering_notes import (
        generated_long_notes,
        generated_short_notes,
        render_generated_project_long_memory_contents,
        render_generated_sase_memory_body,
    )
    from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT, memory_read_root

    project_config = project_config_read_path(root=project_root)
    project_entries, project_errors = linked_entries_from_config(
        project_config, label="project", project_name=project
    )
    assert not project_errors, project_errors
    global_config = config_dir / "sase.yml"
    home_entries, home_errors = linked_entries_from_config(global_config, label="home")
    assert not home_errors, home_errors

    merged = list(project_entries)
    names = {entry.name for entry in project_entries}
    for entry in home_entries:
        if entry.name in names:
            continue
        names.add(entry.name)
        merged.append(
            entry.__class__(
                name=entry.name,
                description=f"{entry.description} (home configuration)",
                path=entry.path,
                auto_clone=entry.auto_clone,
            )
        )
    template_body, template_error = render_generated_sase_memory_body(
        project_root, merged, project_name=project
    )
    assert template_body is not None, template_error
    project_title, project_error = resolve_amd_h1_title(
        project_root, derive_project_title=True
    )
    assert project_error is None, project_error
    home_title, home_error = resolve_amd_h1_title(home_root)
    assert home_error is None, home_error

    short_notes = generated_short_notes(template_body)
    project_long_contents, project_long_error = (
        render_generated_project_long_memory_contents()
    )
    assert project_long_error is None, project_long_error
    project_long_notes = generated_long_notes(project_long_contents)

    def _collect(
        root: Path,
        title: str | None,
        entries: tuple,
        config_path: Path,
        *,
        include_project_memory: bool,
    ):
        read_root = memory_read_root(root)
        source_root = (
            read_root
            if read_root is not None
            else root / CANONICAL_MEMORY_RELATIVE_ROOT
        )
        web_plan = memory_web_root_plan(
            root,
            source_memory_root=source_root,
            include_project_memory=include_project_memory,
        )
        assert not web_plan.blockers, web_plan.blockers
        excluded = retired_note_relative_paths(
            root, include_project_memory=include_project_memory
        )
        try:
            linked_source = config_path.relative_to(root).as_posix()
        except ValueError:
            linked_source = config_path.as_posix()
        return collect_memory_root_units(
            root,
            title,
            project_name=project,
            linked_entries=entries,
            linked_entries_source=Path(linked_source) if linked_source else None,
            generated_short_notes=short_notes,
            generated_long_notes=(project_long_notes if include_project_memory else {}),
            generated_web_notes=dict(web_plan.web_note_bodies or {}),
            source_memory_root=None,
            excluded_note_paths=excluded,
        )

    project_units = _collect(
        project_root,
        project_title,
        tuple(project_entries),
        project_config,
        include_project_memory=True,
    )
    home_units = _collect(
        home_root,
        home_title,
        tuple(home_entries),
        global_config,
        include_project_memory=False,
    )
    for root, units in ((project_root, project_units), (home_root, home_units)):
        text, error = render_memory_root_units(units)
        assert text is not None, error
        write(root / "AGENTS.md", text)


def _check_fixture_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    *,
    project: str = "fixture",
) -> None:
    base = tmp_path / shape
    project_root = base / "proj"
    home_root = base / "home"
    config_dir = _patch_global_config(monkeypatch, base)
    _write_home(home_root)
    if shape == "sase-like":
        _write_sase_like(project_root)
    elif shape == "bob-like":
        _write_bob_like(project_root)
    elif shape == "act-like":
        _write_act_like(project_root)
    else:  # pragma: no cover - guarded by the three call sites
        raise AssertionError(f"unknown shape {shape!r}")
    _render_legacy_files(
        project_root, home_root, project=project, config_dir=config_dir
    )
    compiled = compile_bundle(
        make_facts(provider="codex", project=project),
        project_root=project_root,
        home_root=home_root,
    )
    report = legacy_parity(compiled, project_root, home_root)
    assert report.ok, f"{shape}: {report.summary()}\n" + "\n".join(
        issue.detail for issue in report.issues
    )
    assert report.contract_count == 1


def test_parity_sase_shaped_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sase-shaped fixture passes legacy parity for the root render."""
    _check_fixture_shape(tmp_path, monkeypatch, "sase-like")


def test_parity_bob_cli_shaped_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bob-cli-shaped fixture passes legacy parity for the root render."""
    _check_fixture_shape(tmp_path, monkeypatch, "bob-like")


def test_parity_actstat_shaped_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actstat-shaped fixture passes legacy parity for the root render."""
    _check_fixture_shape(tmp_path, monkeypatch, "act-like")


def test_parity_committed_agents_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This checkout's AGENTS.md passes parity with an isolated empty home."""
    home_root = tmp_path / "empty-home"
    home_root.mkdir()
    config_dir = tmp_path / "global-config"
    config_dir.mkdir()
    write(config_dir / "sase.yml", "{}\n")
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core.get_use_chezmoi", lambda: False)

    before = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    ).stdout
    compiled = compile_bundle(
        make_facts(provider="codex", project="sase"),
        project_root=_REPO_ROOT,
        home_root=home_root,
    )
    report = legacy_parity(compiled, _REPO_ROOT, home_root)
    assert report.ok, f"committed AGENTS.md: {report.summary()}\n" + "\n".join(
        issue.detail for issue in report.issues
    )
    after = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    ).stdout
    assert after == before


def test_parity_detects_missing_unit(tmp_path: Path) -> None:
    """A legacy path with no bundle section fails parity as missing."""
    project_root, home_root = tmp_path / "proj", tmp_path / "home"
    empty_proj = tmp_path / "empty-proj"
    project_root.mkdir()
    home_root.mkdir()
    empty_proj.mkdir()
    write(empty_proj / "sase.yml", "is_sase_managed: true\n")
    write(project_root / "AGENTS.md", "## Core Memory\n\n- @memory/ghost.md\n")
    compiled = compile_bundle(
        make_facts(provider="qwen", project="fixture"),
        project_root=empty_proj,
        home_root=home_root,
    )
    report = legacy_parity(compiled, project_root, home_root)
    assert not report.ok
    assert report.missing_sections


def test_render_parser_options_are_alphabetical_with_short_aliases() -> None:
    """Every ``render`` option keeps its short alias."""
    args = create_parser().parse_args(
        [
            "instructions",
            "render",
            "-a",
            "some-agent",
            "-f",
            "provider=codex",
            "-f",
            "mode=export",
            "-j",
            "-N",
            "-p",
            "-s",
        ]
    )
    assert args.instructions_subcommand == "render"
    assert args.agent == "some-agent"
    assert args.fact == ["provider=codex", "mode=export"]
    assert args.json is True
    assert args.no_cache is True
    assert args.parity is True
    assert args.sections is True


def test_render_fact_overrides() -> None:
    """``-f`` accepts comma pairs and implies interactive actors."""
    from sase.main.instructions_handler import _parse_fact_overrides

    assert _parse_fact_overrides(["provider=codex"]) == {"provider": "codex"}
    assert _parse_fact_overrides(["provider=codex,mode=runtime"]) == {
        "provider": "codex",
        "mode": "runtime",
    }
    assert _parse_fact_overrides(["mode=export"]) == {
        "mode": "export",
        "actor": "interactive",
    }
    assert _parse_fact_overrides(["mode=interactive,provider=grok"]) == {
        "mode": "interactive",
        "provider": "grok",
        "actor": "interactive",
    }


def test_render_fact_conflicts_and_unknowns_rejected() -> None:
    """Conflicting actors and unknown facts are render errors."""
    import pytest as _pytest

    from sase.main.instructions_handler import _RenderError, _parse_fact_overrides

    with _pytest.raises(_RenderError, match="requires actor 'interactive'"):
        _parse_fact_overrides(["mode=export", "actor=sase_root"])
    with _pytest.raises(_RenderError, match="unknown fact"):
        _parse_fact_overrides(["nope=x"])
    with _pytest.raises(_RenderError, match="KEY=VALUE"):
        _parse_fact_overrides(["provider"])


__all__ = [
    "test_parity_actstat_shaped_fixture",
    "test_parity_bob_cli_shaped_fixture",
    "test_parity_committed_agents_md",
    "test_parity_detects_missing_unit",
    "test_parity_sase_shaped_fixture",
    "test_render_fact_conflicts_and_unknowns_rejected",
    "test_render_fact_overrides",
    "test_render_parser_options_are_alphabetical_with_short_aliases",
]
