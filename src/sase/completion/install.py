"""Compatibility exports for shell-completion install helpers."""

from __future__ import annotations

from sase.completion.install_flow import install_completion
from sase.completion.install_models import (
    RECOMMENDED_ZSTYLE,
    CompletionRefreshReport,
    ExpectedCompletion,
    InstallResult,
    InstallStep,
    RefreshShellOutcome,
    ShellInstallStatus,
)
from sase.completion.install_refresh import (
    maybe_refresh_installed_completions,
    refresh_stamped_completions,
)
from sase.completion.install_scripts import zwc_path
from sase.completion.install_status import list_shell_statuses
from sase.completion.install_targets import (
    CompletionInstallError,
    DetectedShell,
    ForeignInstallError,
    TargetChoice,
)

_ExpectedCompletion = ExpectedCompletion
_refresh_stamped_completions = refresh_stamped_completions


__all__ = [
    "CompletionInstallError",
    "CompletionRefreshReport",
    "DetectedShell",
    "ForeignInstallError",
    "InstallResult",
    "InstallStep",
    "RECOMMENDED_ZSTYLE",
    "RefreshShellOutcome",
    "ShellInstallStatus",
    "TargetChoice",
    "install_completion",
    "list_shell_statuses",
    "maybe_refresh_installed_completions",
    "refresh_stamped_completions",
    "zwc_path",
]
