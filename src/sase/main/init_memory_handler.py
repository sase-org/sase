"""Handler for the ``sase init memory`` command."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi

_COMMAND_LABEL = "init memory"
_PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
_PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
_MINIMAL_AGENTS_CONTENT = "# Agent Instructions\n\n@memory/short/sase.md\n"
_AT_REF_RE = re.compile(r"(?:^|(?<=\s)|(?<=[\"'`(]))@([^\s,;:()[\]{}\"'`]+)")
_MEMORY_PATH_RE = re.compile(
    r"(?<![\w./-])(memory/(?:short|long)/[^\s,;:()[\]{}\"'`]+?\.md)"
)


@dataclass(frozen=True)
class _SiblingMemoryEntry:
    name: str
    description: str


@dataclass(frozen=True)
class _MemoryRootResult:
    root: Path
    written_paths: tuple[Path, ...]
    unreferenced: tuple[Path, ...]


def _home_root_path(use_chezmoi: bool) -> Path:
    """Return the home-level root for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME
    return Path.home()


def _home_memory_path(use_chezmoi: bool) -> Path:
    """Return the home-level short memory target for the active config mode."""
    return _home_root_path(use_chezmoi) / "memory" / "short" / "sase.md"


def _global_config_path(use_chezmoi: bool) -> Path:
    """Return the global config source path for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    return CONFIG_DIR / "sase.yml"


def _project_config_path() -> Path:
    return Path.cwd() / "sase.yml"


def _load_yaml_mapping(path: Path) -> tuple[Mapping[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return {}, f"{path}: failed to parse YAML: {exc}"
    except OSError as exc:
        return {}, f"{path}: failed to read file: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, Mapping):
        return {}, f"{path}: expected a YAML mapping at the top level"
    return data, None


def _sibling_entries_from_config(
    config_path: Path, *, label: str
) -> tuple[tuple[_SiblingMemoryEntry, ...], tuple[str, ...]]:
    config, load_error = _load_yaml_mapping(config_path)
    if load_error is not None:
        return (), (load_error,)

    raw = config.get("sibling_repos", [])
    if raw is None:
        return (), ()
    if not isinstance(raw, list):
        return (), (f"{config_path}: sibling_repos must be a list",)

    entries: list[_SiblingMemoryEntry] = []
    errors: list[str] = []
    for index, item in enumerate(raw):
        prefix = f"{config_path}: sibling_repos[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix} is missing required string field 'name'")
            continue

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(
                f"{prefix} ({name.strip()!r}) is missing required string "
                "field 'description'"
            )
            continue

        entries.append(
            _SiblingMemoryEntry(
                name=name.strip(),
                description=" ".join(description.strip().split()),
            )
        )

    if errors:
        errors.insert(
            0,
            f"{_COMMAND_LABEL}: cannot generate {label} memory until "
            "sibling repo descriptions are complete",
        )
    return tuple(entries), tuple(errors)


def _render_sase_memory(entries: Iterable[_SiblingMemoryEntry]) -> str:
    lines = [
        "# SASE Memory",
        "",
        "## Sibling Repositories",
        "",
    ]
    entries = tuple(entries)
    if entries:
        lines.append("Configured sibling repositories for this context:")
        lines.append("")
        for entry in entries:
            lines.append(f"- `{entry.name}`: {entry.description}")
    else:
        lines.append("No sibling repositories are configured for this context.")

    lines.extend(
        [
            "",
            "When a sibling repository needs changes, agents MUST run:",
            "",
            "```bash",
            "sase workspace open -p <sibling_repo> <workspace_num>",
            "```",
            "",
            "`<workspace_num>` must be the workspace number assigned to the primary repo. Use the path printed by",
            "`sase workspace open` as the only repository path for sibling edits.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_memory_readme() -> str:
    return (
        "# SASE Memory\n\n"
        "The `memory/` directory holds agent-facing project context.\n\n"
        "- `memory/short/` contains always-loaded context referenced from "
        "`AGENTS.md`.\n"
        "- `memory/long/` contains detailed context that must be reachable "
        "from `AGENTS.md` directly or through another\n"
        "  referenced memory file.\n"
    )


def _write_text_if_changed(path: Path, content: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _ensure_agents_file(root: Path) -> Path | None:
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        return None
    agents_path.write_text(_MINIMAL_AGENTS_CONTENT, encoding="utf-8")
    return agents_path


def _ensure_provider_shims(root: Path) -> list[Path]:
    written: list[Path] = []
    for filename in _PROVIDER_SHIM_FILES:
        path = root / filename
        if _write_text_if_changed(path, _PROVIDER_SHIM_CONTENT):
            written.append(path)
    return written


def _initialize_memory_root(
    root: Path, sibling_entries: Iterable[_SiblingMemoryEntry]
) -> _MemoryRootResult:
    written: list[Path] = []

    (root / "memory" / "short").mkdir(parents=True, exist_ok=True)
    (root / "memory" / "long").mkdir(parents=True, exist_ok=True)

    memory_path = root / "memory" / "short" / "sase.md"
    if _write_text_if_changed(memory_path, _render_sase_memory(sibling_entries)):
        written.append(memory_path)

    readme_path = root / "memory" / "README.md"
    if _write_text_if_changed(readme_path, _render_memory_readme()):
        written.append(readme_path)

    agents_path = _ensure_agents_file(root)
    if agents_path is not None:
        written.append(agents_path)
    written.extend(_ensure_provider_shims(root))

    return _MemoryRootResult(
        root=root,
        written_paths=tuple(written),
        unreferenced=_unreferenced_memory_files(root),
    )


def _memory_files(root: Path) -> set[Path]:
    memory_root = root / "memory"
    results: set[Path] = set()
    for tier in ("short", "long"):
        tier_root = memory_root / tier
        if not tier_root.exists():
            continue
        results.update(
            path.resolve(strict=False)
            for path in tier_root.rglob("*.md")
            if path.is_file()
        )
    return results


def _extract_reference_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _AT_REF_RE.finditer(text):
        token = match.group(1).rstrip(".,;:!?)")
        if token:
            tokens.append(token)
    for match in _MEMORY_PATH_RE.finditer(text):
        token = match.group(1).rstrip(".,;:!?)")
        if token:
            tokens.append(token)
    return tokens


def _resolve_reference(root: Path, source: Path, token: str) -> Path | None:
    if token.startswith(("http://", "https://")):
        return None

    expanded = Path(token).expanduser()
    candidates: list[Path]
    if expanded.is_absolute():
        candidates = [expanded]
    elif token.startswith(("./", "../")):
        candidates = [source.parent / expanded]
    else:
        candidates = [root / expanded, source.parent / expanded]

    root_resolved = root.resolve(strict=False)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _referenced_files_from(root: Path, source: Path) -> set[Path]:
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return set()

    refs: set[Path] = set()
    for token in _extract_reference_tokens(text):
        resolved = _resolve_reference(root, source, token)
        if resolved is not None:
            refs.add(resolved)
    return refs


def _reachable_memory_files(root: Path) -> set[Path]:
    agents_path = (root / "AGENTS.md").resolve(strict=False)
    if not agents_path.exists():
        return set()

    memory_files = _memory_files(root)
    reachable: set[Path] = set()
    visited: set[Path] = {agents_path}
    queue = list(_referenced_files_from(root, agents_path))

    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        if path in memory_files:
            reachable.add(path)
            queue.extend(_referenced_files_from(root, path))

    return reachable


def _unreferenced_memory_files(root: Path) -> tuple[Path, ...]:
    memory_files = _memory_files(root)
    reachable = _reachable_memory_files(root)
    return tuple(sorted(memory_files - reachable, key=lambda path: path.as_posix()))


def _print_config_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(error, file=sys.stderr)


def _print_validation_errors(results: Iterable[_MemoryRootResult]) -> None:
    printed = False
    for result in results:
        if not result.unreferenced:
            continue
        if not printed:
            print(
                f"{_COMMAND_LABEL}: unreferenced memory files were found",
                file=sys.stderr,
            )
            printed = True
        print(f"  {result.root}:", file=sys.stderr)
        for path in result.unreferenced:
            try:
                display = path.relative_to(result.root.resolve(strict=False))
            except ValueError:
                display = path
            print(f"    - {display}", file=sys.stderr)


def _deploy_to_chezmoi(written_paths: Iterable[Path]) -> int:
    paths = tuple(written_paths)
    if not paths:
        return 0

    git_root = CHEZMOI_HOME.parent
    repo_check = subprocess.run(
        ["git", "-C", str(git_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repo_check.returncode != 0:
        print(
            f"{_COMMAND_LABEL}: {git_root} is not a git repo",
            file=sys.stderr,
        )
        return 1

    for path in paths:
        subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            check=False,
        )

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        check=False,
    )
    if staged.returncode != 0:
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "commit",
                "-m",
                "chore: initialize sase memory",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            print(
                f"{_COMMAND_LABEL}: chezmoi commit failed: {commit.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        first_line = (
            commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
        )
        if first_line:
            print(f"  {first_line}")

    try:
        apply_result = subprocess.run(
            ["chezmoi", "apply", "--force"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{_COMMAND_LABEL}: chezmoi not found on PATH", file=sys.stderr)
        return 1

    if apply_result.returncode != 0:
        print(
            f"{_COMMAND_LABEL}: chezmoi apply --force failed: "
            f"{apply_result.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    return 0


def handle_init_memory_command(args: argparse.Namespace) -> None:
    """Handle the ``sase init memory`` command."""
    del args

    use_chezmoi = get_use_chezmoi()
    project_config = _project_config_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries, project_errors = _sibling_entries_from_config(
        project_config, label="project"
    )
    home_entries, home_errors = _sibling_entries_from_config(
        global_config, label="home"
    )
    config_errors = (*project_errors, *home_errors)
    if config_errors:
        _print_config_errors(config_errors)
        sys.exit(1)

    project_result = _initialize_memory_root(Path.cwd(), project_entries)
    home_result = _initialize_memory_root(_home_root_path(use_chezmoi), home_entries)
    results = (project_result, home_result)

    if any(result.unreferenced for result in results):
        _print_validation_errors(results)
        sys.exit(1)

    print(f"{_COMMAND_LABEL}: initialized memory")
    print(f"  project memory target: {Path.cwd() / 'memory' / 'short' / 'sase.md'}")
    print(f"  home memory target: {_home_memory_path(use_chezmoi)}")
    print(f"  global config source: {global_config}")

    exit_code = 0
    if use_chezmoi:
        exit_code = _deploy_to_chezmoi(home_result.written_paths)
    sys.exit(exit_code)
