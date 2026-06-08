---
create_time: 2026-06-08 07:43:13
status: done
prompt: sdd/prompts/202606/cross_project_timestamp_dedup_collision.md
---
# Fix: running coder shows `TALE DONE` due to cross-project artifact-timestamp dedup collision

## Symptom

In the `sase ace` Agents tab, the TALE coder follow-up step `3p.f1.f1--code` shows status **`TALE DONE`** even though
its process is still alive and actively implementing (running-man glyph `🏃‍♂️ 2m43s`, live reply stream updating). It
should show **`TALE APPROVED`** for the whole window between plan approval and coder completion. Because the family root
mirrors its newest child, the `3p.f1.f1` root row inherits the wrong `TALE DONE` too.

## Root cause (confirmed against live artifacts + reproduced through the real loader)

The affected coder is `bob-cli`'s `3p.f1.f1--code` in artifact dir
`~/.sase/projects/bob-cli/artifacts/ace-run/20260608070834` (pid 36341). At the moment of the bug it was genuinely
running: its `workflow_state.json` was `status: "running"` with the `main` step `in_progress`, and there was no
`done.json`. Loaded in isolation it correctly resolves to `RUNNING` → `TALE APPROVED` (the parent root carries
`plan_action: "tale"`, so `_active_approved_plan_handoff_status` fires).

The real problem is a **timestamp-directory-name collision across two unrelated projects**:

- `~/.sase/projects/bob-cli/artifacts/ace-run/20260608070834` — the running coder (`bob-cli`, pid 36341).
- `~/.sase/projects/sase/artifacts/ace-run/20260608070834` — an unrelated, already-**completed** `sase_fix_just-108`
  workflow (`sase`, pid 62940).

Both launched in the same clock second, so both artifact directories are named `20260608070834`. Agents are keyed
throughout the loader by `raw_suffix = <timestamp dir name>`, which is **only unique within a single project's artifact
tree, not globally**.

`dedup_workflow_entries` (`src/sase/ace/tui/models/_dedup.py:202`) deduplicates `WORKFLOW` agents by `raw_suffix`
**alone**, with no project/artifact-path scoping:

```python
seen_suffixes: dict[str, Agent] = {}
for agent in agents:
    if agent.agent_type == AgentType.WORKFLOW and agent.raw_suffix:
        if agent.raw_suffix in seen_suffixes:
            existing = seen_suffixes[agent.raw_suffix]
            ...
            # Prefer non-RUNNING status from workflow_state.json (accurate status)
            if existing.status == "RUNNING" and agent.status != "RUNNING":
                existing.status = agent.status   # <-- running coder inherits DONE
            ...
        else:
            seen_suffixes[agent.raw_suffix] = agent
```

When the running `bob-cli` coder is seen first (`existing`, status `RUNNING`) and the completed `sase` workflow second
(`agent`, status `DONE`), this overwrites the coder's status with `DONE` (and merges other metadata such as
pid/cl_name), then drops one of the two entries. The override layer then maps the now-`DONE` coder through
`_is_completed_plan_handoff_child` → `_done_handoff_status` → **`TALE DONE`**, and the family root mirrors it. The
running-man glyph and ticking timer remain because `agent_time.py` derives liveness from `run_start_time`/pid, **not**
from status — which is exactly why the row looks "alive but DONE".

This was verified by running the production pipeline (`load_all_agents` / `_load_agents_from_all_sources` → dedup chain
→ `_apply_status_overrides`) against the live filesystem and by a standalone reconstruction:

- **With** the cross-project collision present: coder → `TALE DONE`, root → `TALE DONE` (bug reproduced).
- **Without** it (or with both entries kept separate): coder → `TALE APPROVED`, root → `TALE APPROVED` (correct), and
  the unrelated `sase` agent stays `DONE`.

`dedup_running_vs_workflow` (`_dedup.py:247`) has the **identical** vulnerability: it builds `workflow_by_suffix` keyed
by bare `raw_suffix` and merges a `RUNNING` ace-run agent into a `WORKFLOW` agent on a raw-timestamp match, so a running
ace-run agent in project A can be conflated with a workflow agent in project B that happens to share the same launch
second.

## Fix

Make the timestamp-based dedup keys **project-scoped** so two agents are only ever treated as duplicates when they
belong to the same project's artifact tree. `project_file` is set uniformly on every agent source (running-field,
running-home, workflow, and workflow-snapshot loaders), so a composite key of `(project_file, raw_suffix)` is both
available everywhere and sufficient to disambiguate the artifact directory (which is
`<project>/artifacts/<workflow-dir>/<raw_suffix>`).

File: `src/sase/ace/tui/models/_dedup.py`

1. **`dedup_workflow_entries`** (primary fix): replace the `seen_suffixes` dict keyed by `agent.raw_suffix` with a dict
   keyed by `(agent.project_file, agent.raw_suffix)`. Update the duplicate lookup, the merge branch, and the final
   filter (which references `seen_suffixes` / `seen_suffixes.get(a.raw_suffix)`) to use the same composite key. Behavior
   within a single project is unchanged; cross-project same-timestamp agents are no longer merged.

