"""Project-aware snippet catalog loader.

Resolves a project workspace without changing process CWD, replays the real
config-layer order, overlays explicit ``ace.snippets`` on xprompt-derived
entries, and delegates alias, composition, and graph semantics to Rust.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import importlib.resources
import os
from pathlib import Path

from sase.config import core as config_core
from sase.config.layers import ConfigLayer, load_config_layers
from sase.config.loading import load_default_config
from sase.content_layout import (
    discover_project_root,
    resolve_project_config_read_path,
    resolve_project_config_write_path,
)
from sase.core.snippet_catalog_facade import (
    compose_snippet_catalog,
    validate_snippet_trigger,
)
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetEntry,
    SnippetLayerDiagnostic,
    SnippetRelations,
    SnippetSourceContribution,
    SnippetSourceKind,
)
from sase.xprompt._glossary_catalog_projects import select_project
from sase.xprompt.glossary_catalog import enabled_project_records
from sase.xprompt import loader as xprompt_loader
from sase.xprompt.snippet_bridge import (
    XPromptSnippetEntry,
    build_xprompt_snippet_entries_from_catalog,
)

_KIND_BY_LAYER = {
    "default": "default",
    "user": "user",
    "local": "project",
}


def load_snippet_catalog(
    project_ref: str | None = None,
    *,
    launch_workspace: str | Path | None = None,
    pending_saves: Mapping[str, str] | None = None,
) -> SnippetCatalog:
    """Load one project's provenance-aware snippet catalog.

    Never changes process CWD. *project_ref* may be a display name, alias, or
    project key. When omitted, the launch workspace (or CWD) selects the
    project. Xprompt loading still receives the original ref so callers that
    only know a namespace keep working when the lifecycle registry has no row.
    """
    context = resolve_snippet_catalog_context(
        project_ref, launch_workspace=launch_workspace
    )
    xprompt_project = context.name or project_ref
    xprompt_entries = build_xprompt_snippet_entries_from_catalog(
        xprompt_loader.get_all_xprompts(project=xprompt_project),
        include_shadowed=True,
    )
    config_contributions, layer_diagnostics = _config_layer_contributions(
        context.workspace_dir
    )
    return _build_snippet_catalog(
        context,
        xprompt_entries=xprompt_entries,
        config_contributions=config_contributions,
        pending_saves=pending_saves,
        layer_diagnostics=layer_diagnostics,
    )


def resolve_snippet_catalog_context(
    project_ref: str | None,
    *,
    launch_workspace: str | Path | None = None,
) -> SnippetCatalogContext:
    """Resolve project identity for a catalog load without changing CWD."""
    selected = select_project(
        project_ref,
        enabled_project_records(None),
        launch_workspace=launch_workspace,
    )
    if selected is not None:
        return SnippetCatalogContext(
            key=selected.key,
            name=selected.name,
            aliases=selected.aliases,
            workspace_dir=selected.workspace_dir,
        )
    fallback_root = None
    if launch_workspace is not None:
        start = Path(launch_workspace).expanduser()
        fallback_root = discover_project_root(start) or start
    elif project_ref is None:
        fallback_root = discover_project_root()
    return SnippetCatalogContext(
        key=None,
        name=project_ref,
        aliases=(),
        workspace_dir=fallback_root,
    )


def _build_snippet_catalog(
    context: SnippetCatalogContext,
    *,
    xprompt_entries: Sequence[XPromptSnippetEntry],
    config_contributions: Sequence[SnippetSourceContribution],
    pending_saves: Mapping[str, str] | None = None,
    layer_diagnostics: Sequence[SnippetLayerDiagnostic] = (),
) -> SnippetCatalog:
    """Compose explicit templates from already-loaded source contributions."""
    by_trigger: dict[str, list[SnippetSourceContribution]] = {}
    explicit: dict[str, str] = {}
    for entry in xprompt_entries:
        _record_contribution(
            by_trigger,
            explicit,
            _xprompt_contribution(entry),
            overlay=False,
        )
    effective_config: dict[str, str] = {}
    for contribution in config_contributions:
        _record_contribution(by_trigger, explicit, contribution, overlay=True)
        if contribution.trigger:
            effective_config[contribution.trigger] = contribution.template
    if pending_saves:
        for trigger, template in pending_saves.items():
            _record_contribution(
                by_trigger,
                explicit,
                SnippetSourceContribution(
                    trigger=trigger,
                    template=template,
                    kind="pending",
                    path=None,
                    display_path="pending",
                    writable=False,
                ),
                overlay=True,
            )

    composed = compose_snippet_catalog(explicit)
    aliases_for: dict[str, list[str]] = {trigger: [] for trigger in explicit}
    for alias, source in composed.alias_provenance.items():
        aliases_for.setdefault(source, []).append(alias)

    rust_by_trigger: dict[str, list] = {trigger: [] for trigger in explicit}
    for diagnostic in composed.diagnostics:
        rust_by_trigger.setdefault(diagnostic.trigger, []).append(diagnostic)

    entries = tuple(
        SnippetEntry(
            trigger=trigger,
            raw_template=explicit[trigger],
            composed_template=composed.templates.get(trigger, explicit[trigger]),
            origin=_winning_contribution(by_trigger[trigger]),
            aliases=tuple(aliases_for.get(trigger, ())),
            contributions=tuple(by_trigger[trigger]),
            relations=SnippetRelations(
                outbound=composed.outbound.get(trigger, ()),
                inbound=composed.inbound.get(trigger, ()),
                calls=composed.calls.get(trigger, ()),
            ),
            diagnostics=tuple(rust_by_trigger.get(trigger, ())),
        )
        for trigger in sorted(explicit)
    )
    return SnippetCatalog(
        context=context,
        entries=entries,
        composed=composed,
        layer_diagnostics=tuple(layer_diagnostics),
        explicit_templates=dict(explicit),
        effective_config_templates=dict(effective_config),
    )


def prompt_catalog_projection(
    catalog: SnippetCatalog,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return ``(explicit, composed, config)`` maps for ACE prompt snapshots."""
    return (
        dict(catalog.explicit_templates),
        dict(catalog.composed_templates),
        dict(catalog.effective_config_templates),
    )


