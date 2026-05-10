---
create_time: 2026-05-10 12:23:09
status: done
prompt: sdd/prompts/202605/bead_work_force_reuse_names.md
---
# Plan: `sase bead work` agent prompts use `%name:!` (forced-reuse) directives

## Problem

When `sase bead work <epic_id>` (or the legend variant) launches a fan-out of phase agents plus a final land agent, each
agent reserves a permanent name (`<epic_id>.<N>` for phases, `<epic_id>` for land). If something goes wrong mid-flight
and the user kills the agents, the **name reservations persist** in the agent-name registry / artifacts. Re-running
`sase bead work <epic_id>` then fails because the registry still shows those names as taken (or, if those agents are
still live, `find_live_name_collisions` blocks the launch).

The user wants restarts to be idempotent: kill the affected agents (or just re-run), then `sase bead work <epic_id>`
again, and the relaunch should succeed by wiping the stale owner records.

## Solution Sketch

The `%name` directive already supports a `!` prefix (`%name:!foo`) whose semantics are _"wipe the previous owner of this
name, then reuse it"_. The parsing/wipe machinery is fully built out — see `src/sase/agent/launch_validation.py` and
`src/sase/agent/names/_wipe.py`. What remains is to:

1. Make `render_multi_prompt` (and `render_legend_multi_prompt`) **always emit** `%name:!<name>` for every phase /
   epic-planning / land segment.
2. Plumb the wipe/confirm/rewrite handshake through the CLI handler so the prompt actually launches (the launcher's
   `validate_launch_name_requests` refuses raw `!` directives unless the caller has wiped + rewritten first).
3. Update the `find_live_name_collisions` pre-check so it is informational when force-reuse will wipe live owners anyway
   (or keep the hard block — see "Open question" below).

## Affected Files

### Source

- `src/sase/bead/work.py` — `render_multi_prompt` (`%name:` lines around line 332 and 343) and
  `render_legend_multi_prompt` (around 382 and 399). Both need to emit `%name:!<agent_name>` instead of
  `%name:<agent_name>`.
- `src/sase/bead/cli_work.py` — `_handle_epic_bead_work` and `_handle_legend_bead_work`:
  - After rendering, call `force_reuse_owner_names([rendered_query])`, `wipe_names_for_forced_reuse(...)`, then
    `rewrite_force_reuse_name_directives(rendered_query)` before invoking `launch_agent_from_cwd`. This mirrors the
    TUI's `_finish_agent_launch` handshake at `src/sase/ace/tui/actions/agent_workflow/_launch_start.py:38-80`.
  - Reconcile the existing `find_live_name_collisions` block with the new "wipe handles stale owners" semantics.

### Tests

Every test that asserts on the literal `%name:<name>` directive in rendered or dry-run output must be updated. Searching
for `%name:` in `tests/test_bead` turns up the following files (see grep results in the investigation):

- `tests/test_bead/test_work_rendering.py` — multiple `%name:p1`, `%name:e1`, `%name:l1.x`, etc. assertions in raw
  render strings.
- `tests/test_bead/test_work_epic_plan.py` — golden multi-line render fragments like `"%name:p1\n%group:e1\n…"`.
- `tests/test_bead/test_work_legend_plan.py` — same style for legend renders.
- `tests/test_bead/test_cli_work_epic.py` — dry-run assertions of the form `f"%name:{p1_id}\n%group:{epic_id}\n…"`.
- `tests/test_bead/test_cli_work_legend.py` — legend dry-run assertions (the dry-run path prints the rendered prompt,
  which now contains `!`).

A new dedicated test (in `test_cli_work_epic.py` and `test_cli_work_legend.py`) should cover the round-trip: a stale
name reservation exists, `sase bead work` is invoked, the wipe succeeds, the launcher receives a `%name:<name>` prompt
(no `!`), and the launch returns success.

## Implementation Sketch (plain-English, no diffs)

1. **`render_multi_prompt` and `render_legend_multi_prompt`** — change the two `f"%name:{...}"` constructions in each
   function to `f"%name:!{...}"`. This is the _only_ source change needed for the rendered prompt to carry the
   force-reuse marker. Update the docstrings to note the directive is force-reuse.

2. **`_handle_epic_bead_work` / `_handle_legend_bead_work`** — after rendering the query and before calling
   `_launcher.launch_agent_from_cwd`:
   - `from sase.agent.launch_validation import (force_reuse_owner_names, wipe_names_for_forced_reuse, rewrite_force_reuse_name_directives)`.
   - Compute `owner_names = force_reuse_owner_names([query])` — this returns the set of names that need wiping (it
     parses `%name:!…` from the prompt).
   - Call `wipe_names_for_forced_reuse(owner_names)` — best-effort; log/warn on partial failure as the TUI does.
   - Replace `query` with `rewrite_force_reuse_name_directives(query)` so the prompt that hits the launcher uses
     ordinary `%name:<name>` (this is what the launcher's `validate_launch_name_requests` accepts).
   - Pass the rewritten `query` into `launch_agent_from_cwd`.

3. **`find_live_name_collisions` pre-check** — see open question below. The conservative choice is to leave it intact:
   the pre-check still gives the user a clean "kill these first, then retry" error before any wipe runs. The wipe path
   then handles the stale (already-killed) owner records.

4. **Tests** — bulk-update every literal `%name:` assertion in the listed tests to `%name:!`. Add the round-trip
   stale-owner test described above.

## Behavioral Changes

- Re-running `sase bead work <epic>` after killing its agents now succeeds instead of failing with name-collision errors
  from stale registry entries.
- The dry-run output (`--dry-run`) shows `%name:!<name>` directives. This is the pre-wipe prompt; users seeing `!`
  should understand "this run will wipe any prior owner of these names before launching."
- The wipe is best-effort. If the registry wipe fails for a name, the subsequent `validate_launch_name_requests` call
  inside the launcher will surface a `AgentNameLaunchCollisionError` with the standard "name is taken" message — i.e.
  failure is loud and goes through the existing rollback path.

## Open Question

**Should `find_live_name_collisions` keep blocking the launch when previous agents are still live?**

- **Keep it (recommended)**: gives the user a clear error before any destructive wipe runs. Matches the user's stated
  workflow ("kill them, then re-run").
- **Drop it**: lets `wipe_names_for_forced_reuse` (which terminates live artifacts via `_terminate_live_artifacts` in
  `src/sase/agent/names/_wipe.py:87`) silently kill in-progress agents on every re-run. Surprising and risks losing
  in-flight work.

Default to keeping the pre-check unless the user prefers the more aggressive behavior.

## Non-Goals

- Adding a CLI flag to opt in/out of `!`. The user explicitly asked for always-on behavior.
- Touching the `permanent_agent_names` epic design or the `!` directive semantics — we are only an additional caller of
  an existing feature.
- Changing how the launcher itself interprets `%name:!` (no `allow_force_reuse=True` plumbing into
  `launch_agent_from_cwd`).
