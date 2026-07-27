"""Generated SDD guide files and init planning."""

from pathlib import Path

from sase.directory_map_assets import read_directory_map_asset
from sase.mdtemplates import packaged_markdown_text
from sase.sdd._paths import resolve_sdd_asset_path, resolve_sdd_readme_path
from sase.sdd._types import (
    SddExpectedBytesFile,
    SddExpectedTextFile,
    SddInitAction,
    SddInitOperation,
)

SDD_DIRECTORY_MAP_FILENAME = "sdd-directory-map.png"
SDD_DIRECTORY_MAP_RELATIVE_PATH = f"assets/{SDD_DIRECTORY_MAP_FILENAME}"
SDD_SIDECAR_KINDS = ("plans", "research")
SDD_SIDECAR_GUIDE_KINDS = ("plans", "research", "beads")
SDD_SIDECAR_DIRECTORY_MAP_FILENAMES = {
    "plans": "plans-directory-map.png",
    "research": "research-directory-map.png",
    "beads": "beads-directory-map.png",
}
AGENTS_SIDECAR_SCHEMA = (
    '{"authority":"owner-sharded","format":"sase-agents-sidecar",'
    '"relationship_schema_version":2,"schema_version":2}\n'
)


def _read_sdd_markdown(filename: str) -> str:
    return packaged_markdown_text("sase.sdd", f"templates/{filename}")


def expected_sdd_readme(
    path: str | None = None, *, cwd: Path | None = None
) -> SddExpectedTextFile:
    """Return the canonical top-level SDD README target and content."""
    return SddExpectedTextFile(
        path=resolve_sdd_readme_path(path, cwd=cwd),
        content=_read_sdd_markdown("README.md"),
    )


def expected_sdd_directory_readmes(
    path: str | None = None, *, cwd: Path | None = None
) -> tuple[SddExpectedTextFile, ...]:
    """Return canonical SDD directory README targets and contents."""
    sdd_root = resolve_sdd_readme_path(path, cwd=cwd).parent
    return tuple(
        SddExpectedTextFile(
            path=sdd_root / dirname / "README.md",
            content=_read_sdd_markdown(f"{dirname}-README.md"),
        )
        for dirname in SDD_SIDECAR_KINDS
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


def expected_sdd_sidecar_files(
    kind: str,
    root: str | Path,
    *,
    description: str | None = None,
) -> tuple[SddExpectedTextFile | SddExpectedBytesFile, ...]:
    """Return deterministic generated files for one sidecar root.

    The plans, research, and beads roles use illustrated guide templates,
    while agents receives its privacy-forward bundle scaffold.
    Custom roles receive a small deterministic README so repo init can seed
    arbitrary configured sidecars without inventing role-specific layouts.
    """

    sidecar_root = Path(root)
    if kind == "agents":
        return (
            SddExpectedTextFile(
                path=sidecar_root / "README.md",
                content=_read_sdd_markdown("sidecar-agents-README.md"),
            ),
            SddExpectedTextFile(
                path=sidecar_root / "schema.json",
                content=AGENTS_SIDECAR_SCHEMA,
            ),
            SddExpectedTextFile(
                path=sidecar_root / "agents" / ".gitkeep",
                content="",
            ),
            SddExpectedTextFile(
                path=sidecar_root / "families" / ".gitkeep",
                content="",
            ),
            SddExpectedTextFile(
                path=sidecar_root / "users" / ".gitkeep",
                content="",
            ),
        )
    if kind not in SDD_SIDECAR_GUIDE_KINDS:
        return (
            SddExpectedTextFile(
                path=sidecar_root / "README.md",
                content=_generic_sidecar_readme(kind, description),
            ),
        )
    filename = SDD_SIDECAR_DIRECTORY_MAP_FILENAMES[kind]
    return (
        SddExpectedTextFile(
            path=sidecar_root / "README.md",
            content=_read_sdd_markdown(f"sidecar-{kind}-README.md"),
        ),
        SddExpectedBytesFile(
            path=sidecar_root / "assets" / filename,
            content=_read_sdd_sidecar_directory_map_bytes(kind),
        ),
    )


def plan_sdd_sidecar_init_actions(
    kind: str,
    root: str | Path,
    *,
    description: str | None = None,
) -> tuple[SddInitAction, ...]:
    """Plan generated README and asset drift for one split sidecar."""

    actions: list[SddInitAction] = []
    for expected in expected_sdd_sidecar_files(
        kind,
        root,
        description=description,
    ):
        if (
            kind == "agents"
            and expected.path.name == "README.md"
            and _agents_sidecar_has_publication(Path(root))
        ):
            # Root and nested browsing pages are derived from owner manifests.
            # Once populated, repo init must not replace those rendered views.
            continue
        if kind == "agents" and expected.path.name == ".gitkeep":
            parent = expected.path.parent
            try:
                populated = parent.is_dir() and any(parent.iterdir())
            except OSError:
                populated = True
            if populated and not expected.path.exists():
                continue
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
                    detail=f"{kind} sidecar {expected.path.name}",
                    new_content=expected.content,
                )
            )
    return tuple(actions)


def _agents_sidecar_has_publication(root: Path) -> bool:
    try:
        return any(root.glob("users/*/machines/*/manifest.json"))
    except OSError:
        return True


def ensure_sdd_sidecar_initialized(
    kind: str,
    root: str | Path,
    *,
    description: str | None = None,
) -> tuple[Path, ...]:
    """Refresh deterministic generated files for one sidecar."""

    actions = plan_sdd_sidecar_init_actions(
        kind,
        root,
        description=description,
    )
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
    return read_directory_map_asset("sase.sdd", SDD_DIRECTORY_MAP_FILENAME)


def _read_sdd_sidecar_directory_map_bytes(kind: str) -> bytes:
    """Read the packaged directory-map placeholder for one sidecar."""

    _validate_sidecar_kind(kind)
    return read_directory_map_asset(
        "sase.sdd",
        SDD_SIDECAR_DIRECTORY_MAP_FILENAMES[kind],
    )


def _validate_sidecar_kind(kind: str) -> None:
    if kind not in SDD_SIDECAR_GUIDE_KINDS:
        raise ValueError(f"unknown SDD sidecar kind: {kind}")


def _generic_sidecar_readme(kind: str, description: str | None) -> str:
    title = kind.replace("-", " ").replace("_", " ").strip().title() or "Sidecar"
    purpose = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else "This repository stores durable resources for its SASE-managed source repository."
    )
    return (
        f"# SASE {title}\n\n"
        f"{purpose}\n\n"
        "This repository is managed as a SASE sidecar and is cloned below "
        f"`sase/repos/{kind}` in project workspaces.\n"
    )


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
