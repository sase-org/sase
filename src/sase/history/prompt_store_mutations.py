"""Prompt-history mutation workflows."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: the facade is imported at call time so either module can be
    # imported first without a circular ImportError.
    from sase.history import prompt_store as store


@dataclass(frozen=True)
class _PromptMutation:
    """A prompt history mutation to apply under the writer lock."""

    text: str
    cancelled: bool
    force_cancelled: bool = False
    origin: store.PromptOrigin | None = None


def effective_prompt_origin(
    origin: store.PromptOrigin | None,
    *,
    launch_envs: tuple[Mapping[str, str] | None, ...] = (),
) -> store.PromptOrigin | None:
    """Resolve the write-time origin for one launch.

    ``generated`` means "do not write": the writers treat it as a no-op so
    machine-originated launches leave no row, no placeholder, and no Stash
    entry. An explicit ``generated`` origin, a chop/job marker in any of the
    launch's own *launch_envs* mappings, or a ``SASE_AGENT`` process
    environment each resolve to ``generated``. ``None`` (unknown/legacy path)
    is left alone so historical rows keep their unwritten state.

    *launch_envs* holds launch parameters only, never ``os.environ``: chop
    markers count only when the launch itself carries them, because surfaces
    such as the Telegram inbound handler run inside a job tick whose process
    env carries the same markers for human prompts.
    """
    from sase.axe.chop_agents import is_chop_launch_env

    if origin == "generated":
        return "generated"
    if any(is_chop_launch_env(env) for env in launch_envs):
        return "generated"
    if os.environ.get("SASE_AGENT"):
        return "generated"
    return origin


def add_or_update_prompt(
    text: str,
    *,
    cancelled: bool = False,
    allow_short: bool = False,
    record_segments: bool = True,
    origin: store.PromptOrigin | None = None,
) -> None:
    """Add a new prompt or update an existing prompt's last_used timestamp.

    If a prompt with the same text already exists, updates its last_used timestamp.
    Otherwise, adds a new entry.

    Args:
        text: The prompt text to add or update.
        cancelled: If True, mark this prompt as cancelled (unsent). An existing
            non-cancelled prompt will not be downgraded to cancelled.
        allow_short: If True, record the prompt even when it is shorter than
            the normal history threshold. This is used for replayable generated
            fanout invocations such as a bare macro swarm trigger.
        record_segments: If True, multi-prompts also record their individual
            long-enough segments. If False, only the exact prompt text passed by
            the caller is written.

    Placeholder tags are recorded before the history threshold is applied, so
    even a sub-five-word prompt contributes its ``<foobar>`` tags to the common
    placeholder store. Cancelled prompts contribute too: the user wrote those
    tags, and recovering one from an abandoned draft is exactly what makes the
    completion menu feel like it remembers. Span extraction covers the whole
    string, so multi-prompt segments need no separate call.

    A ``generated`` origin writes nothing at all: no row, no placeholder, and
    no ``last_used`` bump of an already-typed row.
    """
    from sase.history import prompt_store as store

    effective_origin = effective_prompt_origin(origin)
    if effective_origin == "generated":
        return

    from sase.history.prompt_placeholders import record_prompt_placeholders

    record_prompt_placeholders(text)

    if not store.is_recordable_prompt(text, allow_short=allow_short):
        return

    current_timestamp = store.generate_timestamp()
    mutations = [
        _PromptMutation(text=text, cancelled=cancelled, origin=effective_origin)
    ]
    if record_segments:
        mutations.extend(
            _multi_prompt_segment_mutations(
                text, cancelled=cancelled, origin=effective_origin
            )
        )

    _apply_prompt_mutations(mutations, current_timestamp)


def record_failed_launch_prompt(
    text: str,
    *,
    project: str | None = None,
    origin: store.PromptOrigin | None = None,
) -> None:
    """Record a submitted prompt whose launch failed before producing agents.

    Failed launch attempts are different from ordinary prompt-bar cancellation:
    the user submitted the prompt, so even short prompts such as ``#gh:foo`` are
    useful history, and an earlier optimistic successful write must be forced
    back to cancelled.

    The submitted prompt is also preserved in the prompt stash (best-effort) so
    a long prompt remains recoverable through ``gp`` / ``gP`` after the prompt
    bar has been unmounted. ``project`` is optional best-effort metadata for the
    restore picker's project chip; it never gates recovery of the prompt text.

    A failed launch still records the prompt's ``<foobar>`` tags in the common
    placeholder store: the user wrote them, so they stay available in the next
    prompt's completion menu even though the launch produced no agents.

    A ``generated`` origin writes nothing at all: no row, no placeholder, and
    no Stash entry.
    """
    from sase.history import prompt_store as store

    if not text.strip():
        return

    effective_origin = effective_prompt_origin(origin)
    if effective_origin == "generated":
        return

    from sase.history.prompt_placeholders import record_prompt_placeholders

    record_prompt_placeholders(text)

    current_timestamp = store.generate_timestamp()
    mutations = [
        _PromptMutation(
            text=text,
            cancelled=True,
            force_cancelled=True,
            origin=effective_origin,
        )
    ]
    mutations.extend(
        _PromptMutation(
            text=mutation.text,
            cancelled=True,
            force_cancelled=True,
            origin=effective_origin,
        )
        for mutation in _multi_prompt_segment_mutations(text, cancelled=True)
    )

    _apply_prompt_mutations(mutations, current_timestamp)

    from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt

    stash_failed_launch_prompt(text, project=project)


def _multi_prompt_segment_mutations(
    text: str,
    *,
    cancelled: bool,
    origin: store.PromptOrigin | None = None,
) -> list[_PromptMutation]:
    """Return history mutations for long-enough multi-prompt segments."""
    from sase.history import prompt_store as store

    from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt

    if not is_multi_prompt(text):
        return []

    multi = parse_multi_prompt(text)
    mutations = []
    for segment in multi.segments:
        if not store.is_recordable_prompt(segment):
            continue
        mutations.append(
            _PromptMutation(text=segment, cancelled=cancelled, origin=origin)
        )
    return mutations


def _multi_prompt_segment_rewrite_pairs(
    old_text: str,
    new_text: str,
) -> list[tuple[str, str]]:
    """Return exact old/new segment pairs for a rewritten multi-prompt."""
    from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt

    if not is_multi_prompt(old_text) or not is_multi_prompt(new_text):
        return []

    old_multi = parse_multi_prompt(old_text)
    new_multi = parse_multi_prompt(new_text)
    if len(old_multi.segments) != len(new_multi.segments):
        return []

    return [
        (old_segment, new_segment)
        for old_segment, new_segment in zip(
            old_multi.segments,
            new_multi.segments,
            strict=True,
        )
        if old_segment != new_segment
    ]


def rewrite_prompt_text_exact(old_text: str, new_text: str) -> int:
    """Rewrite prompt-history entries by exact text match.

    The rewrite is intentionally conservative: it replaces only rows whose
    ``text`` exactly matches *old_text*, plus exact multi-prompt segment rows
    derived from old/new segment pairs. Fuzzy matching is never used.

    Returns the number of history rows whose text changed.

    Raises:
        PromptHistoryLoadError: If the current history cannot be safely loaded
            or saved for mutation.
    """
    if old_text == new_text:
        return 0

    from sase.history import prompt_store as store

    replacements: dict[str, str] = {old_text: new_text}
    replacements.update(_multi_prompt_segment_rewrite_pairs(old_text, new_text))

    with store.locked_prompt_history():
        store.ensure_migrated()
        entries: list[store.PromptEntry] = []
        for path in store.iter_shard_paths_newest_first():
            shard_entries = store.load_shard_for_write(path)
            shard_entries.sort(key=lambda entry: entry.last_used, reverse=True)
            entries.extend(shard_entries)

        changed = 0
        for entry in entries:
            replacement = replacements.get(entry.text)
            if replacement is None:
                continue
            entry.text = replacement
            changed += 1

        if changed == 0:
            return 0

        entries.sort(key=lambda entry: entry.last_used, reverse=True)
        deduped = store.dedup_prompt_entries_newest_first(iter(entries))
        if not store.save_prompt_history(deduped):
            raise store.PromptHistoryLoadError
        return changed


def _apply_prompt_mutations(
    mutations: list[_PromptMutation],
    current_timestamp: str,
) -> bool:
    """Apply prompt mutations to the current month shard under the writer lock."""
    from sase.history import prompt_store as store

    with store.locked_prompt_history():
        try:
            store.ensure_migrated()
            path = store.shard_path(store.shard_key_for_timestamp(current_timestamp))
            prompts = store.load_shard_for_write(path)
        except store.PromptHistoryLoadError:
            return False

        for mutation in mutations:
            existing = next((p for p in prompts if p.text == mutation.text), None)
            if existing:
                existing.last_used = current_timestamp
                if mutation.force_cancelled:
                    existing.cancelled = True
                elif not mutation.cancelled:
                    # Normal cancellation only upgrades to non-cancelled, never
                    # downgrades an already-successful prompt.
                    existing.cancelled = False
                # Origin merges typed-wins and never downgrades, mirroring the
                # cancelled rule above.
                existing.origin = store.merge_prompt_origin(
                    existing.origin, mutation.origin
                )
                continue

            prompts.append(
                store.PromptEntry(
                    text=mutation.text,
                    timestamp=current_timestamp,
                    last_used=current_timestamp,
                    cancelled=mutation.cancelled,
                    origin=mutation.origin,
                )
            )

        prompts.sort(key=lambda entry: entry.last_used, reverse=True)
        return store.save_shard(path, prompts)
