---
create_time: 2026-05-30
status: research
---

# SASE Episode Lessons Worth Promoting To Long-Term Memory

## Question

Review the existing SASE project episodes and identify lessons that future agents could use. End with a recommendation
for which lessons should be promoted to `memory/long/`. This note intentionally does not edit memory files.

## Scope And Method

Episode store reviewed:

```text
~/.sase/projects/sase/episodes/
```

Commands used:

```bash
sase memory episodes list -p sase -j -o time
sase memory episodes show -p sase -f overview <episode-id>
sase memory episodes show -p sase -f timeline <episode-id>
sase memory episodes show -p sase -f sources <episode-id>
sase memory episodes verify -p sase --all
sase memory episodes status -p sase -j
sase memory episodes doctor -p sase -j
```

Existing long-term memories were read through audited `sase memory read` calls before making recommendations:

- `memory/long/generated_skills.md`
- `memory/long/tui_jk_baseline.md`

Neither existing long-term memory covers the episode lessons below.

## Inventory Reviewed

The project has 83 stored SASE episodes with 620 source refs, 64 agent records, and 112 chat refs. Importance scoring
classifies 77 episodes as `low` and 6 as `medium`; there are no `high` or `critical` episodes in this corpus.

The episode distribution is lopsided:

- 31 episodes are single-source chat fragments. Most preserve prompts or previous-conversation snippets, but are weak
  candidates for durable memory.
- 33 episodes are repeated low-signal scheduled chops such as recent bug audit, recent improvement audit, pylimit split,
  and refresh docs.
- 6 medium episodes contain plan/code/review evidence and useful implementation lessons.
- A low-scored research-swarm cluster is nevertheless important because it records the design decision around episodes,
  events, and memory promotion.

Verification found 68 clean episodes and 15 drifted episodes, with 123 missing source refs and 6 changed source refs.
That drift is itself useful: future agents should treat episodes as evidence indexes whose sources can disappear or
change, not as canonical truth.

## High-Value Lessons Found

### Episodes Are Evidence, Not Instructions

Evidence:

- `ep-a30208be496943b7433565c7`
- `ep-2862c442d2552878977ca172`
- `ep-35bff7da08cb157942314ffe`
- `ep-0684f61f824ee8dd765a86b6`
- `ep-627edd9d21712c23e490767d`
- `sdd/research/202605/sase_episodes_events_decision_consolidated.md`
- `sdd/research/202605/memory_episode_connected_components_and_events.md`

Reusable lesson:

Private episodes should remain deterministic, source-linked evidence records under project state. They should not
become always-loaded rules, direct writes to `memory/long`, or repo-committed lesson files. Curated `sdd/events/`
records can exist without episodes for push-model human/agent-authored lessons, but episodes are valuable for pull-model
backlog mining, dedupe, safety flags, provenance, and event-candidate review.

The trust boundary is important:

- raw chats and artifacts are source evidence;
- private episodes are generated evidence indexes;
- curated events are reviewed, repo-safe history;
- `memory/long` remains the very small reviewed semantic/procedural memory layer.

### Episode V2 Components Need Strong-Lineage Boundaries

Evidence:

- `ep-4073e6ba115b2988964c3fc5`
- `sdd/tales/202605/episodes_next_steps.md`
- `src/sase/memory/episodes/views.py`
- `src/sase/memory/episodes/_collector_record.py`

Reusable lesson:

For v2 episodes, date ranges select seeds, not boundaries. Membership should be based on strong lineage edges such as
retry, fork/resume, parent/child workflow, response chat, and workflow-step agent links. Weak topic edges such as
ChangeSpec, bead, same agent family, touched path, and generic file evidence should remain metadata and search signal,
not component-join criteria.

The May 29 fix captured three concrete gotchas:

- timeline grouping should prefer actor/conversation labels (`agent_run`, then `chat`, then `workflow_step`) over
  marker-file labels like `episode_trace.json`;
- strong graph mode should omit file/evidence edges such as `source`, `artifact`, `output`, `diff`, `plan`, `feedback`,
  `question`, and `memory_context`;
- related-timestamp expansion must skip the current artifact record to avoid retry self-loop edges.

### Notification Modal Tabs Are Top-Level Taxonomy

Evidence:

- `ep-dbf0db9652514f21e736506e`
- `ep-decdbb3262ba2afee38eda4a`
- `sdd/tales/202605/notification_tabs.md`
- `sdd/tales/202605/muted_notification_tab.md`
- `sdd/tales/202605/notification_bracket_footer.md`

Reusable lesson:

The ACE notification modal moved away from nested status sections. It should render flat, newest-first rows inside
top-level tabs. Synthetic tabs are product taxonomy, not stored notification tags:

