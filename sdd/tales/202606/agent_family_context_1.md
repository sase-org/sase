---
create_time: 2026-06-14 13:10:41
status: done
prompt: sdd/prompts/202606/agent_family_context_1.md
---
# Plan: Agent-family context in the ACE metadata panel

## Problem

The `sase ace` Agents tab metadata panel already has an `AGENT CONTEXT` section with `MEMORY` and `SKILLS` lanes, but
the data loaded for that section is scoped to the selected `Agent` only:

- `build_detail_header_summary()` calls `load_memory_reads_for_agent(agent)` and `load_skill_uses_for_agent(agent)`.
- Those loaders filter audit logs by one artifact directory, falling back to one agent name only when the event has no
  artifact directory.
- Agent-family root rows already consolidate replies from `followup_agents`, but their metadata context does not
  consolidate memory reads or logged skill uses from follow-up family members such as planner feedback, `q`, `coder`,
  `epic`, or `commit`.
- Even if the data were aggregated, the current row renderer would not show which family member produced each event.

The result is misleading: the root/family row can look like only the first/planner agent read memory or used skills,
while later phases did additional audited context work that is invisible.

## Design goals

1. **Family-wide when the UI is family-wide**: when the selected row has `followup_agents`, show audited context from
   the selected row plus its follow-up family members. For ordinary rows with no follow-ups, preserve the current
   per-agent behavior.
2. **Explicit attribution**: each aggregated row should show a compact role label such as `plan`, `q`, `coder`, `fb2`,
   `epic`, `legend`, or `commit`. Unknown/custom rows fall back to a concise `@agent_name` or display label.
3. **No fragile name-only family scans**: use the in-memory relationships already computed by the loader
   (`followup_agents`, family metadata, role suffixes, artifact dirs) rather than trying to infer all family members
   from dotted names at render time.
4. **Reliable log matching**: keep the existing artifact-dir-first matching semantics. Fall back to agent-name matching
   only for log events with no artifact directory. Deduplicate by event id so synthetic planner rows sharing the root
   artifact directory do not double-render the same event.
5. **TUI performance discipline**: read each audit log at most once per family summary build, cache by project, member
   identities, log mtime, and throttle timestamp, and keep the cheap immediate header path disk-free.
6. **Clean visual hierarchy**: keep the existing `MEMORY` and `SKILLS` lanes, colors, row caps, and reason wrapping. Add
   a narrow responsibility column between timestamp and glyph only for attributed/family events, and include `N agents`
   in lane summaries when multiple producers appear.

## Implementation outline

### 1. Add shared TUI context attribution helpers

Create a small helper module near the existing TUI context loaders, for example
`src/sase/ace/tui/agent_context_members.py`.

Responsibilities:

- Build an ordered, deduplicated context-member list from a selected agent:
  - primary selected agent first
  - then `agent.followup_agents`
  - dedupe by stable agent identity / artifact dir / agent name
- Normalize artifact dirs with the same realpath behavior the loaders already use.
- Produce compact role labels:
  - `--plan` / `.plan` / root plan rows -> `plan`
  - `--q` / `.q` -> `q`
  - `--code` / `.code` -> `coder`
  - feedback suffixes -> `fbN`
  - `--epic`, `--legend`, `--commit` -> their literal labels
  - otherwise `agent_family_role`, `@agent_name`, step name, or display name, truncated by the renderer
- Match audit events against members:
  - artifact dir match wins when event has `artifacts_dir`
  - name fallback only when event lacks `artifacts_dir`
  - return the matched label for display

This stays in Python/TUI code because it is display attribution over already-loaded TUI relationships, not shared
backend behavior.

### 2. Add attributed context event wrappers

Keep the existing public per-agent loaders intact for callers/tests that need raw log events.

Add display-oriented wrappers:

- `MemoryReadDisplayEvent(event: MemoryReadEvent, agent_label: str | None)`
- `SkillUseDisplayEvent(event: SkillUseEvent, agent_label: str | None)`

Add new loader entry points:

- `load_memory_reads_for_agent_context(agent, limit=MAX_KEPT_READS)`
- `load_skill_uses_for_agent_context(agent, limit=MAX_KEPT_SKILL_USES)`

Behavior:

- For a single-member context, return wrappers around the same events as today, with `agent_label=None` so the existing
  visual shape is preserved for normal rows.
- For a multi-member context, read the log once, match all members, dedupe by event id, sort newest first, cap to
  existing limits, and include member labels.
- Cache multi-member results with a key that includes project, ordered member cache keys, log mtime, and throttle
  timestamp. This avoids multiplying log reads as family size grows.

### 3. Feed family context into the metadata summary

Update `build_detail_header_summary()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` to call the
new display-context loaders.

The cheap header path remains unchanged and still does no audit-log work. The hint and zoom paths already consume
`build_detail_header_summary()`, so they pick up the same family context automatically.

### 4. Render responsibility labels beautifully

Update the existing lane renderers rather than adding a third section:

- Teach `_agent_context_common.append_lane_row()` to accept `agent_label: str | None`.
- When any visible event in a lane has a label, reserve a compact fixed-width role column after the timestamp:
  - Example memory row: `14:22:08  coder  ◇ long/tui_perf.md`
  - Example skill row: `14:23:10  q      ◆ sase_questions`
- Keep reason wrapping aligned under the primary path/skill text.
- In each lane summary, add producer count only when labels are present:
  - `▸ MEMORY · 4 reads · 3 files · 2 agents`
  - `▸ SKILLS · 3 uses · 2 skills · 2 agents`
- Preserve the existing empty-state behavior (`none recorded`) for one lane when the other has data.

This makes attribution visible without turning the metadata panel into a table or overwhelming single-agent rows.

### 5. Tests

Add focused regression coverage:

- `tests/ace/tui/test_memory_reads_loader.py`
  - family context includes root + coder/q/follow-up events
  - labels are correct
  - artifact-dir mismatches still do not fall back to agent name
  - duplicate root/synthetic-planner artifact events render once
  - results are newest-first and capped
- `tests/ace/tui/test_skill_uses_loader.py`
  - same family aggregation and attribution cases for skill-use logs
- `tests/ace/tui/widgets/test_agent_memory_reads.py` and `test_agent_skill_uses.py`
  - attributed rows show role labels
  - summaries include `N agents`
  - reason wrapping alignment still holds
- `tests/ace/tui/widgets/test_prompt_panel_header.py`
  - a family root header renders memory/skill events from a coder or `q` follow-up and shows the producing role.

Existing single-agent tests should continue to pass with no role column unless they explicitly exercise attributed
events.

### 6. Verification

After implementation:

1. Run the focused tests:
   - `uv run pytest tests/ace/tui/test_memory_reads_loader.py tests/ace/tui/test_skill_uses_loader.py tests/ace/tui/widgets/test_agent_memory_reads.py tests/ace/tui/widgets/test_agent_skill_uses.py tests/ace/tui/widgets/test_prompt_panel_header.py`
2. Because source files will be changed in this repo, run the required repo check:
   - `just install`
   - `just check`
3. If any visual snapshot changes unexpectedly, inspect the generated PNG diff artifacts. The intended design avoids
   changing existing single-agent snapshots unless a test fixture is updated to use attributed family events.

## Out of scope

- Changing the audit log schema for memory reads or skill uses.
- Adding new `sase ace` keymaps, options, or help-modal text.
- Scanning arbitrary agents by shared name prefix at render time.
- Moving the audit-log reader into Rust core; this feature is presentation attribution over TUI agent-family
  relationships.
