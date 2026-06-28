---
create_time: 2026-06-28 09:07:36
status: done
prompt: sdd/prompts/202606/auto_before_xprompts.md
---
# Move Auto Metadata Before XPrompts

## Objective

Move the agent metadata panel's `Auto:` field so it renders immediately before the `Xprompts:` field on the `Agents` tab
of `sase ace`.

The display should keep the current `Auto:` label, lightning token, and per-kind styling from the recent auto-approve
metadata change. This is a presentation-only TUI ordering change; no backend, Rust core, agent loading, or auto-approve
state semantics should change.

## Current Behavior

`build_header_text` in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` currently appends metadata in
this relevant order:

1. `Workflow:` when present
2. `Xprompts:` when non-cheap header enrichment has xprompt metadata
3. `Model:`
4. `VCS:`
5. `Auto:` when `agent.approve` is enabled
6. `PID:` and later fields

That means an auto-approved agent that also used xprompts shows `Xprompts:` before `Auto:`, which is the opposite of the
requested layout.

`Xprompts:` is intentionally omitted on the cheap/immediate render path because xprompt metadata comes from disk-backed
summary enrichment. The ordering change therefore needs to be verified with a non-cheap header summary that contains
xprompt data.

## Proposed Change

In `build_header_text`, relocate the existing auto-approve metadata append logic to the pre-xprompt position:

1. Keep the existing workflow rendering where it is.
2. Append `Auto:` immediately after the workflow block and immediately before the xprompt section block.
3. Keep the existing xprompt rendering block unchanged apart from its new predecessor.
4. Leave `Model:`, `VCS:`, `PID:`, and later fields after `Xprompts:`.

Expected relevant order after the change:

1. `Workflow:` when present
2. `Auto:` when `agent.approve` is enabled
3. `Xprompts:` when non-cheap summary data is available
4. `Model:`
5. `VCS:`
6. `PID:` and later fields

If an approved agent has no rendered xprompt metadata, `Auto:` will still occupy this earlier metadata slot before
`Model:`/`VCS:`. That follows from making it the field immediately before the conditional `Xprompts:` block.

No duplicate auto-rendering should be introduced. If useful while editing, extract the existing auto field append into a
small local helper to make relocation less error-prone, but avoid broader refactors.

## Test Plan

Add focused unit coverage in `tests/ace/tui/widgets/test_agent_display_name_model_metadata.py` or a nearby
metadata-ordering test file:

- Build an approved agent with `cheap=False` and a `_DetailHeaderSummary` / `DetailHeaderSummary` containing at least
  one xprompt metadata entry.
- Assert the plain header contains `Auto: ⚡ PLAN` immediately before `Xprompts:` or, at minimum, that `Auto:` appears
  before `Xprompts:` with no intervening unrelated metadata field.
- Preserve existing assertions that `Mode:` and `Auto-Approve` do not appear.
- Keep the existing kind/style tests for `PLAN`, `TALE`, and `EPIC`; they should continue to pass without behavioral
  changes.

Update visual coverage in `tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py`:

- Reuse the existing auto-approve metadata visual flow or add one compact adjacent visual state where the selected
  approved agent has a temporary artifacts directory containing `xprompts.json`.
- Assert the rendered page includes both `Auto:` and `Xprompts:` before capturing.
- Generate/update the affected PNG golden so the `Agents` tab metadata panel has snapshot coverage for the combined
  `Auto:` plus `Xprompts:` layout.

## Validation

Because this implementation will change repo files, run:

1. `just install`
2. Targeted unit test for the metadata header file, for example:
   `./.venv/bin/pytest tests/ace/tui/widgets/test_agent_display_name_model_metadata.py`
3. Targeted visual snapshot update for the affected auto/xprompt metadata case:
   `./.venv/bin/pytest <visual-test-selector> --sase-update-visual-snapshots`
4. Targeted visual validation without update mode: `./.venv/bin/pytest <visual-test-selector>`
5. `git diff --check`
6. `just check`

Do not modify memory files or provider shim files if `sase validate` reports unrelated init/check drift. Report that
failure clearly if it occurs.

## Risks

- Moving `Auto:` before a conditional `Xprompts:` block also moves it earlier for agents without xprompt metadata. This
  is acceptable because the requested anchor is the `Xprompts:` position, and absent xprompt metadata leaves `Auto:` in
  the same early metadata group.
- Visual header enrichment is asynchronous, so the visual test should wait for the existing visual idle helpers before
  asserting/capturing.
- Avoid broad metadata reordering beyond the `Auto:` field; other fields should keep their current relative order.
