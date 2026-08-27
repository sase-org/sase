"""Settle-time rebuild of the question gate shell's follow-up prompt."""

from __future__ import annotations

import logging
from typing import Any

from sase.main.qa_markdown import build_merged_qa_markdown
from sase.main.qa_prompt import merge_qa_for_prompt

logger = logging.getLogger(__name__)


def question_next_action(
    *,
    artifacts_dir: str,
    meta: dict[str, Any],
    envelope: dict[str, Any],
    response: dict[str, Any],
    declared: str | None,
) -> str | None:
    """Rebuild the merged Q&A follow-up prompt across every round in the chain.

    Registered as the ``question`` kind's settle-time next-action hook (see
    ``sase.gate_shell.kind_next_action``). Returns *declared* when the base
    prompt or the round list comes back empty -- that declared text is
    already short exactly one round, never a sentinel and never empty.

    Uses :func:`build_merged_qa_markdown`, not :func:`merge_qa_for_prompt`:
    ``compose_gate_followup_prompt`` wraps this whole prompt in one disabled
    region, which escapes nested ``%xprompts_enabled:`` markers -- emitting
    ``merge_qa_for_prompt``'s own marker pair inside it would leave visible
    escaped markers. The SDD archive snapshot below keeps the marker-wrapped
    form, since it is written directly rather than re-composed.
    """
    from sase.question_shell.rounds import question_base_prompt, question_rounds

    base_prompt = question_base_prompt(artifacts_dir)
    rounds = question_rounds(artifacts_dir, head_response=response)
    if not base_prompt or not rounds:
        return declared

    try:
        _update_snapshot_if_configured(artifacts_dir, meta, merge_qa_for_prompt(rounds))
    except Exception:
        logger.warning(
            "Question SDD prompt Q&A snapshot update failed; continuing",
            exc_info=True,
        )
    return base_prompt + "\n\n" + build_merged_qa_markdown(rounds)


def _update_snapshot_if_configured(
    artifacts_dir: str, meta: dict[str, Any], merged_qa_text: str
) -> None:
    sdd_spec_path = meta.get("question_sdd_spec_path")
    if not isinstance(sdd_spec_path, str) or not sdd_spec_path:
        return
    update_question_sdd_prompt_snapshot(
        sdd_spec_path,
        merged_qa_text,
        workspace_dir=str(meta.get("workspace_dir") or ""),
        workspace_num=meta.get("workspace_num"),
        artifacts_dir=artifacts_dir,
    )


def update_question_sdd_prompt_snapshot(
    sdd_spec_path: str,
    merged_qa_text: str,
    *,
    workspace_dir: str,
    workspace_num: int | None,
    artifacts_dir: str,
) -> None:
    """Update the recorded prompt artifact and commit machine-made store writes.

    In-tree prompt files remain part of the agent's normal workspace commit
    flow. External stores are committed here so a SASE-authored Q&A update
    never becomes unclaimed work for the commit finalizer. Lifted from
    ``run_agent_exec_questions._update_sdd_prompt_snapshot_qa`` to explicit
    arguments so both the Off branch and the gate-shell settlement hook share
    one implementation.
    """
    from pathlib import Path

    prompt_path = Path(sdd_spec_path)
    parts = prompt_path.parts
    if len(parts) >= 3 and parts[-3] == "prompts" and parts[-2].isdigit():
        from sase.sdd.files import set_prompt_qa

        # The commit finalizer recognizes Q&A-only edits at this canonical
        # agents-sidecar path and commits them without prompting the agent.
        set_prompt_qa(prompt_path, merged_qa_text)
        return

    # Compatibility for an interrupted run that still points at the legacy
    # plans-sidecar prompt location during the cutover.
    from sase.sdd.files import commit_sdd_store_files, set_prompt_qa
    from sase.sdd.store import resolve_sdd_store

    set_prompt_qa(prompt_path, merged_qa_text)

    store = resolve_sdd_store(workspace_dir, workspace_num or 1)
    if store.is_in_tree:
        return

    commit_sdd_store_files(
        store,
        f"Add Q&A to {prompt_path.stem} prompt",
        auto_commit_type="sdd",
        paths=[prompt_path],
        artifacts_dir=artifacts_dir,
    )


__all__ = ["question_next_action", "update_question_sdd_prompt_snapshot"]
