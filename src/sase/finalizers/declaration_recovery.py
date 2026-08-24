"""Recovery turn for a missing or stale finalizer declaration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.pending_handoff import has_pending_handoff
from sase.finalizers.declaration_context_evidence import COMMIT_DECLARATION_RULE
from sase.finalizers.declaration_recovery_evidence import build_recovery_evidence
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    write_text_atomic as _write_text_atomic,
)
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.telemetry.metrics import FINALIZER_RECOVERIES

if TYPE_CHECKING:
    from sase.finalizers.declaration import FinalContextPublication

FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME = "final_declaration_recovery_evidence.md"
FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME = "final_declaration_recovery_prompt.md"
FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME = "final_declaration_recovery_response.md"


def ensure_final_declaration_or_recover(
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: LLMInvocationOptions | None = None,
    original_prompt: str | None = None,
) -> InvokeResult:
    """Run one declaration-recovery turn when required submission is absent."""

    # Import the facade lazily so its monkeypatch seams and public orchestration
    # remain authoritative during recovery without introducing an import cycle.
    from sase.finalizers import declaration

    if has_pending_handoff(artifacts_dir):
        FINALIZER_RECOVERIES.labels(kind="declaration", result="handoff").inc()
        return invoke_result

    context = declaration.publish_final_context(artifacts_dir=artifacts_dir)
    if not context.submission_required or declaration.final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        FINALIZER_RECOVERIES.labels(kind="declaration", result="not_required").inc()
        return invoke_result

    previous_nonce = os.environ.get(declaration.SASE_FINAL_TURN_NONCE_ENV)
    recovery_nonce = declaration.mint_finalizer_turn_nonce()
    try:
        root = declaration.require_artifacts_dir(
            artifacts_dir,
            "finalizer declaration recovery",
        )
        evidence = build_recovery_evidence(
            context=context,
            original_prompt=original_prompt,
            response_text=invoke_result.content,
            artifacts_dir=artifacts_dir,
        )
        _write_text_atomic(
            root / FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME,
            evidence,
        )
        prompt = _declaration_recovery_prompt(context, evidence)
        _write_text_atomic(root / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME, prompt)
        follow_up = provider.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )
        _write_text_atomic(
            root / FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME,
            follow_up.content,
        )
        accumulated = InvokeResult(
            content=append_response(invoke_result.content, follow_up.content),
            usage=merge_usage(invoke_result.usage, follow_up.usage),
        )
        if not _latest_context_matches_nonce(root, recovery_nonce):
            raise RuntimeError(
                "Finalizer declaration recovery failed: no fresh context was "
                "published for the recovery turn"
            )
        if not declaration.final_submission_is_current(artifacts_dir=artifacts_dir):
            raise RuntimeError(
                "Finalizer declaration recovery failed: required declaration "
                "is still missing or invalid"
            )
        FINALIZER_RECOVERIES.labels(kind="declaration", result="success").inc()
        return accumulated
    except Exception:
        FINALIZER_RECOVERIES.labels(kind="declaration", result="failed").inc()
        raise
    finally:
        if previous_nonce is None:
            os.environ.pop(declaration.SASE_FINAL_TURN_NONCE_ENV, None)
        else:
            os.environ[declaration.SASE_FINAL_TURN_NONCE_ENV] = previous_nonce


def _latest_context_matches_nonce(root: Path, nonce: str) -> bool:
    from sase.finalizers.declaration import load_latest_finalizer_context

    try:
        return load_latest_finalizer_context(root).turn_nonce == nonce
    except FinalizerDeclarationError:
        return False


def _declaration_recovery_prompt(
    context: FinalContextPublication,
    evidence: str,
) -> str:
    parts = [
        "A required SASE finalizer declaration was missing or stale after your "
        "normal response.",
        "",
        "This is the single declaration-recovery turn. Do not perform unrelated "
        "work, make no new repository edits, and do not answer the user yet. "
        "Declaring a commit is not an edit you perform; it authorizes the host "
        "finalizer to preserve the work after your turn. Use your `/sase_final` "
        "skill now; it must publish a fresh context for this turn and submit "
        "one valid declaration for every required finalizer payload. After the "
        "declaration succeeds, return briefly.",
    ]
    if evidence.strip():
        parts.extend(
            [
                "",
                evidence.strip(),
                "",
                "The work described above is this turn's own run. Write any "
                "commit message from that evidence; do not assume no work happened.",
            ]
        )
    parts.extend(
        [
            "",
            COMMIT_DECLARATION_RULE,
            "",
            "A deferral needs a typed reason about the repository tree itself: "
            "`protected_paths`, `foreign_work`, `unsafe_content`, or "
            "`belongs_to_another_turn`. Missing conversational context is not "
            'valid. Do not defer because "I have no context", "this is only a '
            'recovery turn", "these files predate me", or "I did not do this '
            'work". When the evidence shows this turn wrote the paths, submit '
            "a conventional commit message instead.",
            "",
            f"Current required context digest: {context.context.context_digest}",
            "",
        ]
    )
    return "\n".join(parts)
