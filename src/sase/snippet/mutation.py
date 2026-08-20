"""Conflict-safe snippet add, update, and delete operations.

Python owns destination resolution, source-preserving YAML edits, and the
stale-write guard. Rust validates triggers and the candidate snippet set.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import importlib.resources
from pathlib import Path
import shlex

from sase.config import core as config_core
from sase.config.loading import (
    load_default_config,
    load_plugin_configs,
    load_yaml_file,
    merge_config_sources,
)
from sase.content_layout import resolve_project_config_read_path
from sase.core.snippet_catalog_facade import (
    ComposedSnippetCatalog,
    SnippetDiagnostic,
    SnippetTriggerValidation,
    compose_snippet_catalog,
    validate_snippet_trigger,
)
from sase.snippet.catalog import load_snippet_catalog, resolve_snippet_catalog_context
from sase.snippet.lookup import SnippetLookupError, lookup_snippet
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetEntry,
    SnippetMutationAction,
    SnippetMutationOutcome,
    SnippetRelations,
)
from sase.xprompt.save_index import invalidate_save_index
from sase.xprompt.snippet_config_yaml import (
    SnippetConfigConflictError,
    apply_snippet_config_text,
    insert_snippet_into_config,
    parse_ace_snippets,
    preview_snippet_delete,
    preview_snippet_upsert,
    snippet_config_digest,
)
from sase.xprompt.snippet_targets import resolve_snippet_save_target
from sase.xprompt.write_targets import resolve_xprompt_write_target

SnippetConflictError = SnippetConfigConflictError


class SnippetMutationError(RuntimeError):
    """Raised when a snippet add, update, or delete cannot be applied."""


class SnippetValidationError(SnippetMutationError):
    """Raised when the candidate snippet set fails the Rust contract."""

    def __init__(self, diagnostics: tuple[SnippetDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        if diagnostics:
            message = "; ".join(f"{item.code}: {item.message}" for item in diagnostics)
        else:
            message = "snippet validation failed"
        super().__init__(message)


class SnippetReadOnlyError(SnippetMutationError):
    """Raised when a delete targets a derived or read-only definition."""


def add_snippet(
    project_ref: str | None,
    trigger: str,
    template: str,
    *,
    target: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    expected_digest: str | None = None,
) -> SnippetMutationOutcome:
    """Insert or replace *trigger* after Rust validation and a stale-write check."""
    return _upsert_snippet(
        project_ref,
        trigger,
        template,
        target=target,
        force=force,
        dry_run=dry_run,
        expected_digest=expected_digest,
        require_existing=False,
    )


def update_snippet(
    project_ref: str | None,
    trigger: str,
    template: str,
    *,
    target: str | None = None,
    dry_run: bool = False,
    expected_digest: str | None = None,
) -> SnippetMutationOutcome:
    """Replace an existing destination snippet after validation."""
    return _upsert_snippet(
        project_ref,
        trigger,
        template,
        target=target,
        force=True,
        dry_run=dry_run,
        expected_digest=expected_digest,
        require_existing=True,
    )


def upsert_snippet_at_path(
    config_path: str | Path,
    trigger: str,
    template: str,
    *,
    force: bool = True,
    dry_run: bool = False,
    expected_digest: str | None = None,
) -> SnippetMutationOutcome:
    """Write *trigger* to an already-resolved YAML path.

    Used by the prompt-pane save wrapper so authoring surfaces share one
    mutation primitive. *force* defaults to true because those surfaces have
    already confirmed the write.
    """
    cleaned_trigger = _require_trigger(trigger)
    cleaned_template = _require_template(template)
    write_target = resolve_xprompt_write_target(config_path)
    destination = str(write_target.write_path)
    catalog = load_snippet_catalog()
    if not force:
        _refuse_collision(catalog, cleaned_trigger, destination)
    return _apply_upsert(
        catalog=catalog,
        context=catalog.context,
        trigger=cleaned_trigger,
        template=cleaned_template,
        read_path=str(write_target.read_path),
        write_path=destination,
        apply_target=None
        if write_target.apply_target is None
        else str(write_target.apply_target),
        via_chezmoi=write_target.via_chezmoi,
        source_kind="configured",
        force=force,
        dry_run=dry_run,
        expected_digest=expected_digest,
        require_existing=False,
    )


def delete_snippet(
    project_ref: str | None,
    trigger: str,
    *,
    all_layers: bool = False,
    dry_run: bool = False,
    expected_digest: str | None = None,
) -> SnippetMutationOutcome:
    """Remove the winning writable config contribution for *trigger*."""
    cleaned = trigger.strip()
    if not cleaned:
        raise SnippetMutationError("snippet trigger must be a nonblank string")
    context = resolve_snippet_catalog_context(project_ref)
    catalog = load_snippet_catalog(project_ref)
    entry = lookup_snippet(catalog, cleaned)
    targets = _delete_targets(entry, all_layers=all_layers)
    if not targets:
        origin = entry.origin
        raise SnippetReadOnlyError(
            "cannot delete "
            f"{entry.trigger}: definition comes from "
            f"{origin.display_path or origin.kind}"
        )
    removed_paths = {item[0] for item in targets}
    revealed = _revealed_after_delete(entry, removed_paths)
    candidate = dict(catalog.explicit_templates)
    if revealed is None:
        candidate.pop(entry.trigger, None)
    else:
        candidate[entry.trigger] = revealed.raw_template
    composed = _validate_candidate(candidate)
    backlinks = composed.inbound.get(entry.trigger, ())
    write_path, original, new_text = targets[0]
    digest = snippet_config_digest(original or b"")
    if not dry_run:
        if expected_digest is not None and expected_digest != digest:
            raise SnippetConflictError(Path(write_path))
        for path, expected, text in targets:
            apply_snippet_config_text(path, text, expected_bytes=expected)
        _invalidate_after_write(*(item[0] for item in targets))
        digest = snippet_config_digest(Path(write_path).read_bytes())
    project_name = context.name or project_ref or ""
    return SnippetMutationOutcome(
        project_name=project_name,
        trigger=entry.trigger,
        template=entry.raw_template,
        action="deleted",
        read_path=write_path,
        write_path=write_path,
        apply_target=None,
        source_kind=entry.origin.kind,
        via_chezmoi=False,
        restore_command=_restore_command(
            entry.trigger, entry.raw_template, project_name, write_path
        ),
        affected_backlinks=backlinks,
        revealed=revealed,
        dry_run=dry_run,
        content_digest=digest,
        created=False,
    )


def _upsert_snippet(
    project_ref: str | None,
    trigger: str,
    template: str,
    *,
    target: str | None,
    force: bool,
    dry_run: bool,
    expected_digest: str | None,
    require_existing: bool,
) -> SnippetMutationOutcome:
    cleaned_trigger = _require_trigger(trigger)
    cleaned_template = _require_template(template)
    context = resolve_snippet_catalog_context(project_ref)
    catalog = load_snippet_catalog(project_ref)
    save_target = resolve_snippet_save_target(
        target
        if target is not None
        else _configured_snippet_path(context.workspace_dir)
    )
    destination = str(save_target.write_path)
    if not force:
        _refuse_collision(catalog, cleaned_trigger, destination)
    return _apply_upsert(
        catalog=catalog,
        context=context,
        trigger=cleaned_trigger,
        template=cleaned_template,
        read_path=str(save_target.read_path),
        write_path=destination,
        apply_target=None
        if save_target.apply_target is None
        else str(save_target.apply_target),
        via_chezmoi=save_target.via_chezmoi,
        source_kind=save_target.source,
        force=force,
        dry_run=dry_run,
        expected_digest=expected_digest,
        require_existing=require_existing,
    )


def _apply_upsert(
    *,
    catalog: SnippetCatalog,
    context: SnippetCatalogContext,
    trigger: str,
    template: str,
    read_path: str,
    write_path: str,
    apply_target: str | None,
    via_chezmoi: bool,
    source_kind: str,
    force: bool,
    dry_run: bool,
    expected_digest: str | None,
    require_existing: bool,
) -> SnippetMutationOutcome:
    del force
    path = Path(write_path)
    original = path.read_bytes() if path.is_file() else None
    current_text = "" if original is None else original.decode("utf-8")
    existing = parse_ace_snippets(current_text)
    if require_existing and trigger not in existing:
        raise SnippetLookupError(trigger)
    new_text = preview_snippet_upsert(current_text, trigger, template)
    candidate_file = parse_ace_snippets(new_text)
    _validate_candidate(candidate_file)
    candidate_catalog = dict(catalog.explicit_templates)
    candidate_catalog[trigger] = template
    composed = _validate_candidate(candidate_catalog)
    action = _upsert_action(catalog, trigger, destination_has=trigger in existing)
    backlinks = composed.inbound.get(trigger, ())
    digest = snippet_config_digest(original or b"")
    if not dry_run:
        if expected_digest is None:
            insert_snippet_into_config(str(path), trigger, template)
        else:
            apply_snippet_config_text(
                path,
                new_text,
                expected_bytes=original,
                expected_digest=expected_digest,
            )
        _invalidate_after_write(write_path, read_path)
        digest = snippet_config_digest(path.read_bytes())
    project_name = context.name or ""
    return SnippetMutationOutcome(
        project_name=project_name,
        trigger=trigger,
        template=template,
        action=action,
        read_path=read_path,
        write_path=write_path,
        apply_target=apply_target,
        source_kind=source_kind,
        via_chezmoi=via_chezmoi,
        restore_command=_restore_command(trigger, template, project_name, write_path),
        affected_backlinks=backlinks,
        revealed=None,
        dry_run=dry_run,
        content_digest=digest,
        created=trigger not in existing,
    )


def _refuse_collision(catalog: SnippetCatalog, trigger: str, destination: str) -> None:
    existing = catalog.entry_for(trigger)
    if existing is None:
        source = catalog.alias_provenance.get(trigger)
        if source is not None:
            existing = catalog.entry_for(source)
    if existing is None:
        return
    origin = existing.origin
    origin_path = origin.path or ""
    if origin_path == destination:
        raise SnippetMutationError(
            f"snippet {existing.trigger!r} already exists in {destination}; "
            "pass force to overwrite"
        )
    winner = origin.display_path or origin.kind
    raise SnippetMutationError(
        f"snippet {existing.trigger!r} already exists in {winner}; "
        "pass force to shadow or overwrite"
    )


def _upsert_action(
    catalog: SnippetCatalog, trigger: str, *, destination_has: bool
) -> SnippetMutationAction:
    if destination_has:
        return "replaced"
    if catalog.entry_for(trigger) is not None:
        return "shadowed"
    return "created"


def _delete_targets(
    entry: SnippetEntry, *, all_layers: bool
) -> list[tuple[str, bytes | None, str]]:
    contributions = [
        item
        for item in entry.contributions
        if item.kind not in {"xprompt", "default", "plugin", "pending"}
        and item.writable
        and item.path
    ]
    if not contributions:
        return []
    selected = contributions if all_layers else [contributions[-1]]
    targets: list[tuple[str, bytes | None, str]] = []
    for item in selected:
        source_path = item.path
        if source_path is None:
            continue
        write = resolve_xprompt_write_target(source_path)
        path = write.write_path
        original = path.read_bytes() if path.is_file() else None
        text = "" if original is None else original.decode("utf-8")
        try:
            new_text = preview_snippet_delete(text, entry.trigger)
        except KeyError as exc:
            raise SnippetMutationError(
                f"snippet {entry.trigger!r} is not present in {path}"
            ) from exc
        targets.append((str(path), original, new_text))
    return targets


def _revealed_after_delete(
    entry: SnippetEntry, removed_paths: set[str]
) -> SnippetEntry | None:
    kept = [
        item for item in entry.contributions if (item.path or "") not in removed_paths
    ]
    if not kept:
        return None
    winner = replace(kept[-1], shadowed_by=None)
    return SnippetEntry(
        trigger=entry.trigger,
        raw_template=winner.template,
        composed_template=winner.template,
        origin=winner,
        aliases=(),
        contributions=tuple(kept),
        relations=SnippetRelations((), (), ()),
        diagnostics=(),
    )


def _validate_candidate(snippets: Mapping[str, str]) -> ComposedSnippetCatalog:
    composed = compose_snippet_catalog(snippets)
    errors = tuple(
        item for item in composed.diagnostics if item.code == "invalid_trigger"
    )
    invalid = tuple(item for item in composed.triggers.values() if not item.valid)
    if errors or invalid:
        if not errors:
            errors = tuple(
                SnippetDiagnostic(
                    code="invalid_trigger",
                    message=item.reason or "invalid trigger",
                    trigger=item.trigger,
                )
                for item in invalid
            )
        raise SnippetValidationError(errors)
    return composed


def _require_trigger(trigger: str) -> str:
    cleaned = trigger.strip()
    if not cleaned:
        raise SnippetMutationError("snippet trigger must be a nonblank string")
    validation: SnippetTriggerValidation = validate_snippet_trigger(cleaned)
    if not validation.valid:
        reason = validation.reason or "invalid_characters"
        raise SnippetMutationError(f"snippet trigger {cleaned!r} is invalid ({reason})")
    return cleaned


def _require_template(template: str) -> str:
    if not template.strip():
        raise SnippetMutationError("snippet template must be a nonblank string")
    return template


def _configured_snippet_path(workspace: Path | None) -> str | None:
    local_path = None
    if workspace is not None:
        try:
            local_path = resolve_project_config_read_path(workspace)
        except Exception:
            local_path = None
    merged = merge_config_sources(
        default_config=load_default_config(importlib.resources.files),
        plugin_configs=load_plugin_configs(importlib.resources.files),
        user_base_path=config_core.CONFIG_DIR / "sase.yml",
        overlay_paths=config_core.selected_overlay_paths(),
        selected_identity_snapshot=config_core.get_agent_owner_config_snapshot(),
        local_path=local_path,
        yaml_loader=load_yaml_file,
    )
    ace = merged.get("ace")
    if not isinstance(ace, dict):
        return None
    value = ace.get("snippet_config_path")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _restore_command(
    trigger: str, template: str, project_name: str, write_path: str
) -> str:
    parts = ["sase", "snippet", "add", trigger, template]
    if project_name:
        parts.extend(["-p", project_name])
    if write_path:
        parts.extend(["-t", write_path])
    return " ".join(shlex.quote(part) for part in parts)


def _invalidate_after_write(*paths: str) -> None:
    for path in paths:
        invalidate_save_index(path)
    config_core.clear_config_cache()


__all__ = [
    "SnippetConflictError",
    "SnippetMutationError",
    "SnippetReadOnlyError",
    "SnippetValidationError",
    "add_snippet",
    "delete_snippet",
    "update_snippet",
    "upsert_snippet_at_path",
]
