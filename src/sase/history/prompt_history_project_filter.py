"""Read-only project-identity adapter for the Ctrl+K prompt-history filter.

Gathers project/Patch identity facts (project records, aliases, provider
owner/repo spellings, Patch ownership) into one immutable catalog snapshot,
and extracts per-segment VCS-ref facts from prompt text -- the raw materials
:mod:`sase.core.prompt_history_filter_facade` needs to compile a query, build
the Ctrl+K seed, and batch-match loaded history rows. No disk/provider I/O
happens on a keystroke path: a snapshot is built once per modal opening.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.prompt_history_filter_facade import (
    build_prompt_history_seed,
    compile_prompt_history_query,
    match_prompt_history_rows,
)
from sase.core.prompt_history_filter_wire import (
    CompiledPromptHistoryQuery,
    PromptHistoryProjectIdentity,
    PromptHistoryRowFacts,
    PromptHistorySeed,
)
from sase.xprompt._parsing_vcs_tags import (
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
    find_vcs_workflow_tag,
    find_vcs_workflow_tag_span,
)
from sase.xprompt._prompt_segments import split_prompt_segments

_GITHUB_PROVIDER_PREFIX = "gh_"
_GITHUB_PROVIDER_SEPARATOR = "__"


def _provider_raw_refs(project_key: str) -> list[str]:
    """Return owner/repo spellings derivable from a ``gh_owner__repo`` key.

    Never guesses ownership from a displayed basename -- only the directory
    key's own well-known provider naming convention.
    """
    if not project_key.startswith(_GITHUB_PROVIDER_PREFIX):
        return []
    rest = project_key[len(_GITHUB_PROVIDER_PREFIX) :]
    owner, sep, repo = rest.partition(_GITHUB_PROVIDER_SEPARATOR)
    if not sep or not owner or not repo:
        return []
    return [f"{owner}/{repo}"]


def _patch_raw_refs_by_project() -> dict[str, list[str]]:
    """Return each project's Patch names, from local read-only records.

    Ownership comes from the Patch's own recorded project directory, never
    from parsing the Patch's name as a prefix guess.
    """
    try:
        from sase.ace.patch.cache import find_all_patches_cached
    except Exception:
        return {}
    try:
        patches = find_all_patches_cached(include_states=("enabled", "disabled"))
    except Exception:
        return {}

    by_project: dict[str, list[str]] = defaultdict(list)
    for patch in patches:
        try:
            project_key = patch.project_name
        except Exception:
            continue
        if project_key and patch.name:
            by_project[project_key].append(patch.name)
    return dict(by_project)


@dataclass(frozen=True)
class PromptHistoryProjectCatalog:
    """One immutable project-identity snapshot for one modal opening."""

    entries: tuple[PromptHistoryProjectIdentity, ...]

    @classmethod
    def load(cls) -> PromptHistoryProjectCatalog:
        """Build a fresh snapshot from local read-only project/Patch records."""
        try:
            records = list_project_records(
                sase_projects_dir(), "all", include_home=True
            )
        except Exception:
            records = []

        patch_refs = _patch_raw_refs_by_project()
        entries = tuple(
            PromptHistoryProjectIdentity(
                key=record.project_name,
                label=record.display_name,
                aliases=list(record.aliases),
                raw_refs=[
                    *_provider_raw_refs(record.project_name),
                    *patch_refs.get(record.project_name, []),
                ],
            )
            for record in records
        )
        return cls(entries=entries)

    def compile_query(self, raw_query: str) -> CompiledPromptHistoryQuery:
        """Compile *raw_query* against this snapshot."""
        return compile_prompt_history_query(raw_query, list(self.entries))

    def resolve_ref(self, raw_ref: str | None) -> str | None:
        """Resolve *raw_ref* to a canonical project key, when unambiguous."""
        if not raw_ref:
            return None
        compiled = self.compile_query(f"project:{_quote_qualifier_value(raw_ref)}")
        return compiled.project_key

    def build_seed(
        self, *, raw_ref: str | None, remainder_text: str
    ) -> PromptHistorySeed:
        """Build the initial Ctrl+K history query from recognized ref facts."""
        return build_prompt_history_seed(
            raw_ref=raw_ref,
            remainder_text=remainder_text,
            catalog=list(self.entries),
        )


def _quote_qualifier_value(value: str) -> str:
    """Quote *value* for embedding as a ``project:`` qualifier value."""
    if value and not any(ch.isspace() for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _segment_active_ref(segment: str) -> str | None:
    """Return the active (leading, else embedded) VCS ref text for *segment*."""
    tag = extract_vcs_workflow_tag(segment) or find_vcs_workflow_tag(segment)
    if not tag:
        return None
    return extract_project_from_vcs_tag(tag)


def prepare_prompt_history_row_facts(
    index: int,
    canonical_text: str,
    display_text: str,
    catalog: PromptHistoryProjectCatalog,
) -> PromptHistoryRowFacts:
    """Prepare one loaded history row's per-segment project-ref facts.

    Splits *canonical_text* into its multi-prompt segments and resolves each
    segment's active VCS ref (if any) to a canonical project key, so a row
    matches a ``project:`` constraint when any segment belongs to it. A
    legacy record with no active ref in any segment has no inferred project
    and stays reachable unscoped.
    """
    pieces, _separators = split_prompt_segments(canonical_text)
    segment_raw_refs = [_segment_active_ref(piece) for piece in pieces] or [None]
    segment_project_keys = [catalog.resolve_ref(ref) for ref in segment_raw_refs]
    return PromptHistoryRowFacts(
        index=index,
        canonical_text=canonical_text,
        display_text=display_text,
        segment_project_keys=segment_project_keys,
        segment_raw_refs=segment_raw_refs,
    )


def _remove_span_with_boundary_whitespace(text: str, start: int, end: int) -> str:
    """Remove ``text[start:end]`` plus exactly one adjacent boundary space."""
    before = text[:start]
    after = text[end:]
    if before.endswith(" "):
        before = before[:-1]
    elif after.startswith(" "):
        after = after[1:]
    return before + after


def build_prompt_history_seed_from_draft(
    draft: str,
    catalog: PromptHistoryProjectCatalog,
) -> PromptHistorySeed:
    """Build the initial Ctrl+K history query from a single-line prompt draft.

    Uses the first active workspace reference recognized anywhere in
    *draft* (skipping inline/fenced code and disabled xprompt regions),
    consistent with the existing VCS span helper. The draft itself is never
    mutated; only the derived seed text is returned.
    """
    span = find_vcs_workflow_tag_span(draft)
    if span is None:
        return catalog.build_seed(raw_ref=None, remainder_text=draft)

    start, end = span
    raw_ref = extract_project_from_vcs_tag(draft[start:end])
    remainder = _remove_span_with_boundary_whitespace(draft, start, end)
    return catalog.build_seed(raw_ref=raw_ref, remainder_text=remainder)


def filtered_prompt_history_row_indices(
    compiled_query: CompiledPromptHistoryQuery,
    row_facts: list[PromptHistoryRowFacts],
) -> frozenset[int]:
    """Return the indices of *row_facts* matching *compiled_query*."""
    return match_prompt_history_rows(compiled_query, row_facts)


__all__ = [
    "PromptHistoryProjectCatalog",
    "build_prompt_history_seed_from_draft",
    "filtered_prompt_history_row_indices",
    "prepare_prompt_history_row_facts",
]
