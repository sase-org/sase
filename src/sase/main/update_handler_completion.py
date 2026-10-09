"""Post-update shell-completion refresh helpers for ``sase update``.

The fresh-child refresh now lives in :mod:`sase.completion.refresh_child`,
shared with plugin install/update/uninstall. This module keeps the
``sase update`` entry point (honoring an injected in-process refresh function)
and re-exports the shared helpers so existing importers keep working.
"""

from __future__ import annotations

from collections.abc import Callable

from sase.completion.install import maybe_refresh_installed_completions
from sase.completion.refresh_child import (
    COMPLETION_REFRESH_TIMEOUT_SECONDS,
    CompletionRefreshReport,
    RefreshShellOutcome,
    refresh_completions_in_child,
    render_completion_refresh,
)
from sase.uv_tool.detect import UvToolInstall

# Backwards-compatible alias: the private child-refresh helper moved to
# :func:`sase.completion.refresh_child.refresh_completions_in_child`.
_refresh_completions_in_child = refresh_completions_in_child


def completion_refresh_after_update(
    install: UvToolInstall,
    refresh_fn: Callable[[], CompletionRefreshReport] | None,
) -> CompletionRefreshReport:
    if refresh_fn is not None:
        return maybe_refresh_installed_completions(refresh_fn)
    return refresh_completions_in_child(install)


__all__ = [
    "COMPLETION_REFRESH_TIMEOUT_SECONDS",
    "CompletionRefreshReport",
    "RefreshShellOutcome",
    "completion_refresh_after_update",
    "refresh_completions_in_child",
    "render_completion_refresh",
]
