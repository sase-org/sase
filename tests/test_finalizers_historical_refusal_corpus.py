"""Regression corpus: the nine historical commit-finalizer refusals.

Each fixture below reproduces one real refusal from the incident review in
`plan:202608/finalizer_commit_authoring.md` and asserts the outcome the
authoring/deferral protocol now produces for it. This corpus is the
acceptance criterion for the `sase-sp` epic: five refusals argued the
conversation ("the user didn't ask") and are now unrepresentable, two argued
recovery-turn confusion and are rejected with host counter-evidence, and two
were genuine scope judgments that are upheld as typed deferrals.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)

from .finalizer_declaration_channel_test_helpers import (
    add_deferral,
    attempt_records,
    prepare_dirty_declaration,
    valid_manifest,
    write_run_start_baseline,
)


@dataclass(frozen=True)
class _ConsentPriorRefusal:
    run_id: str
    agent: str
    reason: str


# The five refusals that argued the conversation rather than the tree. None
# of these reasons name a member of FINALIZER_DEFERRAL_REASONS, and the old
# free-text `refuse` action they used no longer exists, so they are
# unrepresentable in the new protocol.
_CONSENT_PRIOR_REFUSALS = (
    _ConsentPriorRefusal(
        "20260821091141", "098--code", "no commit was requested for this turn"
    ),
    _ConsentPriorRefusal(
        "20260822055049",
        "toobig-3e…declaration.0",
        "did not request a git commit",
    ),
    _ConsentPriorRefusal(
        "20260822173908",
        "toobig-3h…controller.0--1",
        "did not ask for a git commit",
    ),
    _ConsentPriorRefusal("20260823115128", "0bg--2", "The user did not ask to commit"),
    _ConsentPriorRefusal(
        "20260824083442",
        "research.10.cdx",
        "did not explicitly request a commit",
    ),
)


@pytest.mark.parametrize(
    "refusal",
    _CONSENT_PRIOR_REFUSALS,
    ids=[f"{r.run_id}:{r.agent}" for r in _CONSENT_PRIOR_REFUSALS],
)
def test_consent_prior_refusal_is_unrepresentable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refusal: _ConsentPriorRefusal,
) -> None:
    """A "the user didn't ask" refusal has no legal shape in the new payload."""

    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "refuse"
    decision.pop("message")
    decision["reason"] = refusal.reason

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_action_invalid"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    attempts = attempt_records(tmp_path)
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "commit_action_invalid"


def test_research_0w_cld_recovery_turn_deferral_is_rejected_with_baseline_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`20260822155532` `research.0w.cld` cited "do not mutate repositories"
    during declaration recovery. The named path is this run's own new write
    per the run-start baseline, so the closest-fitting typed deferral is
    rejected rather than silently accepted."""

    prepare_dirty_declaration(monkeypatch, tmp_path)
    write_run_start_baseline(tmp_path, tmp_path, fingerprints={})
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="belongs_to_another_turn",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    message = str(exc_info.value)
    assert "src/app.py" in message
    assert "new or changed after this run began" in message


def test_sase_s9_2_recovery_turn_deferral_is_rejected_with_write_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`20260823120149` `sase-s9.2` claimed to "lack context to authorize a
    commit". This run's own `tool_calls.jsonl` shows it wrote the file, so
    the closest-fitting typed deferral is rejected with that evidence."""

    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/app.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="foreign_work",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    assert "write/edit tool calls" in str(exc_info.value)


def test_09l_code_sidecar_scope_deferral_is_upheld(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`20260821112329` `09l--code` said untracked link sidecars were "not
    part of this implementation". The run-start baseline shows the path
    unchanged by this run, so the host upholds the deferral instead of
    forcing a commit or failing the turn."""

    prepare_dirty_declaration(monkeypatch, tmp_path)
    write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="belongs_to_another_turn",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"] == [
        {
            "instance_id": "commit",
            "repo_id": publication.context.obligations[0].obligation_id,
            "repo_display_name": "main",
            "reason": "belongs_to_another_turn",
            "paths": ["src/app.py"],
        }
    ]


def test_0by_1_cross_repo_scope_deferral_is_upheld(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`20260823154709` `0by--1` said committing a sibling repo "would
    violate the requested single...turn" scope. The run-start baseline shows
    the path unchanged by this run, so the host upholds the deferral."""

    prepare_dirty_declaration(monkeypatch, tmp_path)
    write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="foreign_work",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"] == [
        {
            "instance_id": "commit",
            "repo_id": publication.context.obligations[0].obligation_id,
            "repo_display_name": "main",
            "reason": "foreign_work",
            "paths": ["src/app.py"],
        }
    ]