def editor_helper_entries(catalog: SnippetCatalog) -> list[dict[str, str | None]]:
    """Project the catalog into the editor-helper snippet-catalog wire."""
    metadata: dict[str, dict[str, str | None]] = {}
    for entry in catalog.entries:
        origin = entry.origin
        metadata[entry.trigger] = {
            "trigger": entry.trigger,
            "template": entry.raw_template,
            "source": _helper_source(origin.kind),
            "xprompt_name": origin.xprompt_name,
            "description": origin.description,
            "source_path_display": _helper_display_path(origin),
        }
    rows: list[dict[str, str | None]] = []
    for trigger, template in catalog.composed.templates.items():
        source = catalog.composed.alias_provenance.get(trigger, trigger)
        row = dict(metadata[source])
        row["trigger"] = trigger
        row["template"] = template
        rows.append(row)
    return rows


def _config_layer_contributions(
    workspace: Path | None,
) -> tuple[tuple[SnippetSourceContribution, ...], tuple[SnippetLayerDiagnostic, ...]]:
    contributions: list[SnippetSourceContribution] = []
    diagnostics: list[SnippetLayerDiagnostic] = []
    for layer in _load_raw_layers(workspace):
        kind = _layer_kind(layer.name)
        if layer.error:
            diagnostics.append(
                SnippetLayerDiagnostic(
                    message=layer.error,
                    path=layer.path,
                    layer=layer.name,
                )
            )
            continue
        ace = layer.data.get("ace") if isinstance(layer.data, dict) else None
        if ace is None:
            continue
        if not isinstance(ace, dict):
            diagnostics.append(
                SnippetLayerDiagnostic(
                    message="ace must be a YAML mapping",
                    path=layer.path,
                    layer=layer.name,
                )
            )
            continue
        raw_snippets = ace.get("snippets")
        if raw_snippets is None:
            continue
        if not isinstance(raw_snippets, dict):
            diagnostics.append(
                SnippetLayerDiagnostic(
                    message="ace.snippets must be a YAML mapping",
                    path=layer.path,
                    layer=layer.name,
                )
            )
            continue
        writable = _is_writable(layer.path)
        display = layer.path
        for raw_key, raw_value in raw_snippets.items():
            if not isinstance(raw_key, str) or not isinstance(raw_value, str):
                diagnostics.append(
                    SnippetLayerDiagnostic(
                        message=(
                            "ace.snippets entries must use string triggers "
                            "and string templates"
                        ),
                        path=layer.path,
                        layer=layer.name,
                        trigger=raw_key if isinstance(raw_key, str) else None,
                    )
                )
                continue
            if not validate_snippet_trigger(raw_key).valid:
                diagnostics.append(
                    SnippetLayerDiagnostic(
                        message=f"invalid snippet trigger {raw_key!r}",
                        path=layer.path,
                        layer=layer.name,
                        trigger=raw_key,
                    )
                )
                continue
            contributions.append(
                SnippetSourceContribution(
                    trigger=raw_key,
                    template=raw_value,
                    kind=kind,
                    path=layer.path,
                    display_path=display,
                    writable=writable,
                )
            )
    return tuple(contributions), tuple(diagnostics)


