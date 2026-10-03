"""Resolve one macro definition into the stable show record."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import os
from pathlib import Path
from typing import cast

from sase.macro._catalog_format import format_inputs
from sase.macro._catalog_models import CatalogEntry
from sase.macro._catalog_sources import (
    classify,
    definition_path as catalog_definition_path,
    source_path_display,
)
from sase.macro._parsing import (
    MacroReferenceArgKind,
    iter_macro_references,
)
from sase.macro.cli_show_model import (
    ShowProvenance,
    ShowReference,
    MacroShowRecord,
)
from sase.macro.config_yaml import config_entry_line_span
from sase.macro.load_issues import collect_macro_load_issues
from sase.macro.loader import get_all_workflows, get_all_macros
from sase.macro.models import Macro, macro_to_workflow
from sase.macro.properties import show_inputs, show_local_macros, show_steps
from sase.macro.reference_display import (
    workflow_kind_value,
    workflow_reference_insertion,
    workflow_reference_prefix,
)
from sase.macro.segment_separators import macro_segment_count
from sase.macro.used_macros import scan_macro_references
from sase.macro.workflow_models import Workflow
from sase.macro.macro_sources import (
    definition_file_for_source,
    definition_line_for,
)


_CONFIG_SOURCE_IDS = frozenset({"config", "default_config", "local_config"})
_CONFIG_SOURCE_PREFIXES = (
    "config_overlay:",
    "project_local_config:",
    "plugin_config:",
)


@dataclass(frozen=True, slots=True)
class ShowLookupMiss:
    name: str
    suggestions: list[str]


def normalize_show_name(raw: str) -> tuple[str, bool]:
    """Normalize a bare or copied macro reference for show lookup."""
    text = raw.strip()
    if text.startswith("#!"):
        text = text[2:]
    elif text.startswith(("#", "/")):
        text = text[1:]
    if not text:
        return "", False

    lexical = f"#{text}"
    references = iter_macro_references(lexical)
    if not references or references[0].start != 0:
        return text, False
    reference = references[0]
    if lexical[reference.end :].strip():
        return text, False
    return (
        reference.name,
        reference.arg_kind is not MacroReferenceArgKind.NONE,
    )


def resolve_show_record(
    raw_name: str,
    *,
    project: str | None = None,
) -> MacroShowRecord | ShowLookupMiss:
    """Resolve *raw_name* to its definition record or a lookup miss."""
    name, arguments_were_stripped = normalize_show_name(raw_name)
    with collect_macro_load_issues() as load_issues:
        workflows = get_all_workflows(project=project)
        macros = get_all_macros(project=project)

    warnings = [f"skipped: {issue.source}: {issue.error}" for issue in load_issues]
    if arguments_were_stripped:
        warnings.append(f"arguments ignored: resolved {raw_name!r} as {name!r}")

    workflow = workflows.get(name)
    macro_def = macros.get(name)
    if workflow is None and macro_def is None:
        return ShowLookupMiss(
            name=name,
            suggestions=_suggestions(name, workflows, macros),
        )

    if workflow is not None:
        selected_workflow = workflow
        descriptor = _workflow_descriptor(workflow)
        selected_macro = None
        if macro_def is not None:
            shadowed = source_path_display(classify(macro_def, project=project))
            warnings.append(
                f"workflow {name!r} shadows macro from "
                f"{shadowed or macro_def.source_path or '(unknown source)'}"
            )
    else:
        assert macro_def is not None
        selected_workflow = macro_to_workflow(macro_def)
        descriptor = macro_def
        selected_macro = macro_def

    entry = classify(descriptor, project=project)
    provenance, raw = _resolve_provenance(
        name=name,
        reference=workflow_reference_insertion(name, selected_workflow),
        item_kind="workflow" if workflow is not None else "part",
        descriptor=descriptor,
        entry=entry,
        project=project,
        warnings=warnings,
    )

    body = (
        descriptor.content
        if selected_macro is not None
        else selected_workflow.get_prompt_part_content()
        if selected_workflow.has_prompt_part()
        else None
    )
    segment_count = (
        macro_segment_count(Macro(name=name, content=body)) if body is not None else 0
    )
    local_macros = (
        selected_macro.local_macros
        if selected_macro is not None
        else selected_workflow.macros
    )

    return MacroShowRecord(
        name=name,
        reference=workflow_reference_insertion(name, selected_workflow),
        prefix=workflow_reference_prefix(selected_workflow),
        kind=workflow_kind_value(selected_workflow),
        memory_type=selected_workflow.memory_type,
        is_skill=bool(selected_macro and selected_macro.skill),
        skill_name=selected_macro.skill_name if selected_macro else None,
        is_swarm=segment_count > 1,
        segment_count=segment_count,
        description=selected_workflow.description,
        project=entry.project,
        provenance=provenance,
        tags=sorted(tag.value for tag in selected_workflow.tags),
        skill=selected_macro.skill if selected_macro is not None else None,
        snippet=selected_macro.snippet if selected_macro is not None else None,
        log_skill_use=(
            selected_macro.log_skill_use if selected_macro is not None else None
        ),
        input_signature=format_inputs(selected_workflow.inputs) or None,
        inputs=show_inputs(selected_workflow.inputs),
        local_macros=show_local_macros(local_macros),
        steps=show_steps(selected_workflow),
        body=body,
        body_first_line=_body_first_line(provenance, raw, body),
        raw=raw,
        warnings=warnings,
        references=_show_references(body, local_macros, project=project),
    )


def _suggestions(
    name: str,
    workflows: dict[str, Workflow],
    macros: dict[str, Macro],
) -> list[str]:
    names = sorted(set(workflows) | set(macros))
    matches = get_close_matches(name, names, n=5, cutoff=0.5)
    suggestions: list[str] = []
    for match in matches:
        workflow = workflows.get(match)
        if workflow is None:
            workflow = macro_to_workflow(macros[match])
        suggestions.append(workflow_reference_insertion(match, workflow))
    return suggestions


def _workflow_descriptor(workflow: Workflow) -> Macro:
    return Macro(
        name=workflow.name,
        content=workflow.get_prompt_part_content(),
        inputs=workflow.inputs,
        source_path=workflow.source_path,
        tags=workflow.tags,
        description=workflow.description,
        local_macros=workflow.macros,
        memory_type=workflow.memory_type,
    )


def _resolve_provenance(
    *,
    name: str,
    reference: str,
    item_kind: str,
    descriptor: Macro,
    entry: CatalogEntry,
    project: str | None,
    warnings: list[str],
) -> tuple[ShowProvenance, str | None]:
    source_id = descriptor.source_path
    source_display = source_path_display(entry)
    definition = catalog_definition_path(entry)
    path = Path(definition) if definition is not None else None
    if path is None:
        candidate = definition_file_for_source(source_id)
        if candidate is not None and candidate.is_file():
            path = candidate
            definition = str(candidate.resolve(strict=False))

    definition_line = (
        definition_line_for(path, name)
        if path is not None and path.suffix.lower() in {".yml", ".yaml"}
        else None
    )
    raw = _raw_definition(path, source_id, name, warnings)
    hosted_url: str | None = None
    if path is not None:
        try:
            hosted_url = _hosted_url_for_definition(
                path=path,
                reference=reference,
                name=name,
                item_kind=item_kind,
                definition_line=definition_line,
                descriptor=descriptor,
                project=project,
            )
            if hosted_url is None:
                warnings.append(
                    "hosted URL unavailable: no hosted resolver for this definition"
                )
        except Exception as exc:
            warnings.append(f"hosted URL unavailable: {exc}")

    return (
        ShowProvenance(
            source_id=source_id,
            source_bucket=entry.bucket,
            source_display=source_display,
            definition_path=definition,
            definition_line=definition_line,
            hosted_url=hosted_url,
            editable=bool(path is not None and os.access(path, os.W_OK)),
        ),
        raw,
    )


def _raw_definition(
    path: Path | None,
    source_id: str | None,
    name: str,
    warnings: list[str],
) -> str | None:
    if path is None:
        warnings.append("raw definition unavailable: source path could not be resolved")
        return None
    try:
        text = path.read_bytes().decode("utf-8")
        if not _is_config_source(source_id):
            return text
        span = config_entry_line_span(path, name)
        if span is None:
            warnings.append(
                f"raw definition unavailable: config entry {name!r} was not unique"
            )
            return None
        start, end = span
        return "".join(text.splitlines(keepends=True)[start - 1 : end])
    except (OSError, UnicodeError) as exc:
        warnings.append(f"raw definition unavailable: {exc}")
        return None


def _is_config_source(source_id: str | None) -> bool:
    return bool(
        source_id in _CONFIG_SOURCE_IDS
        or (source_id is not None and source_id.startswith(_CONFIG_SOURCE_PREFIXES))
    )


def _body_first_line(
    provenance: ShowProvenance,
    raw: str | None,
    body: str | None,
) -> int | None:
    if raw is None or body is None or provenance.definition_path is None:
        return None
    if _is_config_source(provenance.source_id):
        return None
    if Path(provenance.definition_path).suffix.lower() != ".md":
        return None
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return 1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        first_body_index = index + 1
        if first_body_index < len(lines) and not lines[first_body_index]:
            first_body_index += 1
        return first_body_index + 1
    return 1 if body == raw else None


def _show_references(
    body: str | None,
    local_macros: dict[str, Macro],
    *,
    project: str | None,
) -> list[ShowReference]:
    if not body:
        return []
    rows: list[ShowReference] = []
    seen: set[str] = set()
    for scanned in scan_macro_references(
        body,
        extra_macros=local_macros,
    ):
        if scanned.raw_ref in seen:
            continue
        seen.add(scanned.raw_ref)
        rows.append(
            ShowReference(
                raw_ref=scanned.raw_ref,
                name=scanned.name,
                kind=_show_reference_kind(
                    scanned.name,
                    scanned.kind,
                    scanned.item,
                    local_macros,
                ),
                resolved=scanned.item is not None,
                source_display=_reference_source_display(scanned.item, project),
            )
        )
    return rows


def _show_reference_kind(
    name: str,
    kind: str | None,
    item: Macro | Workflow | None,
    local_macros: dict[str, Macro],
) -> str | None:
    if name in local_macros:
        return "local helper"
    if isinstance(item, Macro) and item.memory_type is not None:
        return "memory"
    if isinstance(item, Workflow) and item.memory_type is not None:
        return "memory"
    if isinstance(item, Macro) and item.skill:
        return "skill"
    if kind == "part":
        return "macro"
    return kind


def _reference_source_display(
    item: Macro | Workflow | None,
    project: str | None,
) -> str | None:
    if item is None:
        return None
    descriptor = item if isinstance(item, Macro) else _workflow_descriptor(item)
    try:
        return source_path_display(classify(descriptor, project=project))
    except Exception:
        return descriptor.source_path


def _hosted_url_for_definition(
    *,
    path: Path,
    reference: str,
    name: str,
    item_kind: str,
    definition_line: int | None,
    descriptor: Macro,
    project: str | None,
) -> str | None:
    """Best-effort hosted URL resolution through existing provenance APIs."""
    from sase.agents_sync.git import run_git
    from sase.content_layout import discover_project_root
    from sase.repo_inventory import collect_repo_inventory
    from sase.sdd.hosted_links import HostedLinkResolver
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store
    from sase.macro.macro_sources import collect_macro_sources
    from sase.macro_links import MacroSourceRecord, MacroTargetResolver

    records = collect_macro_sources(
        reference,
        extra_macros={name: descriptor},
    )
    captured = next((record for record in records if record["name"] == name), None)
    if captured is None:
        return None

    primary_root = (discover_project_root() or Path.cwd()).resolve(strict=False)
    revision_result = run_git(
        primary_root,
        ["rev-parse", "HEAD"],
        op="xprompt_show.revision",
    )
    primary_revision = revision_result.stdout.strip()
    if revision_result.returncode != 0 or not primary_revision:
        return None

    workspace, workspace_num = workspace_context_for_plan_resolution(primary_root)
    store = resolve_sdd_store(workspace, workspace_num)
    hosted = HostedLinkResolver(
        store,
        project=project,
        primary_root=primary_root,
        git_runner=run_git,
    )
    repository_roots: dict[str, Path] = {}
    for inventory_record in collect_repo_inventory().records:
        for raw_root in (
            inventory_record.path,
            *(clone.path for clone in inventory_record.clones),
        ):
            if raw_root and Path(raw_root).is_dir():
                repository_roots.setdefault(
                    inventory_record.name,
                    Path(raw_root).expanduser().resolve(strict=False),
                )

    source_record = cast(
        MacroSourceRecord,
        {
            **captured,
            "kind": item_kind,
            "source_path": str(path),
            "definition_line": definition_line,
        },
    )
    resolver = MacroTargetResolver(
        primary_root=primary_root,
        primary_revision=primary_revision,
        hosted=hosted,
        git_runner=run_git,
        repository_roots=repository_roots,
    )
    return resolver(source_record)


__all__ = [
    "ShowLookupMiss",
    "normalize_show_name",
    "resolve_show_record",
]
