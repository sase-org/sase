"""Install preview plans for the Config Center Updates plugin browser."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.agent_clis.install import AgentCliInstallPlan
from sase.plugins.catalog import PluginCatalogError, find_plugin, load_plugin_catalog
from sase.plugins.declared_commands import (
    DeclaredCommandProblem,
    DeclaredCommands,
    declared_problems,
    get_declared_commands_for_entry,
)
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
    *declared_commands* is the upstream pre-install command preview for the
    confirm modal (phase sase-1if.6); ``None`` (or ``unknown``) renders
    nothing. *declared_problems_* carries the pre-consent collision flags for
    the preview names, rendered as yellow warnings.
    """

    index_plan: InstallPlan | None
    git_plan: InstallReady | None = None
    error: str | None = None
    declared_commands: DeclaredCommands | None = None
    declared_problems_: tuple[DeclaredCommandProblem, ...] = ()


@dataclass(frozen=True)
class InstallManyPreview:
    """Off-thread result of planning a batch install preview.

    *declared* carries the upstream command preview per batch member, keyed
    by display name; members without a declared preview simply render no
    per-item suffix.
    """

    plan: InstallManyPlan | None
    error: str | None = None
    declared: dict[str, DeclaredCommands] | None = None


def install_command_details(declared: DeclaredCommands | None) -> tuple[str, ...]:
    """Leading confirm-modal detail lines for a single-install preview.

    One ``❯ Adds a new command: sase <name>`` line per declared command.
    Anything but a ``declared`` preview renders nothing.
    """
    from sase.plugin_commands.chip import format_command_chip

    if declared is None or declared.status != "declared" or not declared.names:
        return ()
    return tuple(
        f"❯ Adds a new command: {format_command_chip(name)}" for name in declared.names
    )


def install_command_warnings(
    problems: tuple[DeclaredCommandProblem, ...],
) -> tuple[str, ...]:
    """Yellow confirm-modal warnings for pre-consent command collisions."""
    return tuple(problem.detail for problem in problems)


def install_many_item_suffix(
    declared: DeclaredCommands | None,
) -> str:
    """Per-item batch-modal suffix for one member's preview, or ``""``."""
    from sase.plugin_commands.chip import format_command_chip

    if declared is None or declared.status != "declared" or not declared.names:
        return ""
    chips = ", ".join(format_command_chip(name) for name in declared.names)
    return f" (adds {chips})"


@dataclass(frozen=True)
class CombinedInstallPreview:
    """Off-thread result of planning a mixed plugin + agent-CLI install."""

    cli_names: tuple[str, ...]
    plugin_names: tuple[str, ...]
    cli_plan: AgentCliInstallPlan
    plugin_preview: InstallManyPreview


def plan_install_preview(
    name: str,
    *,
    offline: bool,
    declared_fn: Callable[..., DeclaredCommands | None] | None = None,
) -> InstallPreview:
    """Plan ``install <name>`` (default source, then git) for the confirm modal.

    Delegates to :func:`sase.plugins.operations.plan_install` — the single
    source of truth shared with the PatchI — once per source. Cache-first
    (``refresh=False``). The default-source plan is no longer guaranteed to
    resolve from the index: a definitive public-PyPI 404 makes it fall back to
    git automatically. The explicit forced-git variant is only resolved when
    the default plan is ready *and* did not already fall back, so a terminal
    outcome or an already-git default short-circuits the second load instead
    of offering a redundant duplicate variant.

    Attaches the upstream command preview (phase sase-1if.6) best-effort:
    any failure degrades to ``None``, which renders nothing.
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
    declared = _preview_for_install(name, offline=offline, declared_fn=declared_fn)
    problems: tuple[DeclaredCommandProblem, ...] = ()
    if declared is not None and declared.status == "declared" and declared.names:
        try:
            problems = declared_problems(declared.names)
        except Exception:  # noqa: BLE001 — problems must never fail the preview.
            problems = ()
    return InstallPreview(
        index_plan=index_plan,
        git_plan=git_plan,
        declared_commands=declared,
        declared_problems_=problems,
    )


def _preview_for_install(
    name: str,
    *,
    offline: bool,
    declared_fn: Callable[..., DeclaredCommands | None] | None,
) -> DeclaredCommands | None:
    """Best-effort upstream command preview for the install confirm modal."""
    fetch = declared_fn or get_declared_commands_for_entry
    try:
        catalog = load_plugin_catalog(refresh=False, offline=offline)
        entry = find_plugin(catalog, name)
    except Exception:  # noqa: BLE001 — previews must never fail the preview.
        return None
    if entry is None:
        return None
    try:
        return fetch(entry, offline=offline)
    except Exception:  # noqa: BLE001 — previews must never fail the preview.
        return None


def plan_install_many_preview(
    names: tuple[str, ...], *, offline: bool
) -> InstallManyPreview:
    """Plan a marked-set install for the confirm-preview modal."""
    try:
        plan = plan_install_many(names, offline=offline)
    except (PluginCatalogError, ReceiptError) as exc:
        return InstallManyPreview(plan=None, error=str(exc))
    return InstallManyPreview(
        plan=plan, declared=_previews_for_many(plan, offline=offline)
    )


def _previews_for_many(
    plan: InstallManyPlan, *, offline: bool
) -> dict[str, DeclaredCommands] | None:
    """Best-effort upstream previews for batch members, keyed by display name."""
    from sase.plugins.declared_commands import (
        attach_declared_previews,
        declared_cache_key,
    )
    from sase.plugins.operations import InstallManyReady

    if not isinstance(plan, InstallManyReady) or offline:
        return None
    try:
        catalog = load_plugin_catalog(refresh=False, offline=offline)
    except Exception:  # noqa: BLE001 — previews must never fail the preview.
        return None
    names: list[str] = []
    batch_entries: list[Any] = []
    for spec in plan.specs:
        try:
            entry = find_plugin(catalog, spec.display_name)
        except Exception:  # noqa: BLE001 — one bad lookup skips one suffix.
            continue
        if entry is not None:
            names.append(spec.display_name)
            batch_entries.append(entry)
    if not batch_entries:
        return None
    try:
        previews = attach_declared_previews(tuple(batch_entries))
    except Exception:  # noqa: BLE001 — previews must never fail the preview.
        return None
    keyed = {
        name: previews.get(declared_cache_key(entry.full_name))
        for name, entry in zip(names, batch_entries, strict=True)
    }
    return {name: preview for name, preview in keyed.items() if preview is not None}
