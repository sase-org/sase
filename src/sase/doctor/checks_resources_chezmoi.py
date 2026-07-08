"""Chezmoi source-tree checks for ``sase doctor`` resources."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.diagnostics import DiagnosticCheck

type _CommandResolver = Callable[[str], str | None]


def check_chezmoi(
    *,
    use_chezmoi: bool | None = None,
    source_home: Path | None = None,
    command_resolver: _CommandResolver | None = None,
) -> DiagnosticCheck:
    """Check the optional chezmoi source tree used for home-managed files."""
    if use_chezmoi is None:
        use_chezmoi = get_use_chezmoi()
    source_home = source_home or CHEZMOI_HOME
    command_resolver = command_resolver or shutil.which

    source_exists = source_home.exists()
    source_is_dir = source_home.is_dir() if source_exists else False
    command_path = command_resolver("chezmoi")
    source_entry_count = _source_entry_count(source_home) if source_is_dir else None
    data = {
        "use_chezmoi": use_chezmoi,
        "source_path": str(source_home),
        "source_exists": source_exists,
        "source_is_dir": source_is_dir,
        "source_entry_count": source_entry_count,
        "command_found": command_path is not None,
        "command_path": command_path,
    }

    if not use_chezmoi and not source_exists:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="SKIP",
            title="Chezmoi source",
            summary="chezmoi remapping is disabled and no source tree was found",
            data=data,
        )

    problems = _chezmoi_source_problems(
        use_chezmoi=use_chezmoi,
        source_home=source_home,
        source_exists=source_exists,
        source_is_dir=source_is_dir,
        source_entry_count=source_entry_count,
        command_found=command_path is not None,
    )

    if use_chezmoi and command_path is None:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="ERROR",
            title="Chezmoi source",
            summary="use_chezmoi is enabled but the chezmoi command is missing",
            details=tuple(problems),
            next_steps=(
                "Install `chezmoi` or set `use_chezmoi: false` if SASE should write live home files directly.",
            ),
            data=data,
        )

    if problems:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="WARN",
            title="Chezmoi source",
            summary="chezmoi source state needs attention",
            details=tuple(problems),
            next_steps=_chezmoi_next_steps(problems),
            data=data,
        )

    return DiagnosticCheck(
        id="resources.chezmoi",
        group="resources",
        status="OK",
        title="Chezmoi source",
        summary=(
            "chezmoi command and source state look usable"
            if use_chezmoi
            else "chezmoi source tree exists; SASE chezmoi remapping is disabled"
        ),
        data=data,
    )


_check_chezmoi = check_chezmoi


def _chezmoi_source_problems(
    *,
    use_chezmoi: bool,
    source_home: Path,
    source_exists: bool,
    source_is_dir: bool,
    source_entry_count: int | None,
    command_found: bool,
) -> list[str]:
    problems: list[str] = []
    if use_chezmoi and not source_exists:
        problems.append(
            f"`use_chezmoi` is true but the chezmoi source home is missing: {source_home}"
        )
    if source_exists and not source_is_dir:
        problems.append(f"chezmoi source home is not a directory: {source_home}")
    if source_is_dir and source_entry_count == 0:
        problems.append(f"chezmoi source home is empty: {source_home}")
    if source_exists and not command_found:
        problems.append("chezmoi source tree exists but `chezmoi` is not on PATH")
    return problems


def _source_entry_count(source_home: Path) -> int | None:
    try:
        return sum(1 for _entry in source_home.iterdir())
    except OSError:
        return None


def _chezmoi_next_steps(problems: list[str]) -> tuple[str, ...]:
    steps: list[str] = []
    if any("not a directory" in problem for problem in problems):
        steps.append("Move or remove the non-directory chezmoi source path.")
    if any("missing" in problem or "empty" in problem for problem in problems):
        steps.append(
            "Create or restore the chezmoi source tree, then rerun `sase doctor -D`."
        )
    if any("not on PATH" in problem for problem in problems):
        steps.append("Install `chezmoi` or remove the unused source tree.")
    return tuple(steps)
