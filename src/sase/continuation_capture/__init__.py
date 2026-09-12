"""Local persistence for continuation capture records.

The Rust continuation contract owns the wire shapes and validation. This
package is only the artifacts-side persistence adapter: it records local prompt
provenance, workspace facts, checkpoints, and agent-delta nodes without trying
to interpret replay policy.
"""

from __future__ import annotations

from ._constants import (
    CAPTURE_ERRORS_FILENAME,
    CONTINUATION_DIRNAME,
    MANIFEST_FILENAME,
    PREPARED_PROMPT_FILENAME,
    WORKSPACE_FACTS_FILENAME,
)
from ._storage import record_capture_error
from .agent_delta import (
    persist_agent_delta as _persist_agent_delta,
    persist_agent_delta,
    persist_agent_delta_best_effort,
    read_latest_manifest_projection,
)
from .checkpoints import (
    publish_handoff_checkpoint,
    publish_handoff_checkpoint_best_effort,
)
from .models import (
    ContinuationPublishResult,
    ContinuationSegmentCapture,
    MonitorResultPublishResult,
    PreparedPromptCaptureResult,
)
from .monitor import (
    persist_monitor_result,
    persist_monitor_result_best_effort,
    persist_monitor_start_intent,
    persist_monitor_start_intent_best_effort,
)
from .prompt import (
    read_prepared_prompt_capture_ref,
    record_prepared_prompt_capture as _record_prepared_prompt_capture,
    record_prepared_prompt_capture,
    record_prepared_prompt_capture_best_effort,
)
from .segments import (
    embedded_workflow_prompt_segment,
    local_authored_prompt_segment,
    local_materialized_prompt_segment,
    xprompt_trace_segments,
)
from .workspace import persist_workspace_facts, persist_workspace_facts_best_effort

__all__ = [
    "ContinuationPublishResult",
    "ContinuationSegmentCapture",
    "MonitorResultPublishResult",
    "PreparedPromptCaptureResult",
    "_persist_agent_delta",
    "_record_prepared_prompt_capture",
    "embedded_workflow_prompt_segment",
    "local_authored_prompt_segment",
    "local_materialized_prompt_segment",
    "persist_agent_delta",
    "persist_agent_delta_best_effort",
    "persist_monitor_start_intent",
    "persist_monitor_start_intent_best_effort",
    "persist_monitor_result",
    "persist_monitor_result_best_effort",
    "persist_workspace_facts",
    "persist_workspace_facts_best_effort",
    "publish_handoff_checkpoint",
    "publish_handoff_checkpoint_best_effort",
    "read_latest_manifest_projection",
    "read_prepared_prompt_capture_ref",
    "record_capture_error",
    "record_prepared_prompt_capture",
    "record_prepared_prompt_capture_best_effort",
    "xprompt_trace_segments",
]
