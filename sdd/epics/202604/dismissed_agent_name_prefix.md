---
create_time: 2026-04-27 21:32:28
status: done
bead_id: sase-10
prompt: sdd/prompts/202604/dismissed_agent_name_prefix.md
---
# Enforce Names for Dismissed Agents

## Goal

Dismissed agents currently disappear from normal artifact scans and from the Agents TUI, so their agent names can be
reused or lost even though historical references such as `%wait:<name>` and `#resume:<name>` may still need to resolve.
We will make dismissal preserve a stable historical name by renaming every dismissed agent to:

```text
YYmmdd.<current-agent-name>
```

where `YYmmdd` is the agent completion date. When an agent is revived through the Agents tab `R` flow, the prefix is
stripped so the revived agent returns to its original live name.

The work should be split into separate implementation phases so distinct agent instances can complete each phase safely.

## Design Decisions

- Treat the dismissal rename as an agent-name rename, not as a display-only label. The prefixed name must be written
  into dismissed bundles, restored `agent_meta.json`, restored `done.json`, in-memory dismissed `Agent` objects, and any
  persisted dependency references that point at the old name.
- The completion date should be derived from the best available completion timestamp: `Agent.stop_time` first, then a
  readable completion timestamp from artifact metadata if present, then the agent's raw timestamp/start time as a final
  fallback. This keeps old bundles and partially populated records migratable.
- The prefix format is exactly six digits plus dot, matching `^\d{6}\.`. Prefixing must be idempotent: do not double
  prefix an already-prefixed dismissed name.
- Unprefixing on revive only strips this dismissal prefix. User names that coincidentally begin with a different prefix
  pattern should be handled conservatively by helpers with clear tests.
- Dismissed-name uniqueness is scoped to `(completion day, original/base name)`. If `260428.foo` already exists, the
  next dismissed agent originally named `foo` that completed on `2026-04-28` should get a deterministic suffix, for
  example `260428.foo.2`, then `260428.foo.3`.
- Reference rewrites should be structured-data rewrites where possible. JSON files should be parsed and re-emitted;
  prompt text rewrites should use the existing directive parsing/tokenization conventions rather than broad string
  replacement.
- This feature should use runtime-neutral helpers. Do not special-case Claude/Gemini/Codex.

## Phase 1: Agent Name Transformation Helpers

Owner: one agent instance.

Files likely owned by this phase:

- `src/sase/agent/names.py`
- new focused tests in `tests/test_agent_names.py` or a new `tests/test_dismissed_agent_names.py`

Deliverables:

1. Add a small public helper surface for dismissed-name lifecycle:
   - detect whether a name is dismissal-prefixed
   - add a `YYmmdd.` prefix idempotently
   - strip a dismissal prefix
   - allocate a collision-free dismissed name for a completion date
2. Define the collision source. The helper should scan existing dismissed bundles and any historical artifact metadata
   that can still contain prefixed names, not just visible active agents.
3. Preserve current active-name behavior: active auto-naming should continue ignoring dismissed agents, while explicit
   historical lookup can still find prefixed names once later phases restore metadata.
4. Unit tests should cover:
   - prefixing and stripping
   - idempotence
   - same-day collisions
   - different-day reuse
   - names that already contain dots, repeat suffixes, or workflow child suffixes

Exit criteria:

- Helper tests pass.
- Existing `tests/test_agent_names.py` behavior around `get_next_auto_name()`, `find_named_agent()`,
  `claim_agent_name()`, and repeat naming remains unchanged unless explicitly updated by later phases.

## Phase 2: Dismissal-Time Rename and Bundle Persistence

Owner: one agent instance.

Files likely owned by this phase:

- `src/sase/ace/tui/actions/agents/_dismissing.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/tui/models/agent_bundle.py` if serialization compatibility is needed
- `tests/test_agent_dismiss_in_memory.py`
- `tests/test_dismissed_agents.py`

Deliverables:

1. Before a DONE/FAILED agent is persisted as dismissed, compute its dismissed name and mutate the dismissal snapshot:
   - top-level agent `agent.agent_name`
   - workflow children/follow-up agents if they have agent names
   - same-session `_dismissed_agent_objects`
   - serialized dismissed bundle payloads
2. Agents without an existing name should receive one before prefixing. Prefer an existing stable naming helper so every
   dismissed agent has a name even if it never showed one in the TUI.
3. The optimistic in-memory path should display prefixed names in the revive modal immediately after dismissal.
4. Disk persistence should save bundles containing the prefixed name before deleting artifacts.
5. Batch dismissal should allocate names against the full batch plus existing dismissed history so two same-day agents
   do not collide.

Exit criteria:

- Dismissing a single agent with `foo` creates a dismissed bundle with `260428.foo` when completed on April 28, 2026.
- Dismissing two same-day agents named `foo` creates unique prefixed names.
- Dismissing an unnamed agent creates a non-empty prefixed name.
- Existing fast-dismiss behavior stays optimistic and does not reintroduce full synchronous reloads.

## Phase 3: Reference Rewrites for Wait and Resume

Owner: one agent instance.

Files likely owned by this phase:

- `src/sase/ace/tui/actions/agents/_dismissing.py`
- `src/sase/scripts/sase_chop_wait_checks.py`
- `src/sase/history/chat.py`
- `src/sase/xprompt/directives.py` only if a reusable prompt rewrite helper belongs there
- focused tests in `tests/test_agent_dismiss_in_memory.py`, `tests/history/test_chat.py`,
  `tests/test_directives_types.py`, or a new test file

