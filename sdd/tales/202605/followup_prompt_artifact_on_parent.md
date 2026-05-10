---
create_time: 2026-05-10 12:11:47
status: done
---
# Plan: Surface `followup_prompt-*.md` Artifact on Parent Agent Entry

## Problem

In the `sase ace` TUI's AGENT DETAILS panel, when feedback is sent to an agent, a `followup_prompt-<hash>.md` artifact
is generated and shown on the **child feedback step** (e.g. `@fs.2`) — but not on the **main/parent agent entry** (e.g.
`@fs.plan`).

The user wants the followup-prompt artifact to also appear in the ARTIFACTS list of the parent/workflow entry, so
feedback prompts can be located from the same place that other parent-level artifacts (plan paths, diff paths, dynamic
meta_\*) are aggregated.

## Root Cause (diagnosis)

When the user sends feedback to a running agent:

1. A new follow-up agent (e.g. `@fs.2`) is created with its own fresh artifacts directory under
   `~/.sase/artifacts/agents/<project>/<new_timestamp>/`.
   - `create_followup_artifacts()` in `src/sase/axe/run_agent_helpers.py` allocates the new timestamped dir and writes
     `agent_meta.json` with `parent_timestamp` pointing back to the original agent.
2. `state.current_artifacts_dir` is reassigned to the new child directory.
   - See `src/sase/axe/run_agent_exec_plan.py:228, 374, 452`.
3. `store_followup_prompt_artifact(artifacts_dir=..., prompt=..., label="Full feedback prompt")` in
   `src/sase/axe/run_agent_exec_plan_artifacts.py:30-49` writes `followup_prompt.md` and registers it in the
   explicit-artifact index — but only against the **child's** `agent_artifacts_dir`.

Then on the rendering side:

4. `_agent_artifact_paths()` in `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py:52-68` calls
   `list_agent_artifacts(agent.get_artifacts_dir())` and returns only the artifacts whose `agent_artifacts_dir` matches
   the selected agent's own directory.
5. Other parent metadata (`meta_*`, `code_time`, `epic_time`, `diff_path`) is propagated from follow-up agents up to the
   parent in `src/sase/ace/tui/models/_agent_status_overrides.py:161-188`. **Artifacts are not.** This is the missing
   aggregation.

So the followup-prompt artifact lives on the child only because:

- It's stored against the child's directory by design (the child is the one doing the follow-up work), and
- The parent's TUI artifact list never walks `agent.followup_agents` to collect feedback prompts.

## Desired Behavior

When the AGENT DETAILS panel renders for a parent agent that has follow-up agents (`agent.followup_agents` is
non-empty), the ARTIFACTS list should also include each follow-up agent's `followup_prompt-*.md` entry, displayed
alongside the parent's own artifacts.

Concretely, given the snapshot in the user's message — where `@fs.plan` is the parent and `@fs.2` is the feedback
follow-up — the parent's ARTIFACTS list should grow to include:

```
~/.sase/artifacts/agents/sase/20260510115740/followup_prompt-75f839ddaa4d.md
```

The child's ARTIFACTS view stays unchanged (it already shows this entry).

## Approach

UI-side aggregation in `_agent_artifact_paths()`. This is the most isolated, lowest-risk fix: storage stays the source
of truth (one canonical entry per artifact) and the TUI chooses which follow-up artifacts to surface on the parent.

### Why UI-side and not storage-side

- The artifact genuinely _belongs_ to the child run that produced it; double-registering it against the parent's dir
  would muddy the explicit-artifact index and confuse other consumers (e.g. file-panel listing).
- The TUI already does this kind of parent-aggregation pattern for `meta_*`, `code_time`, `epic_time`, and `diff_path`
  in `_agent_status_overrides.py` — extending the same pattern to artifacts is consistent.
- Aggregation at render time means we don't need to migrate or backfill any existing artifact records.

### Scope of what to aggregate

Only follow-up-prompt artifacts (basename matching `followup_prompt*.md`). Aggregating _all_ child artifacts would be
noisy on the parent (e.g. plan files, code diffs, screenshots that already have their own surfaces). The follow-up
prompt is the canonical "what feedback was sent" record and is the entry the user explicitly asked to see on the parent.

We can use either of these markers to identify the artifact (the implementation should prefer the more robust one):

- Basename pattern `followup_prompt*.md` — simple, works without re-reading the index.
- Explicit artifact `kind == "markdown"` with `label` starting with `"Full feedback"`, `"Full follow-up"`, or
  `"Full question"` — robust if the basename ever changes; requires reading the explicit-artifact index entries.

The basename pattern is simpler and matches the file the user is calling out. Implementation should default to the
basename check.

### Ordering & deduplication

- Parent's own artifacts render first; aggregated follow-up artifacts append after them in follow-up-agent chronological
  order (matches the existing `agent.followup_agents.sort(key=...)` in `_agent_status_overrides.py:252-254`).
- The existing `_dedupe_paths()` step in `_agent_artifacts.py:71-86` already deduplicates by resolved actual path, so
  re-listing the same artifact twice is safe.

### Behavior when the selected agent IS the child

No change — the child still shows its own artifacts including the follow-up prompt, exactly as today. The aggregation
only triggers when `agent.followup_agents` is non-empty, which is true for parents only (the loader populates
`followup_agents` exclusively on parents at `_agent_status_overrides.py:244-249`).

## Files to Change

1. `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
   - Extend `_agent_artifact_paths(agent)` so that, after collecting the agent's own artifacts, it walks
     `agent.followup_agents`, calls `list_agent_artifacts(...)` on each follow-up's artifacts dir, filters to entries
     whose basename matches `followup_prompt*.md`, and appends them to the display list before deduplication.
   - Tolerate failures per follow-up (one bad child shouldn't blank the parent's list — keep the existing broad
     `try/except` discipline).

That's the only production code change required. No data model changes, no storage changes, no migrations.

## Tests

Add a TUI-rendering test under `tests/` that mirrors the existing `_agent_artifacts.py` test layout:

- Build a parent `Agent` with one follow-up agent attached (`followup_agents=[child]`).
- Seed the child's artifacts dir with a `followup_prompt-<hash>.md` file (and the matching explicit-artifact-index row,
  if the test fixtures already set one up).
- Render and assert the parent's ARTIFACTS list contains the child's follow-up prompt path.
- Assert that other child artifacts (e.g. a synthetic `chat`/`pdf`/code-diff path) are NOT promoted to the parent.
- Keep an existing-style test for the child to confirm its own ARTIFACTS view is unchanged.

Run `just check` from the workspace before reporting completion (per `memory/short/build_and_run.md`).

## Out of Scope

- Storage model changes (no new index rows, no per-parent duplication of explicit artifacts).
- Aggregating non-followup-prompt artifacts (plan paths, diffs, images) onto the parent — separate UX decision, not
  requested.
- Changes to the file panel or the diff panel — only the AGENT DETAILS ARTIFACTS section is in scope.
- Backfilling historical artifact-index rows.