- `HITL` for plan approvals, user questions, and HITL actions;
- `Errors` for notifications classified by `is_error`;
- `General`, `Done`, and other stored tag tabs;
- `Muted` as a quiet backlog tab.

Muted state has precedence over HITL, Errors, stored tags, and General. Mute/snooze can move a row out of the current
tab, so rebuild logic must preserve a sensible highlight and clear tab-scoped marks/confirmations only when the active
tab changes. The `[` and `]` tag-navigation bindings are modal-local `BINDINGS`, so footer discoverability does not
require default keymap config changes.

### Agent Root Status Must Reconcile Stale Notification Overrides

Evidence:

- `ep-c70b902cbab33f08deec31ee`
- `sdd/tales/202605/agent_root_running_status.md`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/actions/agents/_loading_compute_finalize.py`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py`

Reusable lesson:

Notification-derived status overrides are presentation hints, not stronger source of truth than the freshly loaded
agent tree. A stale `QUESTION` override should be cleared when loader/family aggregation shows the row has advanced to
an active non-question state such as `RUNNING`, `PLAN APPROVED`, `TALE APPROVED`, `EPIC APPROVED`, `LEGEND APPROVED`,
or `PLAN COMMITTED`.

Keep synchronous finalize and off-thread/precomputed finalize behavior aligned. Worker stale tokens must include status
override values, not only identities, because a same-row override value change should invalidate the old worker plan.

### Artifact Path Copying Should Use Explicit Workspace Metadata

Evidence:

- `ep-c2f1302a907fd2416145ffcb`
- `sdd/tales/202605/artifact_panel_relative_path.md`
- `src/sase/ace/tui/modals/agent_artifacts_modal.py`

Reusable lesson:

When copying or displaying artifact paths as repo-relative paths, use explicit workspace metadata from the artifact
record, `agent_meta.json`, or `done.json`. Do not infer the project root from the current working directory. For
persisted/global artifacts, try `source_path` after the stored artifact path because the stored path may live under
SASE's artifact store while the source path points into the workspace. Return POSIX-style repo-relative paths only when
the resolved path is inside the workspace; otherwise fall back to home-relative or absolute clipboard behavior.

### Scheduled Episode Building Is A Script Chop

Evidence:

- `ep-c1d2a252147001e9f0eeccd9`
- `sdd/tales/202605/memory_episodes_chop_1.md`

Reusable lesson:

The `memory_episodes` AXE task is a script chop, resolved from the `sase_chop_memory_episodes` entry point. A typical
opt-in config uses a `memory` lumberjack with `interval: 300`, `chop_timeout: "10m"`, and per-chop `run_every: "15m"`.
This is useful operational knowledge, but it is deployment-specific and weaker long-term-memory material than the
episode/event trust-boundary lessons.

## Lessons Not Worth Promoting

Do not promote the raw inventory itself. The exact episode IDs, counts, and drift state are useful in this research
file but will age quickly.

Do not promote repeated scheduled-chop episodes as separate memories. The recurring audit/pylimit/refresh-docs episodes
are useful evidence that auto-built episodes can be noisy, but they do not carry reusable project guidance beyond the
selection policy already captured above.

Do not promote standalone prompt fragments, previous-conversation fragments, or non-SASE Obsidian styling work into
SASE long memory.

Do not promote the Athena `memory_episodes` chop config as a default project rule unless the project wants
machine-specific AXE deployment details in long-term memory.

## Long-Term Memory Recommendations

Add these long-term memories:

1. `memory/long/episode_evidence_events.md`

   Capture the trust boundary: episodes are private source-linked evidence, curated `sdd/events/` records are reviewed
   repo-safe history, and `memory/long` remains the small reviewed semantic/procedural layer. Include the rule that
   episodes may feed proposals but must not auto-promote lessons or write `sdd/events/` directly.

2. `memory/long/episode_v2_component_gotchas.md`

   Capture the v2 component rules and hard-won implementation gotchas: date ranges select seeds only, strong lineage
   defines membership, weak topic/file evidence stays metadata, timeline grouping prefers actor labels over marker
   files, strong graph mode hides evidence edges, and retry related-record expansion must avoid self-loops.

3. `memory/long/notification_modal_tabs.md`

   Add if future notification-modal work is likely. Capture the current tab taxonomy, muted precedence, flat newest-first
   rows, highlight behavior after reclassification, and the modal-local nature of `[` / `]` bindings.

4. `memory/long/agent_status_override_reconciliation.md`

   Add if future Agents-tab status work is likely. Capture that fresh loader/family aggregation should clear stale
   `QUESTION` overrides when a root has advanced to an active status, and that sync/off-thread finalize paths must stay
   behaviorally identical.

Do not add the artifact path-copying or AXE `memory_episodes` chop lessons as separate long-term memories yet. They are
useful but narrower; keep them in this research note unless they recur in future episodes.
