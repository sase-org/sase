"""Tests for the ``sase memory init`` command."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from sase.amd.constants import (
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
)
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    run_memory,
    write,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _prettier_command() -> list[str]:
    prettier = shutil.which("prettier")
    if prettier is not None:
        return [prettier]
    local_prettier = _REPO_ROOT / "node_modules" / ".bin" / "prettier"
    if local_prettier.exists():
        return [str(local_prettier)]
    pytest.skip("prettier not installed")


def _single_line(text: str) -> str:
    return " ".join(text.split())


_SASE_MEMORY_HEADER = "# SASE = Structured Agentic Software Engineering"


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


def long_note(
    body: str,
    *,
    description: str | None = "Long description.",
    extra_frontmatter: str = "",
) -> str:
    lines = ["---", "type: long", "parent: AGENTS.md"]
    if description is not None:
        lines.append(f"description: {description}")
    if extra_frontmatter:
        lines.extend(extra_frontmatter.strip().splitlines())
    lines.extend(["---", body])
    return "\n".join(lines)


def home_provider_shim_content(root: Path) -> str:
    return f"@{root.resolve(strict=False).as_posix()}/AGENTS.md\n"


def test_init_memory_uses_local_siblings_for_project_and_global_for_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    )

    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../local-core
    description: Local Rust core.
""",
    )
    write(
        config_dir / "sase.yml",
        """
sibling_repos:
  - name: github
    path: /global/github
    description: Global GitHub plugin.
""",
    )

    assert run_handler() == 0
    out = capsys.readouterr().out
    assert "init memory: initialized memory" in out

    project_memory = (project_root / "memory" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "sase.md").read_text()
    assert "`core`: Local Rust core." in project_memory
    assert "`github`: Global GitHub plugin." not in project_memory
    assert "../local-core" not in project_memory
    assert "`github`: Global GitHub plugin." in home_memory
    assert "`core`: Local Rust core." not in home_memory
    assert "/global/github" not in home_memory
    assert _SASE_MEMORY_HEADER in project_memory
    assert _SASE_MEMORY_HEADER in home_memory

    sibling_trigger = (
        "When you need to make changes to files in a numbered-workspace sibling "
        "repository or need to review numbered-workspace sibling repository code, "
        "agents MUST run:"
    )
    for memory in (project_memory, home_memory):
        assert sibling_trigger in _single_line(memory)
        assert "sibling reads/writes" in memory
        assert "When a sibling repository needs changes, agents MUST run:" not in memory
        assert "sibling edits" not in memory

    for root, shim_content in (
        (project_root, PROVIDER_SHIM_CONTENT),
        (home_root, home_provider_shim_content(home_root)),
    ):
        assert not (root / "memory" / "long").exists()
        assert (root / "memory" / "README.md").is_file()
        readme = (root / "memory" / "README.md").read_text()
        assert "`sase memory list`" in readme
        assert "`sase memory init`" in readme
        assert "Non-README Markdown files live directly under `memory/`" in readme
        assert "`type: long` notes are detailed reference material" in readme
        assert "@memory/sase.md" in (root / "AGENTS.md").read_text()
        for filename in PROVIDER_SHIM_FILES:
            assert (root / filename).read_text() == shim_content


def test_init_memory_static_siblings_use_paths_without_workspace_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    static_one = tmp_path / "static-one"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setenv("STATIC_ONE", str(static_one))
    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: dotfiles
    path: $STATIC_ONE
    description: User dotfiles source.
    workspace:
      strategy: none
  - name: notes
    path: ../static-two
    description: Static notes checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    single_line = _single_line(project_memory)
    assert "Static-path sibling repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: User dotfiles source. This repo is defined in the "
        "`$STATIC_ONE/` directory."
    ) in single_line
    assert (
        "- `notes`: Static notes checkout. This repo is defined in the "
        "`../static-two/` directory."
    ) in single_line
    assert (
        'sase workspace open -p <sibling_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )


def test_init_memory_mixed_siblings_render_static_location_and_workspace_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )
    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../sase-core
    description: Numbered Rust core checkout.
  - name: dotfiles
    path: ../dotfiles
    description: Static dotfiles source.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    single_line = _single_line(project_memory)
    assert "Static-path sibling repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: Static dotfiles source. This repo is defined in the "
        "`../dotfiles/` directory."
    ) in single_line
    assert "numbered-workspace sibling repository" in project_memory
    assert (
        'sase workspace open -p <sibling_repo> -r "<reason>" <workspace_num>'
        in project_memory
    )
    assert "numbered-workspace sibling reads/writes" in single_line


