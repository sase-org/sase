"""No-model controller refuses to run without an accepted declaration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.types import InvokeResult

from ._host_completion import sandbox_home as sandbox_home

__all__ = [
    "test_no_model_controller_refuses_missing_declaration",
]


def test_no_model_controller_refuses_missing_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.finalizers.controller import FinalizerControllerError, run_finalizers

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    entry = MagicMock()
    entry.instance_id = "commit"
    entry.provider_ref = "builtin@commit"
    entry.resolved_index = 0
    monkeypatch.setattr(
        "sase.finalizers.controller_run.authenticate_resolved_finalizer_plan_full",
        lambda *_a, **_k: MagicMock(
            plan=MagicMock(entries=(entry,), plan_digest="p" * 64),
            drift=(),
        ),
    )
    publication = MagicMock()
    publication.submission_required = True
    publication.payload = {"selected_instances": [{"instance_id": "commit"}]}
    monkeypatch.setattr(
        "sase.finalizers.declaration.publish_final_context",
        lambda **_k: publication,
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.final_submission_is_current",
        lambda **_k: False,
    )
    monkeypatch.setattr(
        "sase.finalizers._controller_shared.write_aggregate_result",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.finalizers.controller_run._project_drift_to_agent_meta",
        lambda *_a, **_k: None,
    )

    with pytest.raises(FinalizerControllerError, match="accepted declaration"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="done",
            invoke_result=InvokeResult(content=""),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
            mode="no_model",
        )