2. **`dedup_running_vs_workflow`** (same-class fix, defense in depth + correctness): scope `workflow_by_suffix` and its
   lookup by `(agent.project_file, agent.raw_suffix)` so a `RUNNING` ace-run agent only merges into a `WORKFLOW` agent
   from the same project.
   - Confirm during implementation that the `RUNNING` (running-field / running-home) entry and the matching `WORKFLOW`
     (workflow*state) entry for the _same real agent* resolve to the same `project_file` (both derive from the same
     project dir via `preferred_project_spec_path`; home ace-run agents live under the `home` project tree on both
     sides). The existing tests `test_dedup_running_vs_workflow_merges_plain_run` / `..._no_match_without_suffix` in
     `tests/test_run_workflow_visibility.py` must continue to pass — set `project_file` consistently on those fixtures
     if needed.

### Why this is safe / does not over-trigger

- A genuine duplicate (same artifact dir loaded from two sources) always shares the same project, so it still
  dedupes/merges exactly as before.
- The status-preference and metadata-copy logic is unchanged; only the matching key is narrowed, so unrelated
  cross-project agents are never compared and can no longer cross-contaminate status/pid/cl_name.
- `dedup_by_pid` already keeps two distinct-`raw_suffix` workflow agents that share a pid (the coder and its sibling
  `sase` agent have different pids anyway), so the two entries both survive to the override pass, where each resolves on
  its own merits (coder → `TALE APPROVED`, `sase` agent → `DONE`). This was verified end-to-end.
- Idempotent: re-running the dedup chain with project-scoped keys is stable.

## Scope / non-scope

- **In scope:** `src/sase/ace/tui/models/_dedup.py` (`dedup_workflow_entries`, `dedup_running_vs_workflow`) and targeted
  tests.
- **Noted related risk (out of scope for this fix):** `apply_status_overrides` also keys family resolution by bare
  `raw_suffix` (`parent_by_suffix`, the retry-chain `by_suffix`, and `_is_family_child`'s
  `parent_timestamp == parent.raw_suffix`). A cross-project collision on a _parent/root_ timestamp could similarly
  mis-associate a child with the wrong project's parent. The reported symptom is fully resolved by the dedup fix
  (verified: the override produces the correct `TALE APPROVED` once both colliding entries survive dedup), and changing
  the override's family-resolution keys is higher-risk. Recommend a follow-up to project-qualify those maps; not bundled
  here to keep the change reviewable. (Consistent with the precedent in `sdd/tales/202605/...` where the deeper
  structural origin was deferred behind a contained display-layer fix.)
- **No memory file changes.**

## Tests

Add `tests/test_agent_loader_dedup_cross_project_collision.py` (model the existing `tests/test_agent_loader_dedup_*.py`
files):

1. **Reproduction / core fix** — two `WORKFLOW` agents with the **same** `raw_suffix` but **different** `project_file`,
   one `RUNNING` and one `DONE`. After `dedup_workflow_entries`: both survive, and the `RUNNING` one keeps `RUNNING`
   (its status is no longer overwritten to `DONE`). Assert insensitivity to input order (run with the `RUNNING` entry
   first and with it second).

2. **Family integration** — full scenario: a plan-chain root (`plan_chain_root`, `agent_family_role="root"`,
   `role_suffix="--plan"`, `plan_action="tale"`, `raw_suffix=R`), its running coder (`role_suffix="--code"`,
   `parent_timestamp=R`, `status="RUNNING"`, same `raw_suffix` as an unrelated agent), and an unrelated completed
   `WORKFLOW` agent in a different `project_file` sharing the coder's `raw_suffix`. Run the full
   `dedup_workflow_entries` + `_apply_status_overrides` and assert coder and root resolve to `TALE APPROVED` (not
   `TALE DONE`), and the unrelated agent stays `DONE`.

3. **Regression: same-project dedup still merges** — two `WORKFLOW` agents with the same `raw_suffix` **and** the same
   `project_file` (one `RUNNING`, one `DONE`/with metadata): still deduped to one entry, status preference (`RUNNING` →
   non-`RUNNING`) and metadata copies (`workspace_num`, `cl_name` "unknown"→known, `pid`) preserved.

4. **`dedup_running_vs_workflow`** — cross-project `RUNNING` ace-run vs `WORKFLOW` sharing `raw_suffix` are **not**
   merged; same-project still merges (guard via the existing visibility tests plus one new cross-project case).

## Verification

1. `just install` (ephemeral workspace — required before other `just` commands).
2. Targeted: the new dedup-collision test module + `tests/test_agent_loader_dedup_*` +
   `tests/test_run_workflow_visibility.py`.
3. `just check` (lint + mypy + tests) — required by repo rules after source changes.
4. Manual: with a live TALE coder running while another project's ace-run agent shares its launch second, confirm the
   coder/root read `TALE APPROVED` (it transitions to `TALE DONE` only once the coder actually completes).
