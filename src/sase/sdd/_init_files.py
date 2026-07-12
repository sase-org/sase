"""Generated SDD guide files and init planning."""

from importlib import resources
from pathlib import Path

from sase.sdd._paths import resolve_sdd_asset_path, resolve_sdd_readme_path
from sase.sdd._types import (
    SddExpectedBytesFile,
    SddExpectedTextFile,
    SddInitAction,
    SddInitOperation,
)

SDD_DIRECTORY_MAP_FILENAME = "sdd-directory-map.png"
SDD_DIRECTORY_MAP_RELATIVE_PATH = f"assets/{SDD_DIRECTORY_MAP_FILENAME}"
SDD_COMPANION_KINDS = ("plans", "research")
SDD_COMPANION_DIRECTORY_MAP_FILENAMES = {
    "plans": "plans-directory-map.png",
    "research": "research-directory-map.png",
}

SDD_README_CONTENT = """# Structured Development Docs

This SDD root keeps durable planning context close to the code it describes. It stores prompts, approved plans, roadmap
material, and bead state in predictable paths so humans and agents can reference the same artifacts over time. The root
may be the checkout's `sdd/` directory or a separate `.sase/sdd/` store; run `sase sdd path` or read `SASE_SDD_DIR` from
agent environments to locate it.

![SDD directory map](assets/sdd-directory-map.png)

## Directory Layout

- `plans/` stores implementation plans. Each `plans/<YYYYMM>/prompts/` subdirectory stores the original user prompts or
  expanded prompt snapshots that led to that month's plans. Plan files require `tier: tale` for focused task plans or
  `tier: epic` for larger multi-phase plans.
- `research/` stores exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- `beads/` stores bead issue data for SDD-backed work tracking.

Prompt, plan, and research files are normally organized under a `YYYYMM/` month directory relative to this root. For
example, a prompt at `plans/202605/prompts/example.md` pairs with `plans/202605/example.md`, while research lives at
`research/202605/example.md`. Prompt files should link to their generated plan-like artifact with frontmatter such as
`plan: plans/202605/example.md`; the plan-like artifact should link back with
`prompt: plans/202605/prompts/example.md`.

## Commands

- `sase sdd list` lists SDD markdown artifacts.
- `sase sdd path` prints the effective SDD root; pass a kind such as `research` to print that child directory.
- `sase sdd validate` checks frontmatter links between prompts and plan-like artifacts.
- `sase sdd repair-links` infers and repairs missing bidirectional links.
- `sase plan search` searches these `sdd/` plans and the machine-local `~/.sase/plans/` archive by content.
- `sase bead` manages SDD bead issues and epic work.

## Compatibility

The canonical top-level directories are `plans/`, `research/`, and `beads/`. Prompt snapshots live under
`plans/<YYYYMM>/prompts/`. Historical top-level `prompts/` and `specs/` aliases remain readable during migration, but
new snapshots are written only to the nested layout.
"""

SDD_DIRECTORY_README_CONTENT = {
    "plans": """# Plans

The `plans/` directory stores implementation plans. Every plan must declare a plan-file `tier` in YAML frontmatter:
`tale` for focused task plans or `epic` for larger work that may span multiple phases or beads. This plan-file tier is
separate from bead tier metadata. Each month directory may contain a `prompts/` subdirectory holding the prompt
snapshots paired with that month's plans.
""",
    "research": """# Research

The `research/` directory stores exploratory findings, prior art, options, critiques, and recommendations that inform
later tales, epics, or implementation work.
""",
}

