"""Install preview plans for the Config Center Updates plugin browser."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agent_clis.install import AgentCliInstallPlan
from sase.plugins.catalog import PluginCatalogError
from sase.plugins.operations import (
    InstallManyPlan,
    InstallPlan,
    InstallReady,
    plan_install,
    plan_install_many,
)
from sase.uv_tool.errors import ReceiptError


@dataclass(frozen=True)
class InstallPreview:
    """Off-thread result of planning an install for the confirm-preview modal.

    *index_plan* is the primary plan (install from the index, ``git=False``):
    either a terminal outcome (:class:`NotUvTool` / :class:`InstallNotFound` /
    :class:`AlreadyInstalled`) or an :class:`InstallReady`. *git_plan* is the
    optional git-source variant (present only when the index plan is ready and
    the git plan also resolves), so the modal's toggle stays pure presentation.
    *error* carries a catalog/receipt failure message instead of a plan.
    """

    index_plan: InstallPlan | None
    git_plan: InstallReady | None = None
    error: str | None = None


@dataclass(frozen=True)
class InstallManyPreview:
    """Off-thread result of planning a batch install preview."""

    plan: InstallManyPlan | None
    error: str | None = None


@dataclass(frozen=True)
class CombinedInstallPreview:
    """Off-thread result of planning a mixed plugin + agent-CLI install."""

    cli_names: tuple[str, ...]
    plugin_names: tuple[str, ...]
    cli_plan: AgentCliInstallPlan
    plugin_preview: InstallManyPreview


def plan_install_preview(name: str, *, offline: bool) -> InstallPreview:
    """Plan ``install <name>`` (default source, then git) for the confirm modal.

    Delegates to :func:`sase.plugins.operations.plan_install` — the single
    source of truth shared with the PatchI — once per source. Cache-first
    (``refresh=False``). The default-source plan is no longer guaranteed to
    resolve from the index: a definitive public-PyPI 404 makes it fall back to
    git automatically. The explicit forced-git variant is only resolved when
    the default plan is ready *and* did not already fall back, so a terminal
    outcome or an already-git default short-circuits the second load instead
    of offering a redundant duplicate variant.
    """
    try:
        index_plan = plan_install(name, git=False, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallPreview(index_plan=None, error=str(exc))

    git_plan: InstallReady | None = None
    if isinstance(index_plan, InstallReady) and index_plan.spec.source != "git":
        try:
            candidate = plan_install(name, git=True, offline=offline)
        except (PluginCatalogError, ReceiptError):
            candidate = None
        if isinstance(candidate, InstallReady):
            git_plan = candidate
    return InstallPreview(index_plan=index_plan, git_plan=git_plan)


def plan_install_many_preview(
    names: tuple[str, ...], *, offline: bool
) -> InstallManyPreview:
    """Plan a marked-set install for the confirm-preview modal."""
    try:
        plan = plan_install_many(names, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallManyPreview(plan=None, error=str(exc))
    return InstallManyPreview(plan=plan)
