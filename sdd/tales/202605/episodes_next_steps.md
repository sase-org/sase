---
create_time: 2026-05-29 09:20:37
status: done
prompt: sdd/prompts/202605/episodes_next_steps.md
---
# Episode Visualization Next Steps Plan

## Objective

Implement the previous agent's recommended next step for `sase memory episodes`: fix misleading timeline grouping,
reduce default graph noise by classifying evidence/file edges as weak, prevent retry lineage self-loop graph edges, and
add a regression fixture that exercises the retry-shaped case end to end.

## Scope

This plan targets the three bugs explicitly called out as the best next step:

- Timeline events should group under the most useful run/chat label, not under incidental marker files such as
  `episode_trace.json`.
- Strong graph mode should show connected-component/lineage structure, while file/evidence edges such as `source`,
  `artifact`, `output`, and `diff` should move to weak/all mode.
- Retry-related timestamp expansion should not produce self-loop edges when the timestamp resolves back to the same
  artifact record.

This plan intentionally leaves the remaining recommendations out of scope unless they are needed to support the above
fixes:

- Component key readability and absolute-path leakage.
- Aggregate top-level fields in `verify --json`.

## Current Design Notes

- Timeline grouping is currently computed in `src/sase/memory/episodes/views.py` by mapping each `source_id` to one
  node. Because file nodes and agent nodes can share source IDs, later file nodes can overwrite the agent node, causing
  groups such as `episode_trace.json`.
- Strong graph classification is currently `edge.kind not in _WEAK_EDGE_KINDS`. The weak set includes metadata edges,
  but not evidence/file edges produced by the collector.
- `_queue_related_records` in `src/sase/memory/episodes/_collector_record.py` queues records by related timestamps
  without skipping the current record. Because `_queue_record` returns true for an already-included current record, this
  can add a self-loop edge.

## Implementation Approach

1. Update timeline grouping in `views.py`.
   - Prefer node kinds that represent the episode actor or conversation (`agent_run`, then `chat`, then `workflow_step`,
     then other nodes).
   - Avoid letting generic file/source nodes override a better label for the same source ID.
   - Keep ordering deterministic across nodes and evidence IDs.

2. Update graph edge strength in `views.py`.
   - Add evidence/file-only edge kinds to `_WEAK_EDGE_KINDS`, including at least `source`, `artifact`, `output`, `diff`,
     `plan`, `feedback`, `question`, and `memory_context`.
   - Keep structural edges strong, including `response_chat`, `workflow_step_chat`, `workflow_step_agent`,
     `parent_agent`, retry lineage, fork/link chat edges, and turn containment if it is needed for drill-down structure.
   - Preserve `edge_mode="all"` behavior so users can still inspect the full evidence graph.

3. Prevent self-loop related-record edges in `_collector_record.py`.
   - Compare normalized artifact keys before queueing a related timestamp result.
   - Skip same-record related timestamp matches even if the timestamp appears in retry root or parent metadata.
   - Leave cross-record same-timestamp behavior intact for distinct artifact directories.

4. Add focused regression coverage.
   - Unit-level renderer tests for timeline group priority and graph edge strength.
   - Collector/component test coverage for a retry-root timestamp equal to the current record timestamp, asserting no
     self-loop edge is emitted.
   - Strengthen the existing E2E retry fixture assertion so the timeline groups retry/question events under agent labels
     rather than marker filenames and strong graph mode omits evidence/file edges.

## Verification

Run targeted episode tests first:

```bash
just install
just test tests/test_memory_episodes_builder_renderer.py tests/test_memory_episodes_components.py tests/test_memory_episodes_e2e.py tests/test_memory_episodes_cli_show.py
```

Then run the required repository check because this plan changes code:

```bash
just check
```

If `just check` fails outside the touched episode paths, inspect enough to distinguish a real regression from
pre-existing workspace/environment issues and report that clearly.