SDD_COMPANION_README_CONTENT = {
    "plans": """# SASE Plans

This public companion repository stores the durable planning state for its SASE-managed source repository. SASE
automatically clones it into each workspace and keeps plan files, their original prompt snapshots, and bead state
available to humans and agents.

![Plans directory map](assets/plans-directory-map.png)

## Directory Layout

- `<YYYYMM>/*.md` stores plan files. Every plan declares `tier: tale` or `tier: epic` in YAML frontmatter.
- `<YYYYMM>/prompts/*.md` stores the original prompts or expanded snapshots that produced that month's plans.
- `beads/` stores SASE bead events and compatibility projections. SQLite `beads.db*` files are local-only.
- `assets/` stores generated explanatory media used by this README.

Plan and prompt links are relative to this repository root. For example, `202607/example.md` links back to
`202607/prompts/example.md`.

## Commands

- `sase plan list` and `sase plan search` inspect plans.
- `sase sdd path plans` prints this clone's root.
- `sase sdd validate` checks prompt and plan frontmatter links.
- `sase bead` manages bead work stored under `beads/`.
""",
    "research": """# SASE Research

This public companion repository stores durable research for its SASE-managed source repository. It is cloned lazily
when research is requested, keeping exploratory findings and generated media separate from implementation plans.

![Research directory map](assets/research-directory-map.png)

## Directory Layout

- `<YYYYMM>/*.md` stores research notes organized by month.
- `<YYYYMM>/*_infographic.png` stores generated infographics beside the reports they explain.
- `<YYYYMM>/<topic>/` may store research-swarm drafts such as `<topic>__a.md`, `<topic>__b.md`, and the consolidated
  `<topic>.md` report.
- `assets/` stores generated explanatory media used by this README.

Research should record the question, evidence, alternatives, and a clear recommendation. Follow-up work from
`#research/more` extends the existing report and preserves its established organization and source conventions.

## Commands

- `sase sdd path research --ensure` materializes this clone and prints its root.
- `sase sdd list` lists durable SDD artifacts.
- `#research`, `#research/more`, and `#research_swarm` create or extend research under the current month.
""",
}


def expected_sdd_readme(
    path: str | None = None, *, cwd: Path | None = None
) -> SddExpectedTextFile:
    """Return the canonical top-level SDD README target and content."""
    return SddExpectedTextFile(
        path=resolve_sdd_readme_path(path, cwd=cwd),
        content=SDD_README_CONTENT,
    )


def expected_sdd_directory_readmes(
    path: str | None = None, *, cwd: Path | None = None
) -> tuple[SddExpectedTextFile, ...]:
    """Return canonical SDD directory README targets and contents."""
    sdd_root = resolve_sdd_readme_path(path, cwd=cwd).parent
    return tuple(
        SddExpectedTextFile(path=sdd_root / dirname / "README.md", content=content)
        for dirname, content in SDD_DIRECTORY_README_CONTENT.items()
    )


def expected_sdd_text_files(
    path: str | None = None, *, cwd: Path | None = None
) -> tuple[SddExpectedTextFile, ...]:
    """Return all canonical generated SDD text files."""
    return (
        expected_sdd_readme(path, cwd=cwd),
        *expected_sdd_directory_readmes(path, cwd=cwd),
    )


def expected_sdd_directory_map(
    path: str | None = None, *, cwd: Path | None = None
) -> SddExpectedBytesFile:
    """Return the canonical SDD directory map target and PNG bytes."""
    return SddExpectedBytesFile(
        path=resolve_sdd_asset_path(path, cwd=cwd),
        content=read_sdd_directory_map_bytes(),
    )


def expected_sdd_companion_files(
    kind: str, root: str | Path
) -> tuple[SddExpectedTextFile | SddExpectedBytesFile, ...]:
    """Return deterministic generated files for one split companion root."""

    _validate_companion_kind(kind)
    companion_root = Path(root)
    filename = SDD_COMPANION_DIRECTORY_MAP_FILENAMES[kind]
    return (
        SddExpectedTextFile(
            path=companion_root / "README.md",
            content=SDD_COMPANION_README_CONTENT[kind],
        ),
        SddExpectedBytesFile(
            path=companion_root / "assets" / filename,
            content=_read_sdd_companion_directory_map_bytes(kind),
        ),
    )


def plan_sdd_companion_init_actions(
    kind: str, root: str | Path
) -> tuple[SddInitAction, ...]:
    """Plan generated README and asset drift for one split companion."""

    actions: list[SddInitAction] = []
    for expected in expected_sdd_companion_files(kind, root):
        operation = (
            planned_text_operation(expected.path, expected.content)
            if isinstance(expected, SddExpectedTextFile)
            else planned_bytes_operation(expected.path, expected.content)
        )
        if operation is not None:
            actions.append(
                SddInitAction(
                    path=expected.path,
                    operation=operation,
                    detail=f"{kind} companion {expected.path.name}",
                    new_content=expected.content,
                )
            )
    return tuple(actions)


