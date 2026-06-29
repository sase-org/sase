---
create_time: 2026-06-29 09:43:41
status: done
prompt: sdd/prompts/202606/hide_child_agent_step_prefix.md
---
# Plan: Hide the step-number prefix on child agent rows

## Problem / product context

On the **Agents** tab of `sase ace`, every workflow child row currently renders a small dim step-number prefix between
the tree indent and the runtime icon. Examples seen in the wild:

- `  └─ 1/1--0   main (ANSWERED) ...`
- `  └─ 1/1--plan  gh_..._actstat (TALE APPROVED) ...`
- `  └─ 1/1--code  gh_..._actstat (WORKING TALE) ...`
- `  └─ 1g/1   diff (DONE) ...`

These prefixes (`1/1--0`, `1/1--plan`, `1/1--code`, `1g/1`, etc.) are visual noise. The user wants them gone. The
information they encode is largely redundant: the tree indent already marks tree depth, the agent name (e.g.
`actstat-1.f1--code`) already carries the role, and the step glyph already marks step type. After this change, child
rows should render as just:

- `  └─ <runtime-icon> <name> (STATUS) ...` for agent steps, and
- `  └─ 🐚 <name> (STATUS) ...` / `  └─ 🐍 ...` for bash/python steps.

i.e. the tree indent and the per-step-type glyph stay; only the `N/M…` / `Nx/M` step-number prefix is removed.

## Scope

In scope:

- Remove the step-number prefix (both the regular `{step}/{total}{role}` form and the embedded
  `{parent}{substep}/{parent_total}` form) from child agent rows on the Agents tab.
- Keep the child tree indent and the per-step-type glyph (🐚/🐍) exactly as-is.
- Clean up code that becomes dead as a result, and update the small number of tests that assert on the prefix.

Out of scope:

- Any change to the trailing agent name / role suffix shown at the end of the row.
- Any change to ordering, fold counts, or detail-panel "Step 1/1" rendering (that is a separate rendering path in the
  prompt/workflow panel and must not change).
- Any change to the underlying `Agent` model fields (`step_index`, `total_steps`, `parent_step_index`,
  `parent_total_steps`, `role_suffix`) — these remain required by ordering, loaders, and the workflow detail panel.

## Where the behavior lives

All of this logic is in Python in this repo (not the Rust core).

**Primary render site** — `src/sase/ace/tui/widgets/_agent_list_render_agent.py`, inside `format_agent_option()`, the
`if agent.is_workflow_child:` block:

- It appends `_CHILD_INDENT` (keep).
- It then appends the step-number prefix via an inner `if agent.step_index is not None:` block with two branches —
  embedded (`{parent_num}{substep}/{parent_total}`) and regular (`{step_num}/{total}{role}`). **This inner block is what
  gets removed.**
- It then appends the per-step-type glyph from `_STEP_TYPE_GLYPHS` (keep).

**Helpers used only by that prefix block:**

- `get_substep_suffix` — imported from `sase.xprompt.workflow_output`; in `_agent_list_render_agent.py` it is used
  _only_ in the embedded branch. (The function itself stays — it is still used inside `workflow_output.py` and its own
  tests.)
- `step_role_suffix(agent)` — defined in `src/sase/ace/tui/widgets/_agent_list_helpers.py` and used _only_ by the
  regular branch. After removal it becomes dead code with no other callers or tests.

**Render cache key** — `src/sase/ace/tui/widgets/_agent_list_render_cache.py`, `agent_render_key()`. Its docstring
states it captures "every input that affects `format_agent_option`'s output." After this change, `step_index`,
`total_steps`, `parent_step_index`, and `parent_total_steps` no longer affect row output. `step_type` and
`is_workflow_child` (still needed for the glyph) must stay.

## High-level design / steps

1. **Remove the prefix block** in `_agent_list_render_agent.py`: delete the inner `if agent.step_index is not None:`
   block (both embedded and regular branches, including their comments). Leave the `_CHILD_INDENT` append and the
   `_STEP_TYPE_GLYPHS` glyph append in place so the indent + glyph still render.

2. **Drop now-unused imports/helpers:**
   - Remove the `from sase.xprompt.workflow_output import get_substep_suffix` import from `_agent_list_render_agent.py`.
   - Remove `step_role_suffix` from the `_agent_list_helpers` import block in `_agent_list_render_agent.py`.
   - Remove the now-unused `step_role_suffix()` function from `_agent_list_helpers.py`.

3. **Keep the cache key honest:** in `agent_render_key()`, drop `step_index`, `total_steps`, `parent_step_index`, and
   `parent_total_steps` (they no longer affect output). Keep `step_type` and `is_workflow_child`. This is safe —
   over-keying was harmless, but the docstring's contract is "render inputs only," so removing the now-irrelevant fields
   keeps it accurate. (If the implementer prefers maximum caution, leaving them is also correct; the recommendation is
   to remove for honesty with the docstring.)

4. **Update the affected tests** — only one file asserts on the prefix:
   `tests/ace/tui/widgets/test_agent_list_provider_emoji_badges.py`. Drop the `"1/2 "` / `"1/3 "` step-number portion
   from these four assertions so they assert only the glyph + name that remain:
   - `"1/2 🤖 child-agent (RUNNING)"` → `"🤖 child-agent (RUNNING)"`
   - `"1/2 🐚 diff (RUNNING)"` → `"🐚 diff (RUNNING)"`
   - `"1/3 \U0001f40d "` → `"\U0001f40d "`
   - `"1/3 \U0001f41a "` → `"\U0001f41a "`

   Consider adding one focused assertion that the step-number prefix is _absent_ for a workflow child (e.g. that the
   rendered `left.plain` for an agent child contains no `"/"`-style step token), to lock in the new behavior.

## Verification

- `just install` then `just check` (lint + mypy + tests). Lint will confirm there are no leftover unused
  imports/functions after the cleanup.
- Confirm no other tests assert on the prefix: a search of the test suite shows the only step-prefix assertions are the
  four lines in `test_agent_list_provider_emoji_badges.py`. The detail-panel `"Step 1/1"` assertion in
  `test_agent_display_workflow_async.py` comes from a different rendering path and must remain unchanged.
- The PNG visual snapshot suite renders no workflow-child rows, so no goldens should change; still run
  `just test-visual` and, only if an intentional diff appears, update with `--sase-update-visual-snapshots`.

## Risks / notes

- Low risk, presentation-only change confined to one render block plus dead-code cleanup. No Rust core boundary crossing
  (pure Textual presentation).
- The `Agent` model fields stay intact, so ordering, fold annotations, revive-modal child grouping, and the workflow
  detail panel are unaffected.
- Watch for accidental removal of the `_STEP_TYPE_GLYPHS` glyph append or the `_CHILD_INDENT` indent — both must remain.
