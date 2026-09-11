"""Shared completion-install result models and callback types."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.completion.install_stamp import InstallStamp
from sase.completion.install_targets import DetectedShell, TargetChoice


RECOMMENDED_ZSTYLE = """\
# Recommended compsys styles for sase (grouped, described, menu-selected):
zstyle ':completion:*' menu select
zstyle ':completion:*' group-name ''
zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'
zstyle ':completion:*' verbose yes
zstyle ':completion:*' list-grouped true
zstyle ':completion:*' use-cache on
"""

EmitFn = Callable[[str], tuple[str, str]]
ExpectedFn = Callable[[Sequence[str]], Mapping[str, "ExpectedCompletion"]]
ZcompileFn = Callable[[Path], None]
VerifyFn = Callable[[], str | None]
WritableFn = Callable[[Path], bool]


@dataclass(frozen=True, slots=True)
class InstallStep:
    """One reported step of an install or dry-run."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Outcome of ``sase completion install``."""

    shell: DetectedShell
    target: TargetChoice
    script: Path
    steps: tuple[InstallStep, ...]
    stamp: InstallStamp | None
    registered: bool | None
    fpath_hint: str | None
    ok: bool
    exit_code: int


@dataclass(frozen=True, slots=True)
class ShellInstallStatus:
    """Resolved ``sase completion list`` row for one shell."""

    shell: str
    generator: bool
    status: str
    path: str | None
    zwc: str
    stamp_version: str | None
    owner: str | None
    drift_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpectedCompletion:
    """Current generated completion script and structural digest for one shell."""

    script: str
    digest: str


@dataclass(frozen=True, slots=True)
class RefreshShellOutcome:
    """One shell's result from the update-time refresh hook."""

    shell: str
    ok: bool
    detail: str
    target: str | None


@dataclass(frozen=True, slots=True)
class CompletionRefreshReport:
    """Result of the ``sase update`` completion refresh."""

    attempted: bool
    outcomes: tuple[RefreshShellOutcome, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "shells": [
                {
                    "detail": outcome.detail,
                    "ok": outcome.ok,
                    "shell": outcome.shell,
                    "target": outcome.target,
                }
                for outcome in self.outcomes
            ],
        }