Deliverables:

1. Add a reference rewrite operation that maps `old_name -> dismissed_name` when dismissal renames an agent.
2. Update structured wait references:
   - `agent_meta.json` `wait_for`
   - `waiting.json` `waiting_for`
   - `ready.json` `resolved_deps` where present
   - in-memory `Agent.waiting_for` for loaded agents
3. Update prompt references that directly name the agent:
   - `%wait:<name>` and `%w:<name>`
   - comma-separated wait lists
   - paren/backtick wait forms where safe
   - `#resume:<name>`, `#resume(<name>)`, and backtick resume forms
4. Avoid rewriting unrelated plain prose or disabled/fenced content unless it is a recognized directive reference.
5. Decide and document whether old aliases remain accepted temporarily. The preferred end state is canonical rewrites to
   the prefixed name, with tests proving `wait_checks` and `#resume` resolve the new name.

Exit criteria:

- A waiting agent that used `%w:foo` continues waiting on the dismissed agent after `foo` becomes `260428.foo`.
- A prompt or chat containing `#resume:foo` is rewritten or otherwise resolves as `#resume:260428.foo`.
- Multiple wait dependencies update only the matching dependency.
- Non-matching names such as `foobar` are not touched.

## Phase 4: Revive Unprefixing and Artifact Restoration

Owner: one agent instance.

Files likely owned by this phase:

- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py` if display needs polishing
- `tests/test_agent_revive.py`

Deliverables:

1. When `_do_revive_agent()` or `_do_revive_agents()` restores an agent, strip the `YYmmdd.` dismissal prefix from:
   - the revived parent agent
   - child/follow-up agents restored with it
   - restored `done.json`
   - restored `agent_meta.json`
   - restored workflow state or step markers when they carry name-like fields
2. Reclaim the live unprefixed name with existing name-claim logic so revived agents behave like active agents again.
3. Update any wait/resume references that were rewritten to the dismissed prefixed name back to the live unprefixed name
   when they belong to restored, active agents.
4. Ensure bundle removal still uses identity/raw suffix, not name, so changing the name does not strand bundles.

Exit criteria:

- A dismissed `260428.foo` revived through `R` appears as `foo`.
- Revived artifacts contain `foo`, not `260428.foo`.
- Children/follow-up agents are restored consistently.
- Reviving a batch with multiple same-day collisions strips only the date prefix and preserves any collision suffix that
  belongs to the actual base name.

## Phase 5: Lookup, Migration, and UI Polish

Owner: one agent instance.

Files likely owned by this phase:

- `src/sase/agent/names.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py`
- relevant lookup and modal tests

Deliverables:

1. Make historical lookup reliable for dismissed agents:
   - `find_named_agent("YYmmdd.foo")` should work after dismissal if enough metadata exists
   - `get_most_recent_agent_name()` should not accidentally return prefixed dismissed names for bare `%wait`
2. Add a best-effort migration/repair path for old dismissed bundles with missing `agent_name`.
   - Loading old bundles should synthesize a prefixed name without requiring users to revive and redismiss them.
3. Ensure revive and run-log modals show the prefixed dismissed name clearly while preserving existing filtering by
   `name:<value>`.
4. Update copy-name behavior if needed so dismissed entries copied from run log/revive surfaces use the canonical
   prefixed name.

Exit criteria:

- Existing dismissed bundles with no name become name-bearing after load/save or at dismissal-management time.
- Bare `%wait` still selects the most recent active/visible named agent, not an old dismissed historical name.
- Direct `#resume:YYmmdd.foo` and `%w:YYmmdd.foo` can resolve historical dismissed agents.

## Phase 6: End-to-End Tests and Regression Pass

Owner: one agent instance.

Files likely owned by this phase:

- New integration-style tests near existing agent lifecycle tests
- Any small fixes uncovered by those tests

Deliverables:

1. Add an end-to-end test that exercises:
   - agent completes with name `foo`
   - another agent waits/resumes using `foo`
   - dismiss renames to `YYmmdd.foo`
   - references update to `YYmmdd.foo`
   - revive strips back to `foo`
2. Add a workflow-parent test with children/follow-up agents to ensure parent and children names/references stay
   consistent.
3. Add a collision test with two same-day completions using the same live name.
4. Run targeted tests for all touched areas, then run the repo check command:

```bash
just install
just check
```

Exit criteria:

- All targeted tests pass.
- `just check` passes.
- Any intentionally deferred behavior is documented in this plan or follow-up beads.

## Coordination Notes

- Phases 1 and 2 should land before any broad reference rewrite work. Reference rewriting needs a single canonical
  mapping helper from Phase 1 and real dismissal integration from Phase 2.
- Phases 3 and 4 both need rewrite helpers. If Phase 3 creates generic reference-rewrite utilities, Phase 4 should reuse
  them for the reverse mapping.
- Avoid changing the dismissed identity tuple shape. Existing dismissal hiding and bundle deletion are suffix/identity
  based and should stay compatible.
- Preserve current performance assumptions: dismissal should remain optimistic and asynchronous, and bundle loading
  should avoid scanning more than needed on the TUI hot path.
- Every phase should include its own targeted tests so later agents can trust the previous phase boundary.
