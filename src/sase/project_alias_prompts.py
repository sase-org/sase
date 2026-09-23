"""VCS prompt rewriting for canonical and human-readable project refs."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Hashable, Mapping, Sequence

from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

_PROJECT_LOOKUP_CACHE_LOCK = threading.RLock()
_WORKFLOW_TYPE_CACHE: dict[tuple[int, str, Hashable], str | None] = {}
_CHANGESPEC_NAMES_CACHE: dict[tuple[int, str, Hashable], frozenset[str]] = {}


def _cached_project_lookup[T](
    cache: dict[tuple[int, str, Hashable], T],
    loader: Callable[[str], T],
    project: str,
    signature_for: Callable[[str], Hashable] | None,
) -> T:
    if signature_for is None:
        return loader(project)

    signature = signature_for(project)
    loader_id = id(loader)
    key = (loader_id, project, signature)
    with _PROJECT_LOOKUP_CACHE_LOCK:
        if key in cache:
            return cache[key]

    value = loader(project)

    with _PROJECT_LOOKUP_CACHE_LOCK:
        for stale_key in tuple(cache):
            if stale_key[:2] == (loader_id, project) and stale_key != key:
                del cache[stale_key]
        cache[key] = value
    return value


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
    load_changespec_names_cache_signature: Callable[[str], Hashable] | None = None,
    project_workflow_type: Callable[[str], str | None],
    project_workflow_type_cache_signature: Callable[[str], Hashable] | None = None,
) -> str:
    """Rewrite project alias refs using injected resolution dependencies."""
    protected, fenced_blocks = _candidate_prompt(prompt)
    if pattern.search(protected) is None:
        return prompt

    alias_map = load_alias_map()
    if not alias_map:
        return prompt

    def changespec_names(project: str) -> frozenset[str]:
        return _cached_project_lookup(
            _CHANGESPEC_NAMES_CACHE,
            load_changespec_names,
            project,
            load_changespec_names_cache_signature,
        )

    def workflow_type_for(project: str) -> str | None:
        return _cached_project_lookup(
            _WORKFLOW_TYPE_CACHE,
            project_workflow_type,
            project,
            project_workflow_type_cache_signature,
        )

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
    project_tags: bool = True,
    project_tag_targets: Sequence[object] | None = None,
) -> str:
    """Rewrite canonical project refs using display-name dependencies.

    When *project_tags* is true (default), colon-form project refs that
    resolve to a taggable project are additionally tagified to ``+<name>``
    (D5): ``#gh:sase`` becomes ``+sase``. Patch refs, ``owner/repo``,
    ``@agent`` spellings, paren forms, HITL-marked refs, and
    mismatched-provider refs are never tagified, nor are refs outside a
    tag position (``(#gh:sase)``, ``#gh:sase,``) whose tag form would not
    re-parse. Tagify degrades to today's ``#`` output when the catalog
    is cold.
    """
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
    if project_tags:
        humanized = _tagify_project_refs_in_prompt(
            humanized,
            pattern,
            project_tag_targets,
        )
    return unprotect_fenced_blocks(humanized, fenced_blocks)


def _tagify_project_refs_in_prompt(
    protected: str,
    pattern: re.Pattern[str],
    project_tag_targets: Sequence[object] | None,
) -> str:
    """Rewrite ``#<workflow>:<ref>`` project refs to ``+<name>`` (D5).

    Operates on fenced-protected text so literal zones stay inert. Never
    raises: an unavailable catalog leaves the text unchanged.
    """
    targets = _project_tag_targets_for_tagify(project_tag_targets)
    if not targets:
        return protected

    def replace(match: re.Match[str]) -> str:
        if match.group("paren") is not None:
            return match.group(0)
        if match.group("marker"):
            return match.group(0)
        if not _is_tag_position(protected, match):
            return match.group(0)
        ref = match.group("ref") or ""
        target = _tagify_target_for_ref(ref, targets)
        if target is None:
            return match.group(0)
        workflow = match.group("workflow")
        if _target_field(target, "workflow_type") != workflow:
            return match.group(0)
        tag = _target_field(target, "tag")
        if not isinstance(tag, str) or not tag.startswith("+"):
            return match.group(0)
        return f"{match.group('context')}{tag}"

    try:
        return pattern.sub(replace, protected)
    except Exception:
        return protected


def _project_tag_targets_for_tagify(
    project_tag_targets: Sequence[object] | None,
) -> Sequence[object]:
    """Return tagify targets from the seam or the warm catalog snapshot."""
    if project_tag_targets is not None:
        return project_tag_targets
    try:
        from sase.project_tags.catalog import peek_project_tag_catalog

        catalog = peek_project_tag_catalog()
    except Exception:
        return ()
    if catalog is None:
        return ()
    try:
        return catalog.targets
    except Exception:
        return ()


def _is_tag_position(protected: str, match: re.Match[str]) -> bool:
    """Return whether a ``#`` match sits where its tag form would scan (D1).

    Tagify rewrites ``#<workflow>:<ref>`` to ``+<name>``, and relaunch,
    fork, copy, and MRU-cycling texts go back into an editor where they
    must expand identically (D5). The tag form only scans as a standalone
    word — ``+`` at the start of the text or after whitespace, ``{``, or
    ``|``, with the name followed by the end of the text, whitespace,
    ``|``, or ``}`` — so a ref in any other position (``(#gh:sase)``,
    ``#gh:sase,``, ``#gh:sase!!``) keeps its ``#`` spelling.
    """
    context = match.group("context") or ""
    if context != "" and not (context[-1].isspace() or context[-1] in "{|"):
        return False
    end = match.end()
    if end < len(protected):
        follower = protected[end]
        if not (follower.isspace() or follower in "|}"):
            return False
    return True


def _target_field(target: object, name: str) -> object:
    if isinstance(target, Mapping):
        return target.get(name)
    return getattr(target, name, None)


def _tagify_target_for_ref(ref: str, targets: Sequence[object]) -> object | None:
    """Return the unambiguous tag target claiming *ref*, or ``None``.

    A claim is an exact case-insensitive match on the target's directory
    key, display name, or alias. Ambiguous claims never guess.
    """
    if not ref:
        return None
    folded = ref.casefold()
    match: object | None = None
    for target in targets:
        candidates = [_target_field(target, "key"), _target_field(target, "name")]
        aliases = _target_field(target, "aliases")
        if isinstance(aliases, (list, tuple)):
            candidates.extend(aliases)
        if any(
            isinstance(item, str) and item.casefold() == folded for item in candidates
        ):
            if match is not None:
                return None
            match = target
    return match
