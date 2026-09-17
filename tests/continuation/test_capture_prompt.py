"""Continuation prompt and agent-delta capture tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import LoopState
from sase.continuation_capture import (
    ContinuationSegmentCapture,
    _persist_agent_delta,
    _record_prepared_prompt_capture,
    record_prepared_prompt_capture_best_effort,
)
from sase.continuation_capture.rollout import MONITOR_CONTINUATION_CAPTURE_ENV
from sase.feature_flags import override_flags
from sase.llm_provider.preprocessing import preprocess_prompt_early
from sase.xprompt.models import XPrompt

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._continuation_capture_helpers import (
    HOSTILE_PROMPT,
    blob_text,
    json_record,
)


def test_prepared_prompt_capture_publishes_blobs_without_delimiter_recovery(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    materialized = HOSTILE_PROMPT + "\nMaterialized tail."

    result = _record_prepared_prompt_capture(
        artifacts,
        authored_local_request=HOSTILE_PROMPT,
        materialized_prompt=materialized,
        segments=(
            ContinuationSegmentCapture(
                text="expanded helper\n## Response stays data",
                provenance="local_materialized",
                source_ref="xprompt:helper:test",
                source_label="helper.md",
            ),
        ),
        update_meta=False,
    )

    payload = json_record(Path(result.prepared_path))
    assert payload["authored_local_request"] == HOSTILE_PROMPT
    assert payload["materialized_prompt_ref"].startswith("local:continuation/text/")
    segments = payload["materialized_local_prompt_segments"]
    assert isinstance(segments, list)
    assert [segment["provenance"] for segment in segments] == [
        "local_authored",
        "local_materialized",
    ]
    assert not any(
        segment["provenance"] == "local_materialized"
        and blob_text(artifacts, segment["text_ref"]) == materialized
        for segment in segments
    )
    for segment in segments:
        ref = segment["text_ref"]
        assert isinstance(ref, str)
        blob = artifacts / "continuation" / ref.removeprefix("local:continuation/")
        assert blob.exists()


def test_prepared_prompt_capture_uses_monitor_continuation_env_when_flag_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    with override_flags(monitor_continuation_records=False):
        assert (
            record_prepared_prompt_capture_best_effort(
                artifacts,
                authored_local_request="hello",
                materialized_prompt="hello",
            )
            is None
        )
        monkeypatch.setenv(MONITOR_CONTINUATION_CAPTURE_ENV, "1")
        result = record_prepared_prompt_capture_best_effort(
            artifacts,
            authored_local_request="hello",
            materialized_prompt="hello materialized",
        )

    assert result is not None
    assert Path(result.prepared_path).exists()


def test_agent_delta_capture_uses_wire_validators_and_exact_authored_text(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt=HOSTILE_PROMPT,
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=HOSTILE_PROMPT,
    )
    _record_prepared_prompt_capture(
        ctx.artifacts_dir,
        authored_local_request=HOSTILE_PROMPT,
        materialized_prompt=HOSTILE_PROMPT + "\nmaterialized",
    )

    with (
        patch("sase.core.continuation_facade.validate_agent_delta") as validate_delta,
        patch(
            "sase.core.continuation_facade.validate_continuation_node"
        ) as validate_node,
    ):
        result = _persist_agent_delta(
            ctx,
            state,
            status="completed",
            final_response="done\n## Prompt is response data",
        )

    validate_delta.assert_called_once()
    validate_node.assert_called_once()
    manifest = json_record(Path(result.manifest_path))
    delta_ref = manifest["agent_delta_ref"]
    assert isinstance(delta_ref, str)
    delta_path = (
        Path(ctx.artifacts_dir)
        / "continuation"
        / delta_ref.removeprefix("local:continuation/")
    )
    delta = json_record(delta_path)
    assert delta["authored_local_request"] == HOSTILE_PROMPT
    assert delta["status"] == "completed"
    assert delta["final_response_ref"]


def test_preprocess_prompt_early_captures_xprompt_expansion_provenance() -> None:
    result = preprocess_prompt_early(
        "Before #local after",
        extra_xprompts={
            "local": XPrompt(
                name="local",
                content="expanded body",
                source_path="/tmp/local.md",
            )
        },
    )
    captured = [
        segment
        for segment in result.continuation_segments
        if segment.source_ref and segment.source_ref.startswith("xprompt:local:")
    ]
    assert len(captured) == 1
    assert captured[0].text == "expanded body"


def test_complete_prompt_segments_excludes_injected_ancestry_dump() -> None:
    from sase.continuation_capture import complete_prompt_segments

    segments = complete_prompt_segments(
        authored_local_request="Continue",
        materialized_prompt="INJECTED_ANCESTOR_SENTINEL\nContinue",
        segments=(),
    )

    asserted = [
        (segment.provenance, "INJECTED_ANCESTOR_SENTINEL" in segment.text)
        for segment in segments
    ]
    assert asserted == [("local_authored", False)]


def test_repeated_handoff_does_not_store_inherited_prompt_as_local(
    tmp_path: Path,
) -> None:
    from sase.continuation_capture import (
        complete_prompt_segments,
        local_authored_prompt_segment,
    )

    inherited = "INJECTED_ANCESTOR_SENTINEL\n# New Query\nContinue"
    segments = complete_prompt_segments(
        authored_local_request="Continue",
        materialized_prompt=inherited + "\nlocal helper",
        segments=(
            local_authored_prompt_segment("Continue"),
            ContinuationSegmentCapture(
                text=inherited,
                provenance="injected_parent",
                source_ref="local:injected-parent",
                source_label="fork.yml",
            ),
        ),
    )
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    result = _record_prepared_prompt_capture(
        artifacts,
        authored_local_request="Continue",
        materialized_prompt=inherited + "\nlocal helper",
        segments=segments,
        update_meta=False,
    )
    payload = json_record(Path(result.prepared_path))
    provenances = [
        segment["provenance"]
        for segment in payload["materialized_local_prompt_segments"]
    ]
    assert "injected_parent" in provenances
    assert provenances.count("local_authored") == 1
    state = LoopState(
        current_prompt=inherited + "\nlocal helper",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Continue",
    )
    with (
        patch("sase.core.continuation_facade.validate_agent_delta"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        published = _persist_agent_delta(
            ctx, state, status="completed", final_response="ok"
        )
    delta = json_record(
        Path(ctx.artifacts_dir)
        / "continuation"
        / published.agent_delta_ref.removeprefix("local:continuation/")
    )
    delta_provenances = [
        segment["provenance"]
        for segment in delta.get("materialized_local_prompt_segments", [])
    ]
    assert "injected_parent" not in delta_provenances
    assert all(
        "INJECTED_ANCESTOR_SENTINEL" not in blob_text(artifacts, segment["text_ref"])
        for segment in delta.get("materialized_local_prompt_segments", [])
        if segment["provenance"] == "local_materialized"
    )


def test_fork_workflow_segment_is_injected_parent() -> None:
    from sase.continuation_capture import embedded_workflow_prompt_segment

    segment = embedded_workflow_prompt_segment(
        "fork",
        "INJECTED_ANCESTOR_SENTINEL",
        source_path="/tmp/fork.yml",
    )
    assert segment.provenance == "injected_parent"
    local = embedded_workflow_prompt_segment(
        "commit",
        "commit instructions",
        source_path="/tmp/commit.yml",
    )
    assert local.provenance == "local_materialized"
