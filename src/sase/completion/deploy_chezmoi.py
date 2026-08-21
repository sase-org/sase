"""Render generated completion scripts into a chezmoi source tree."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sase
from sase.completion.emit_bash import emit_bash
from sase.completion.emit_fish import emit_fish
from sase.completion.emit_zsh import emit_zsh
from sase.completion.install_stamp import InstallStamp, OWNER_CHEZMOI
from sase.completion.install_targets import SUPPORTED_SHELLS, script_path
from sase.config.core import CHEZMOI_HOME
from sase.content_layout import chezmoi_source_path
from sase.main._init_chezmoi_deploy import ChezmoiDeployBehavior, deploy_to_chezmoi

DeployFn = Callable[[tuple[Path, ...], ChezmoiDeployBehavior], int]


@dataclass(frozen=True, slots=True)
class _ChezmoiCompletionFile:
    """One generated completion source file and its applied home target."""

    shell: str
    target: Path
    source: Path
    text: str


@dataclass(frozen=True, slots=True)
class _ChezmoiCompletionPlan:
    """All files needed for chezmoi-managed shell completion."""

    files: tuple[_ChezmoiCompletionFile, ...]
    stamp_files: tuple[_ChezmoiCompletionFile, ...]

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(file.source for file in (*self.files, *self.stamp_files))

    def paths_and_text(self) -> tuple[tuple[Path, str], ...]:
        """Return source path / content pairs for writing this plan."""
        return tuple(
            (file.source, file.text) for file in (*self.files, *self.stamp_files)
        )


@dataclass(frozen=True, slots=True)
class _ChezmoiCompletionDeployResult:
    """Outcome of rendering and optionally deploying completion sources."""

    plan: _ChezmoiCompletionPlan
    written_paths: tuple[Path, ...]
    exit_code: int


def _build_chezmoi_completion_plan(
    *,
    source_root: Path = CHEZMOI_HOME,
    home: Path | None = None,
    version: str | None = None,
    timestamp: str | None = None,
) -> _ChezmoiCompletionPlan:
    """Build the source files for chezmoi-managed completion deployment."""
    from sase.completion.build import build_spec

    spec = build_spec()
    digest = spec.structural_digest()
    home_path = Path.home() if home is None else home
    version_value = sase.__version__ if version is None else version
    timestamp_value = _utc_timestamp() if timestamp is None else timestamp
    emitters = {
        "bash": emit_bash,
        "fish": emit_fish,
        "zsh": emit_zsh,
    }

    files: list[_ChezmoiCompletionFile] = []
    stamp_files: list[_ChezmoiCompletionFile] = []
    for shell in SUPPORTED_SHELLS:
        target = _target_path(shell, home_path)
        source = chezmoi_source_path(
            target,
            home_root=home_path,
            source_root=source_root,
        )
        files.append(
            _ChezmoiCompletionFile(
                shell=shell,
                target=target,
                source=source,
                text=emitters[shell](spec),
            )
        )

        stamp = InstallStamp(
            shell=shell,
            version=version_value,
            digest=digest,
            target=str(target),
            timestamp=timestamp_value,
            owner=OWNER_CHEZMOI,
        )
        stamp_target = home_path / ".sase" / "completion" / "stamp" / f"{shell}.json"
        stamp_source = chezmoi_source_path(
            stamp_target,
            home_root=home_path,
            source_root=source_root,
        )
        stamp_files.append(
            _ChezmoiCompletionFile(
                shell=shell,
                target=stamp_target,
                source=stamp_source,
                text=json.dumps(stamp.to_json(), indent=2, sort_keys=True) + "\n",
            )
        )

    return _ChezmoiCompletionPlan(files=tuple(files), stamp_files=tuple(stamp_files))


def deploy_chezmoi_completion(
    *,
    dry_run: bool = False,
    no_apply: bool = False,
    no_commit: bool = False,
    no_push: bool = False,
    source_root: Path = CHEZMOI_HOME,
    home: Path | None = None,
    deploy_fn: DeployFn = deploy_to_chezmoi,
) -> _ChezmoiCompletionDeployResult:
    """Render completion files and optionally deploy them through chezmoi."""
    plan = _build_chezmoi_completion_plan(source_root=source_root, home=home)
    if dry_run:
        return _ChezmoiCompletionDeployResult(plan, written_paths=(), exit_code=0)

    _write_files(plan.paths_and_text())
    exit_code = deploy_fn(
        plan.paths,
        ChezmoiDeployBehavior(
            command_label="completion deploy-chezmoi",
            commit_message="chore: deploy sase completion scripts",
            auto_commit_type="init",
            chezmoi_home=source_root,
            no_apply=no_apply,
            no_commit=no_commit,
            no_push=no_push,
            apply_when_nothing_staged=True,
        ),
    )
    return _ChezmoiCompletionDeployResult(
        plan,
        written_paths=plan.paths,
        exit_code=exit_code,
    )


def _target_path(shell: str, home: Path) -> Path:
    directories = {
        "bash": home / ".local" / "share" / "bash-completion" / "completions",
        "fish": home / ".config" / "fish" / "completions",
        "zsh": home / ".zfunc",
    }
    return script_path(directories[shell], shell)


def _write_files(files: Iterable[tuple[Path, str]]) -> None:
    for path, text in files:
        _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text if text.endswith("\n") else f"{text}\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "deploy_chezmoi_completion",
]
