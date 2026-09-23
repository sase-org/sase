"""Install message helpers for the Config Center Updates plugin browser."""

from __future__ import annotations

from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.operations import (
    InstallManyOutcome,
    InstallManyReady,
    InstallNotFound,
    InstallOutcome,
    InstallReady,
    InstallSkipped,
)
from sase.plugins.render_common import humanize_duration

from .plugins_browser_install_previews import _CombinedInstallOutcome


def install_summary(plan: InstallReady) -> str:
    """The resolved-plugin-set line shown in the confirm-preview modal."""
    return f"Installs {plan.spec.display_name}  (from {plan.spec.source})"


def install_many_summary(plan: InstallManyReady) -> str:
    """The resolved-plugin-set line shown for a batch install."""
    count = len(plan.specs)
    noun = "plugin" if count == 1 else "plugins"
    return f"Installs {count} {noun}"


def install_success_message(outcome: InstallOutcome) -> str:
    """A concise, CLI-flavored success toast: name + new version + elapsed."""
    spec = outcome.plan.spec
    change = outcome.change_set.get(spec.requirement.name)
    version = change.new_version if change is not None else None
    suffix = f" v{version}" if version else ""
    return (
        f"Installed {spec.display_name}{suffix} in {humanize_duration(outcome.elapsed)}"
    )


def install_many_success_message(outcome: InstallManyOutcome) -> str:
    """A concise success toast for a combined marked-set install."""
    count = len(outcome.plan.specs)
    noun = "plugin" if count == 1 else "plugins"
    return f"Installed {count} {noun} in {humanize_duration(outcome.elapsed)}"


def _combined_install_message(outcome: _CombinedInstallOutcome) -> str:
    """The proc message for a mixed install: CLI lines then the plugin leg."""
    from .plugins_browser_agent_clis_actions import agent_cli_install_summary

    cli_message, _severity = agent_cli_install_summary(outcome.cli_results)
    if outcome.plugin_error is not None:
        return f"{cli_message}\n{outcome.plugin_error}"
    if outcome.plugin_outcome is not None:
        plugin_message = install_many_success_message(outcome.plugin_outcome)
        return f"{cli_message}\n{plugin_message}"
    return cli_message


def missing_plugin_message(
    query: str, suggestions: tuple[PluginCatalogEntry, ...]
) -> str:
    """The not-found toast, mirroring the PatchI's ranked-suggestions wording."""
    if suggestions:
        names = ", ".join(entry.name for entry in suggestions)
        return f"No plugin named '{query}' in the catalog. Did you mean: {names}?"
    return f"No plugin named '{query}' in the catalog."


def install_not_found_message(plan: InstallNotFound) -> str:
    """The install not-found toast (shared wording with ``update``)."""
    return missing_plugin_message(plan.query, plan.suggestions)


_SOURCE_VARIANT_LABELS: dict[str, str] = {
    "catalog": "from index",
    "git": "from git",
    "passthrough": "from source",
}


def _source_variant_label(source: str) -> str:
    """The confirm-modal variant label for a resolved :class:`ResolvedSpec` source."""
    return _SOURCE_VARIANT_LABELS.get(source, f"from {source}")


def _install_many_skipped_message(skipped: InstallSkipped) -> str:
    """Human-readable skipped entry for batch-install previews/toasts."""
    if skipped.reason == "not found" and skipped.suggestions:
        names = ", ".join(entry.name for entry in skipped.suggestions)
        return f"{skipped.query}: not found; did you mean {names}?"
    return f"{skipped.query}: {skipped.reason}"
