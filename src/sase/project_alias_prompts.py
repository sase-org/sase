"""VCS prompt rewriting for canonical and human-readable project refs."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks


def _candidate_prompt(prompt: str) -> tuple[str, list[str]]:
    fenced_blocks: list[str] = []
    return protect_fenced_blocks(prompt, fenced_blocks), fenced_blocks


def _rewrite_ref_with_known_prefix(
    ref: str,
    replacement_by_ref: Mapping[str, str],
    *,
    allow_prefix_rewrite: Callable[[str, str], bool] | None = None,
) -> str | None:
    replacement = replacement_by_ref.get(ref)
    if replacement is not None:
        return replacement
    if "_" not in ref:
        return None
    for known_ref, known_replacement in sorted(
        replacement_by_ref.items(),
        key=lambda item: (-len(item[0]), item[0]),
    ):
        prefix = f"{known_ref}_"
        if ref.startswith(prefix):
            if allow_prefix_rewrite is not None and not allow_prefix_rewrite(
                ref, known_replacement
            ):
                return None
            return f"{known_replacement}_{ref[len(prefix) :]}"
    return None


def canonicalize_project_aliases_in_prompt(
    prompt: str,
    *,
    pattern: re.Pattern[str],
    load_alias_map: Callable[[], Mapping[str, str]],
    load_changespec_names: Callable[[str], frozenset[str]],
    project_workflow_type: Callable[[str], str | None],
) -> str:
    """Rewrite project alias refs using injected resolution dependencies."""
    protected, fenced_blocks = _candidate_prompt(prompt)
    if pattern.search(protected) is None:
        return prompt

    alias_map = load_alias_map()
    if not alias_map:
        return prompt

    changespec_names_by_project: dict[str, frozenset[str]] = {}

    def changespec_names(project: str) -> frozenset[str]:
        names = changespec_names_by_project.get(project)
        if names is None:
            names = load_changespec_names(project)
            changespec_names_by_project[project] = names
        return names

    workflow_type_by_project: dict[str, str | None] = {}

    def workflow_type_for(project: str) -> str | None:
        if project not in workflow_type_by_project:
            workflow_type_by_project[project] = project_workflow_type(project)
        return workflow_type_by_project[project]

    aliases_by_project: dict[str, list[str]] = {}
    for alias, project in alias_map.items():
        aliases_by_project.setdefault(project, []).append(alias)
    for aliases in aliases_by_project.values():
        aliases.sort(key=lambda item: (-len(item), item))

    canonical_projects = sorted(
        aliases_by_project,
        key=lambda item: (-len(item), item),
    )

    def repair_mangled_ref(ref: str) -> str | None:
        for project in canonical_projects:
            prefix = f"{project}_"
            if not ref.startswith(prefix):
                continue

            suffix = ref[len(prefix) :]
            names = changespec_names(project)
            if ref in names or suffix in names:
                return None

            for alias in aliases_by_project[project]:
                candidate = f"{alias}_{suffix}"
                if candidate in names:
                    return candidate
        return None

    def replace(match: re.Match[str]) -> str:
        ref = match.group("ref") or match.group("paren") or ""
        canonical = alias_map.get(ref)
        if canonical is None:
            canonical = repair_mangled_ref(ref)
        if canonical is None:
            canonical = _rewrite_ref_with_known_prefix(
                ref,
                alias_map,
                allow_prefix_rewrite=lambda original_ref, project: (
                    original_ref not in changespec_names(project)
                ),
            )
        if canonical is None:
            return match.group(0)

        tag_workflow_type = match.group("workflow")
        actual_workflow_type = workflow_type_for(canonical)
        if (
            actual_workflow_type is not None
            and actual_workflow_type != tag_workflow_type
        ):
            # The alias resolves to a real project, but that project's actual
            # provider doesn't match the tag the user typed. Canonicalizing
            # would aim a mistyped tag (e.g. #git:sase) at the real spec key
            # of an unrelated-provider project (e.g. a GitHub project),
            # letting a downstream resolver silently convert it. Leave it
            # untouched so it stays a harmless, non-resolving ref.
            return match.group(0)

        prefix = (
            f"{match.group('context')}#"
            f"{match.group('workflow')}{match.group('marker') or ''}"
        )
        if match.group("paren") is not None:
            return f"{prefix}({canonical})"
        return f"{prefix}:{canonical}"

    canonicalized = pattern.sub(replace, protected)
    return unprotect_fenced_blocks(canonicalized, fenced_blocks)


def humanize_project_refs_in_prompt(
    prompt: str,
    display_name_by_project: Mapping[str, str],
    *,
    pattern: re.Pattern[str],
) -> str:
    """Rewrite canonical project refs using display-name dependencies."""
    protected, fenced_blocks = _candidate_prompt(prompt)
    if pattern.search(protected) is None:
        return prompt

    def replace(match: re.Match[str]) -> str:
        ref = match.group("ref") or match.group("paren") or ""
        display_name = _rewrite_ref_with_known_prefix(ref, display_name_by_project)
        if not display_name or display_name == ref:
            return match.group(0)

        prefix = (
            f"{match.group('context')}#"
            f"{match.group('workflow')}{match.group('marker') or ''}"
        )
        if match.group("paren") is not None:
            return f"{prefix}({display_name})"
        return f"{prefix}:{display_name}"

    humanized = pattern.sub(replace, protected)
    return unprotect_fenced_blocks(humanized, fenced_blocks)