def ensure_sdd_companion_initialized(kind: str, root: str | Path) -> tuple[Path, ...]:
    """Refresh deterministic generated files for one split companion."""

    actions = plan_sdd_companion_init_actions(kind, root)
    for action in actions:
        action.path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(action.new_content, bytes):
            action.path.write_bytes(action.new_content)
        else:
            assert isinstance(action.new_content, str)
            action.path.write_text(action.new_content, encoding="utf-8")
    return tuple(action.path for action in actions)


def expected_sdd_generated_paths(
    path: str | None = None, *, cwd: Path | None = None
) -> tuple[Path, ...]:
    """Return all generated SDD init paths for *path*."""
    text_paths = tuple(
        expected_file.path for expected_file in expected_sdd_text_files(path, cwd=cwd)
    )
    return (
        *text_paths,
        expected_sdd_directory_map(path, cwd=cwd).path,
    )


def plan_sdd_init_actions(
    path: str | None = None, *, cwd: Path | None = None
) -> tuple[SddInitAction, ...]:
    """Return missing/stale generated SDD files without writing anything."""
    actions: list[SddInitAction] = []
    for expected_file in expected_sdd_text_files(path, cwd=cwd):
        operation = planned_text_operation(expected_file.path, expected_file.content)
        if operation is not None:
            actions.append(
                SddInitAction(
                    path=expected_file.path,
                    operation=operation,
                    detail=sdd_init_detail_for_path(expected_file.path),
                    new_content=expected_file.content,
                )
            )

    expected_map = expected_sdd_directory_map(path, cwd=cwd)
    operation = planned_bytes_operation(expected_map.path, expected_map.content)
    if operation is not None:
        actions.append(
            SddInitAction(
                path=expected_map.path,
                operation=operation,
                detail="directory map asset",
                new_content=expected_map.content,
            )
        )

    return tuple(actions)


def ensure_sdd_initialized(
    path: str | Path | None = None, *, cwd: Path | None = None
) -> tuple[Path, ...]:
    """Create or refresh generated SDD guide files only when they drift."""
    path_arg = str(path) if path is not None else None
    actions = plan_sdd_init_actions(path_arg, cwd=cwd)
    if not actions:
        return ()
    write_sdd_readme(path_arg, cwd=cwd)
    return tuple(action.path for action in actions)


def write_sdd_readme(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Create or refresh the canonical SDD README and return its path."""
    readme = expected_sdd_readme(path, cwd=cwd)
    for expected_file in expected_sdd_text_files(path, cwd=cwd):
        expected_file.path.parent.mkdir(parents=True, exist_ok=True)
        expected_file.path.write_text(expected_file.content, encoding="utf-8")
    write_sdd_directory_map(expected_sdd_directory_map(path, cwd=cwd))
    return readme.path


def write_sdd_directory_map(expected_file: SddExpectedBytesFile) -> None:
    expected_file.path.parent.mkdir(parents=True, exist_ok=True)
    expected_file.path.write_bytes(expected_file.content)


def read_sdd_directory_map_bytes() -> bytes:
    source = resources.files("sase.sdd").joinpath("assets", SDD_DIRECTORY_MAP_FILENAME)
    with resources.as_file(source) as source_path:
        return source_path.read_bytes()


def _read_sdd_companion_directory_map_bytes(kind: str) -> bytes:
    """Read the packaged directory-map placeholder for one companion."""

    _validate_companion_kind(kind)
    source = resources.files("sase.sdd").joinpath(
        "assets", SDD_COMPANION_DIRECTORY_MAP_FILENAMES[kind]
    )
    with resources.as_file(source) as source_path:
        return source_path.read_bytes()


def _validate_companion_kind(kind: str) -> None:
    if kind not in SDD_COMPANION_KINDS:
        raise ValueError(f"unknown SDD companion kind: {kind}")


def planned_text_operation(
    path: Path, expected_content: str
) -> SddInitOperation | None:
    if not path.exists():
        return "create"
    try:
        return (
            None if path.read_text(encoding="utf-8") == expected_content else "update"
        )
    except OSError:
        return "update"
    except UnicodeDecodeError:
        return "update"


def planned_bytes_operation(
    path: Path, expected_content: bytes
) -> SddInitOperation | None:
    if not path.exists():
        return "create"
    try:
        return None if path.read_bytes() == expected_content else "update"
    except OSError:
        return "update"


def sdd_init_detail_for_path(path: Path) -> str:
    if path.name == "README.md" and path.parent.name == "sdd":
        return "top-level README"
    return "directory README"
