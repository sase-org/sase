"""Shared live-autonomy prompt rewrite for restarts and retries.

A restart after ``A`` off must not resurrect auto: the failed agent's stored
prompt still carries its launch-time ``%auto``, while the live record is
manual. The live selection wins, preserving ``:plan`` exactly; without a
live record the prompt passes through unchanged.
"""

from __future__ import annotations


def rewrite_prompt_from_live_record(prompt: str, artifacts_dir: str) -> str:
    """Rewrite *prompt*'s ``%auto`` token from the live autonomy record."""
    try:
        from sase.autonomy.record import live_record, selection_to_prompt_prefix
        from sase.macro._directive_edit_core import set_prompt_directive
    except Exception:
        return prompt
    try:
        record = live_record(artifacts_dir)
    except Exception:
        return prompt
    if record is None:
        return prompt
    prefix = selection_to_prompt_prefix(record.get("selection")).strip()
    try:
        return set_prompt_directive(prompt, {"auto"}, prefix or None)
    except Exception:
        return prompt


__all__ = ["rewrite_prompt_from_live_record"]