def _load_raw_layers(workspace: Path | None) -> list[ConfigLayer]:
    local_path = None
    fallback = Path("sase") / "sase.yml"
    if workspace is not None:
        try:
            local_path = resolve_project_config_read_path(workspace)
        except Exception:
            local_path = None
        fallback = resolve_project_config_write_path(workspace)
    return load_config_layers(
        config_dir=config_core.CONFIG_DIR,
        default_loader=lambda: load_default_config(importlib.resources.files),
        overlay_paths=config_core.selected_overlay_paths(),
        local_path=local_path,
        local_fallback_path=fallback,
        resource_files=importlib.resources.files,
    )


def _layer_kind(name: str) -> SnippetSourceKind:
    if name in _KIND_BY_LAYER:
        return _KIND_BY_LAYER[name]  # type: ignore[return-value]
    if name.startswith("plugin:"):
        return "plugin"
    if name.startswith("overlay:"):
        return "overlay"
    return "user"


def _is_writable(path: str | None) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.exists():
        return candidate.is_file() and os.access(candidate, os.W_OK)
    ancestor = candidate.parent
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    return ancestor.exists() and os.access(ancestor, os.W_OK)


def _xprompt_contribution(entry: XPromptSnippetEntry) -> SnippetSourceContribution:
    return SnippetSourceContribution(
        trigger=entry.trigger,
        template=entry.template,
        kind="xprompt",
        path=entry.source_path_display,
        display_path=entry.source_path_display,
        writable=False,
        xprompt_name=entry.xprompt_name,
        description=entry.description,
    )


def _record_contribution(
    store: dict[str, list[SnippetSourceContribution]],
    explicit: dict[str, str],
    contribution: SnippetSourceContribution,
    *,
    overlay: bool,
) -> None:
    if not validate_snippet_trigger(contribution.trigger).valid:
        return
    existing = store.setdefault(contribution.trigger, [])
    winner_id = contribution.path or contribution.kind
    if overlay:
        store[contribution.trigger] = [
            item
            if item.shadowed_by is not None
            else replace(item, shadowed_by=winner_id)
            for item in existing
        ]
        store[contribution.trigger].append(contribution)
        explicit[contribution.trigger] = contribution.template
        return
    if existing:
        current_id = existing[0].path or existing[0].kind
        existing.append(replace(contribution, shadowed_by=current_id))
        return
    existing.append(contribution)
    explicit[contribution.trigger] = contribution.template


def _winning_contribution(
    contributions: Sequence[SnippetSourceContribution],
) -> SnippetSourceContribution:
    for item in reversed(contributions):
        if item.shadowed_by is None:
            return item
    return contributions[-1]


def _helper_source(kind: SnippetSourceKind) -> str:
    if kind == "xprompt":
        return "xprompt"
    return "user_config"


def _helper_display_path(origin: SnippetSourceContribution) -> str | None:
    if origin.kind == "xprompt":
        return origin.display_path
    return origin.display_path or "ace.snippets"


__all__ = [
    "editor_helper_entries",
    "load_snippet_catalog",
    "prompt_catalog_projection",
    "resolve_snippet_catalog_context",
]
