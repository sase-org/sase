"""Autonomy-toggle mutation for worker-safe directive persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

from ._directive_persistence_io import (
    agent_directive_lock,
    read_json_object,
    write_json_file,
)
from ._directive_persistence_prompts import persist_prompt_artifacts


def persist_autonomy_toggle(
    artifacts_dir: str | Path,
    selection: str,
    *,
    expected_revision: int | None = None,
    surface: str = "tui",
    principal: str = "",
) -> dict[str, Any]:
    """Apply an ``A``-toggle autonomy mutation under the per-agent lock.

    *selection* is ``"manual"`` (toggle off) or ``"restore"`` (toggle on).
    Reads the live record, calls core ``mutate_autonomy`` with a human
    actor, writes ``record_meta_patch``, and rewrites the stored prompt
    token from the resulting selection so retry and fork replay what the
    user sees. A ``stale`` result re-reads and retries once, then reports.
    Pre-E1 agents with only legacy keys translate first and gain a record
    on this toggle. Returns ``{"status", "record", "reason"}``.
    """
    from sase.autonomy.record import (
        apply_record_meta_patch,
        mutate_record,
        read_record,
        resolve_selection,
        selection_to_prompt_prefix,
    )

    artifacts_path = Path(artifacts_dir).expanduser()
    with agent_directive_lock(artifacts_path):
        meta_path = artifacts_path / "agent_meta.json"
        meta = read_json_object(meta_path)
        base = read_record(meta)
        if base is None:
            # Manual by absence, or a legacy-only pre-E1 agent: translate
            # first so the toggle gains a record; otherwise start manual.
            base = resolve_selection(None, source=surface, surface=surface)
            # When legacy keys exist, prefer their translation so the first
            # toggle preserves the launched profile in ``last``.
            translated = read_record(meta)
            if translated is not None:
                base = translated
        attempt_expected: int | None = expected_revision
        if attempt_expected is None and isinstance(base.get("revision"), int):
            attempt_expected = int(base["revision"])
        outcome: dict[str, Any] | None = None
        for _ in range(2):
            try:
                outcome = mutate_record(
                    base,
                    selection,
                    expected_revision=attempt_expected,
                    actor_kind="human",
                    surface=surface,
                    principal=principal,
                )
            except Exception as exc:
                return {"status": "refused", "record": base, "reason": str(exc)}
            if outcome.get("status") != "stale":
                break
            # Stale: re-read live and retry once without a revision check.
            meta = read_json_object(meta_path)
            reread = read_record(meta)
            if reread is None:
                break
            base = reread
            attempt_expected = None
        assert outcome is not None
        status = str(outcome.get("status", "refused"))
        record = outcome.get("record")
        if not isinstance(record, dict) or not record:
            return outcome
        if status in ("applied", "unchanged"):
            updated = dict(meta)
            try:
                from sase.autonomy.record import (
                    LEGACY_AUTONOMY_KEYS,
                    legacy_projection,
                    record_only,
                )

                apply_record_meta_patch(updated, record)
                if not record_only():
                    # Drop stale legacy keys the new projection no longer
                    # carries (e.g. a toggled-off ``approve: True``): the
                    # shared patch only adds truthy keys.
                    try:
                        projection = legacy_projection(record)
                    except Exception:
                        projection = {}
                    for key in LEGACY_AUTONOMY_KEYS:
                        if key not in (
                            "approve",
                            "auto_approve_argument",
                            "auto_approve_plan_action",
                            "plan",
                        ):
                            continue
                        if projection.get(key) in (None, False):
                            updated.pop(key, None)
            except Exception:
                updated["autonomy"] = record
            if updated != meta:
                write_json_file(meta_path, updated)
                update_agent_artifact_index_for_marker_mutation(str(artifacts_path))
                from sase.core.agent_tribe_evidence import (
                    invalidate_agent_tribe_evidence_cache,
                )

                invalidate_agent_tribe_evidence_cache()
            prefix = selection_to_prompt_prefix(record.get("selection")).strip()
            try:
                from sase.macro._directive_edit_core import set_prompt_directive

                def _rewrite_auto(prompt: str) -> str:
                    return set_prompt_directive(prompt, {"auto"}, prefix or None)

                persist_prompt_artifacts(artifacts_path, _rewrite_auto)
            except Exception:
                pass
        return outcome


__all__ = [
    "persist_autonomy_toggle",
]