def test_init_memory_static_relative_paths_use_configured_display_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_root = tmp_path / "primary" / "project"
    project_root = tmp_path / "managed" / "project_10"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    numbered_relative_path = tmp_path / "managed" / "shared"
    primary_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / ".sase" / "checkout.json",
        f"""
{{
  "project_key": "org/project",
  "project_name": "project",
  "workspace_num": 10,
  "primary_workspace_dir": "{primary_root}",
  "registry_path": "/work/registry.json",
  "schema_version": 1
}}
""",
    )
    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: shared
    path: ../shared
    description: Static shared checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    assert (
        "- `shared`: Static shared checkout. This repo is defined in the "
        "`../shared/` directory."
    ) in _single_line(project_memory)
    assert str((tmp_path / "primary" / "shared").resolve(strict=False)) not in (
        project_memory
    )
    assert str(numbered_relative_path.resolve(strict=False)) not in project_memory
    assert (
        'sase workspace open -p <sibling_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )


def test_init_memory_project_memory_includes_workspace_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "sase.md").read_text()
    assert _SASE_MEMORY_HEADER in project_memory
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "directories are named `project_<N>`" in project_memory
    assert (
        'sase workspace open -p <sibling_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )
    assert (
        'sase workspace open -p <sibling_repo> -r "<reason>" <workspace_num>'
        not in home_memory
    )
    assert "{{ project }}" not in project_memory
    assert "Ephemeral" not in home_memory
    assert _SASE_MEMORY_HEADER in home_memory

    plan_warning = (
        "IMPORTANT: Do NOT mention your workspace directory (or any sibling "
        "workspace directory) in any plan files that you generate using your "
        "`/sase_plan` skill. The agent(s) that implement the plan might not run "
        "in the same workspace directory as you!"
    )
    assert plan_warning in _single_line(project_memory)
    assert "/sase_plan" not in home_memory


def test_init_memory_project_memory_uses_managed_checkout_marker_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project_10"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / ".sase" / "checkout.json",
        """
{
  "project_key": "org/project",
  "project_name": "project",
  "workspace_num": 10,
  "primary_workspace_dir": "/work/project",
  "registry_path": "/work/registry.json",
  "schema_version": 1
}
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "project_10_<N>" not in project_memory


def test_init_memory_reports_missing_sibling_descriptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    )
    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "field 'description'" in err
    assert not (project_root / "memory").exists()


def test_init_memory_overwrites_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )
    write(project_root / "AGENTS.md", "@memory/sase.md\n")
    write(project_root / "CLAUDE.md", "old instructions\n")

    assert run_handler() == 0

    assert (project_root / "CLAUDE.md").read_text() == PROVIDER_SHIM_CONTENT
    for filename in ("GEMINI.md", "QWEN.md", "OPENCODE.md"):
        assert (project_root / filename).read_text() == PROVIDER_SHIM_CONTENT


def test_init_memory_allows_transitive_memory_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )
    write(
        project_root / "AGENTS.md",
        "@memory/sase.md\n\nmemory/index.md\n",
    )
    write(
        project_root / "memory" / "index.md",
        long_note("# Index\n\n@memory/detail.md\n", description="Index."),
    )
    write(
        project_root / "memory" / "detail.md",
        long_note("# Detail\n", description="Detail."),
    )

    assert run_handler() == 0


def test_init_memory_syncs_amd_agents_and_long_memory_descriptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )
    write(project_root / "sase.yml", 'amd_h1_title: "Managed Instructions"\n')
    write(project_root / "memory" / "extra.md", short_note("# Extra\n"))
    write(
        project_root / "memory" / "described.md",
        long_note(
            "# Described\n",
            description="Existing description.",
            extra_frontmatter="keywords:\n  - existing",
        ),
    )
    write(
        project_root / "memory" / "curated.md",
        long_note(
            "# Curated\n\nFallback body should not be used.\n",
            description=None,
        ),
    )
    write(
        project_root / "AGENTS.md",
        "# Previous\n\n"
        "**`memory/curated.md`**  \n"
        "Curated description survives. _Read when touching curated memory._\n",
    )

    assert run_handler() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Managed Instructions\n")
    assert "## Tier 1 (short-term) Memory" in agents
    assert "- @memory/extra.md" in agents
    assert "- @memory/sase.md" in agents
    assert "## Tier 2 (dynamic) Memory" not in agents
    assert "## Dynamic Memory Files" not in agents
    assert "### DYNAMIC MEMORY" not in agents
    assert "## Tier 2 (long-term) Memory" in agents
    assert "## Tier 3 (long-term) Memory" not in agents
    assert "#### Long-Term Memory Files" not in agents
    assert "**`memory/curated.md`**  \nCurated description survives." in agents
    assert "**`memory/described.md`**  \nExisting description." in agents
    assert ("sase-" + "amd:") not in agents

    curated = (project_root / "memory" / "curated.md").read_text(encoding="utf-8")
    assert curated.startswith(
        "---\n"
        "type: long\n"
        "parent: AGENTS.md\n"
        "description: Curated description survives.\n"
        "---\n"
    )
    described = (project_root / "memory" / "described.md").read_text(encoding="utf-8")
    assert "description: Existing description." in described
    assert "keywords:" in described
    assert "  - existing" in described


def test_init_memory_rejects_unreferenced_memory_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    )
    write(project_root / "AGENTS.md", "@memory/sase.md\n")
    # Parented under a memory note that does not exist, so the managed
    # instructions onboarding fallback (which only references short notes and
    # top-level ``parent: AGENTS.md`` long notes) cannot make it reachable.
    write(
        project_root / "memory" / "orphan.md",
        "---\ntype: long\nparent: memory/ghost.md\ndescription: Orphan.\n---\n"
        "# Orphan\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "unreferenced memory files" in err
    assert "memory/orphan.md" in err


def test_init_memory_plan_empty_after_prettier_formats_generated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )
    write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../sase-core
    description: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
""",
    )

    assert run_memory() == 0

    generated = [
        project_root / "memory" / "sase.md",
        project_root / "memory" / "README.md",
        home_root / "memory" / "sase.md",
        home_root / "memory" / "README.md",
    ]
    before = {path: path.read_text(encoding="utf-8") for path in generated}
    result = subprocess.run(
        [
            *_prettier_command(),
            "--write",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --write failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert {path: path.read_text(encoding="utf-8") for path in generated} == before

    plan = plan_memory()
    assert plan.actions == ()
    assert plan.blockers == ()


def test_init_memory_generated_markdown_passes_prettier_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    )

    assert run_memory() == 0

    generated = [
        project_root / "memory" / "sase.md",
        project_root / "memory" / "README.md",
    ]
    assert all(path.read_bytes().endswith(b"\n") for path in generated)
    result = subprocess.run(
        [
            *_prettier_command(),
            "--check",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
