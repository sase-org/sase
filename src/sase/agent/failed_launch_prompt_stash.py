"""Best-effort failed-launch prompt preservation into the prompt stash.

A failed agent launch that still holds the submitted prompt should keep that
prompt recoverable through the existing prompt-stash store, so a long prompt is
not lost once the prompt bar has been unmounted. Recovery happens through the
normal ``gp`` / ``gP`` restore flow.

This adapter is intentionally defensive: it never raises and never replaces the
original launch error. Any stash-store failure (e.g. a missing Rust binding)
degrades exactly like the manual-stash error handling -- it is logged and
swallowed. It writes through the same Rust-backed store as manual stash; the
wire schema is unchanged.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: Source tag stamped on every failed-launch stash row.
FAILED_LAUNCH_STASH_SOURCE = "failed_launch"


def stash_failed_launch_prompt(
    prompt: str,
    *,
    project: str | None = None,
    source: str = FAILED_LAUNCH_STASH_SOURCE,
) -> None:
    """Append *prompt* to the prompt-stash store as a failed-launch row.

    Blank prompts are skipped. A leading YAML frontmatter block (carrying local
    xprompt definitions) is lifted into the entry ``frontmatter`` field and only
    the prompt body is stored as ``text``; multi-prompt bodies are kept joined
    with the canonical ``\\n---\\n`` separator so restore expands them back into
    one pane per segment. Project metadata is best-effort -- losing the project
    chip is acceptable, losing the prompt text is not.

    Never raises: any failure is logged and swallowed so the caller's original
    launch error is preserved.
    """
    if not prompt.strip():
        return

    try:
        from datetime import datetime
        from uuid import uuid4

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            PromptStashEntryWire,
            append_prompt_stash,
        )
        from sase.core.time import get_timezone

        frontmatter, text = _split_prompt_for_stash(prompt)
        entry = PromptStashEntryWire(
            id=str(uuid4()),
            created_at=datetime.now(get_timezone()).isoformat(),
            text=text,
            frontmatter=frontmatter,
            project=project,
            source=source,
            pane_index=0,
        )
        append_prompt_stash(prompt_stash_path(), entry)
    except Exception:  # pragma: no cover - defensive (store/binding/IO error)
        log.warning("Failed to stash failed-launch prompt", exc_info=True)


def _split_prompt_for_stash(prompt: str) -> tuple[str, str]:
    """Split *prompt* into ``(frontmatter, text)`` for a stash row.

    ``frontmatter`` is the raw leading ``---`` YAML block (delimiters included,
    no trailing newline) or ``""`` when absent. ``text`` is the canonical
    multi-prompt body: segments re-joined with ``\\n---\\n``. This mirrors the
    manual-stash capture shape so restore treats both identically.
    """
    from sase.agent.multi_prompt import split_segments_protecting_fences
    from sase.xprompt.loader_parsing import parse_yaml_front_matter

    frontmatter_dict, body = parse_yaml_front_matter(prompt)
    frontmatter = ""
    if frontmatter_dict is not None:
        lines = prompt.split("\n")
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                frontmatter = "\n".join(lines[: index + 1])
                break
        else:
            # Defensive: parse_yaml_front_matter only returns a dict when a
            # closing delimiter exists, so this branch is unreachable.
            body = prompt

    segments = split_segments_protecting_fences(body)
    text = "\n---\n".join(segments) if segments else body.strip()
    return frontmatter, text


__all__ = [
    "FAILED_LAUNCH_STASH_SOURCE",
    "stash_failed_launch_prompt",
]
