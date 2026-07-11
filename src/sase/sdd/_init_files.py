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
