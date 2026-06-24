---
create_time: 2026-06-24 08:58:52
status: done
prompt: sdd/prompts/202606/move_pencil_before_runtime.md
---
# Plan: Move the file-change pencil to just before the agent runtime

## Goal

On the **Agents** tab of the `sase ace` TUI, the pencil glyph (`✏️`) shown for agents that have made file changes
currently sits on the **left** side of the row, immediately after the LLM provider badges and before the agent's display
name.

Move that pencil to the **right** side of the row so it renders **immediately before the agent runtime suffix** — and,
when an agent is actively running, immediately before the running emoji (`🏃‍♂️`).

### Before / after (running agent)

```
Before:  [agent] 🎭 ✏️ my-agent (RUNNING)                      🏃‍♂️ 1m23s
After:   [agent] 🎭 my-agent (RUNNING)                      ✏️ 🏃‍♂️ 1m23s
```

### Before / after (finished agent)

```
Before:  [agent] 🎭 ✏️ my-agent (DONE)                  Apr 26 14:30 · 5m
After:   [agent] 🎭 my-agent (DONE)                  ✏️ Apr 26 14:30 · 5m
```

The LLM provider badges stay exactly where they are (left side). Only the pencil moves.

## Product context

The right-hand "runtime suffix" column is the row's metadata column: it shows the running emoji + live elapsed time for
active agents, or a finish timestamp + total duration for completed agents. Relocating the pencil so it leads that
column groups the "this row touched files" signal with the runtime metadata and de-clutters the left side (where the
provider badge already prefixes the name). The pencil must still appear for **every** agent with file changes, including
the rare case where the row has no runtime suffix at all.

## Relevant code (all Python; presentation-only)

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
  - `format_agent_option(...)` — assembles the row. The pencil is appended to the left-side `text` at the block right
    after the provider badges. The right-side `suffix` is assembled near the end via
    `combine_suffixes(build_activity_suffix(agent), build_runtime_suffix(agent, ...))`.
- `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
  - `build_runtime_suffix(...)` — builds the right-side runtime `Text`. For **active** rows it leads with the
    running-emoji live marker (`_RUNTIME_LIVE_MARKER = "🏃‍♂️ "`); for **finished** rows it leads with the finish
    timestamp; it can also lead with the unread/✋ paused markers. It returns an **empty** `Text` when no runtime should
    show.
  - `combine_suffixes(*parts)` — joins non-empty suffix fragments with a dim `·`.
- `src/sase/ace/tui/widgets/_agent_list_styling.py`
  - `_FILE_CHANGE_GLYPH = "✏️"`, `_FILE_CHANGE_GLYPH_STYLE = "bold #FFD75F"` (unchanged).
- `src/sase/ace/tui/models/agent_time.py`
  - `compute_row_runtime(...)` returns `(None, "<dur>")` for active rows (no timestamp → running emoji leads) and
    `((date, time), "<dur>")` for finished rows. This is why the running emoji leads the runtime suffix for running
    agents.

The pencil is rendered in exactly **one** place today (`_agent_list_render_agent.py`, the provider-badge block). Banner
rows and attempt rows do not render it, so there is a single render site to change. The render cache key already tracks
file-change state (`agent_render_key` covers `diff_path` / live hint), so no cache-key change is needed — we are
changing _where_ the glyph draws, not _whether_ it draws.

### Rust core boundary check

This is purely TUI presentation: the position of a glyph within a Textual row. Per the core/backend boundary rule,
widget rendering and layout glue stay in this repo. The determination of _whether_ an agent has file changes is
unchanged and already lives behind `agent_file_change_hint`. No `sase-core` changes are required.

## Design

1. **Remove** the left-side pencil block (the `if _has_file_change_hint(agent): ...` block that appends
   `_FILE_CHANGE_GLYPH` to `text` immediately after the provider-badge loop). The provider-badge loop itself is
   untouched.

2. **Prepend** the pencil to the right-side runtime suffix when the agent has file changes, gluing it directly in front
   of the runtime content with a single space (not the `·` column separator) so it reads as `✏️ 🏃‍♂️ 1m23s` /
   `✏️ Apr 26 14:30 · 5m` — mirroring the tight `✏️ `-then-content spacing it had on the left. Concretely, build the
   runtime suffix first, and if `_has_file_change_hint(agent)` is true, wrap it:
   - pencil glyph (styled with `_FILE_CHANGE_GLYPH_STYLE`),
   - then, **only if** the runtime suffix is non-empty, a single space followed by the existing runtime `Text`.

   This guarantees the pencil still shows when the runtime suffix would otherwise be empty (the fragment becomes a lone
   `✏️`). Feed the resulting fragment into `combine_suffixes` in place of the bare runtime suffix, keeping
   `build_activity_suffix(agent)` as the first fragment. With an activity label present the row reads
   `<activity> · ✏️ <runtime>` — pencil still immediately before the runtime.

   Implement this inline in `format_agent_option` (it already imports `_has_file_change_hint`, `_FILE_CHANGE_GLYPH`, and
   `_FILE_CHANGE_GLYPH_STYLE`), so no new cross-module imports are introduced. A small private helper in
   `_agent_list_render_layout.py` is an acceptable alternative, but the inline approach reuses already-imported names
   and is lower risk.

3. No change to styling constants, the provider-badge logic, the reverted badge, the cache key, or `combine_suffixes`
   itself.

## Test updates

All affected tests are in `tests/ace/tui/widgets/test_agent_display_list_rendering.py` (class
`TestAgentListFileChangePencil` and the provider-emoji ordering tests). They currently unpack
`left, _, _ = format_agent_option(...)` and assert the pencil appears in `left.plain`. After the move, the pencil lives
in the **suffix**, so they must capture and assert against the suffix (the second tuple element).

Key updates:

- "renders pencil" tests (`test_row_with_diff_path_renders_pencil`, `test_row_with_classified_real_diff_renders_pencil`,
  `test_row_with_live_hint_renders_pencil_without_diff_path`): assert `"✏️"` is **in** the suffix and **not in**
  `left.plain`.
- "omits pencil" tests (`test_row_with_classified_bookkeeping_diff_omits_pencil`,
  `test_row_without_diff_path_omits_pencil`, `test_row_with_false_live_hint_omits_pencil`,
  `test_persisted_classification_wins_over_live_hint`): assert `"✏️"` is in **neither** `left.plain` nor the suffix.
- `test_root_row_renders_provider_then_pencil_before_name`: repurpose — assert the provider badge (`🐙`) still renders
  in `left.plain` and the pencil now renders in the suffix (no longer between provider and name on the left).
- `test_pencil_flows_before_display_name_not_bead_metadata`: its premise (pencil flows on the left before the display
  name) no longer holds. Replace it with a test asserting the pencil renders in the suffix and that `left.plain` no
  longer contains `✏️`.
- `test_non_agent_workflow_child_row_omits_provider_emoji` asserts `"1/2 🐚 ✏️ diff (RUNNING)"` in `left.plain`; update
  the expected left string to drop the pencil and assert the pencil is in the suffix instead.

Add focused coverage for the new ordering:

- **Running agent**: pencil immediately precedes the running emoji in the suffix (e.g. `"✏️ 🏃‍♂️"` substring, or pencil
  index < `🏃` index). To make the runtime suffix deterministic, set the agent's `run_start_time` and pass a fixed
  `now=` so the elapsed duration is stable.
- **Finished agent**: pencil immediately precedes the runtime timestamp in the suffix.

Because the elapsed duration in the suffix is time-dependent unless `now=` is pinned, prefer substring / index-based
assertions for the pencil rather than exact full-suffix equality, and pin `now=` where an exact ordering check is
wanted.

The implementer should inspect actual rendered output for the chosen fixtures (the `make_agent` default has
`status="RUNNING"` and a `start_time` but **no** `run_start_time`, so its runtime suffix may be empty — meaning the
pencil could render alone as `✏️`; verify and assert accordingly).

`tests/ace/tui/widgets/test_agent_render_key_badges.py` exercises only the cache key (unchanged) and should keep passing
as-is. `tests/ace/tui/test_agents_live_hint_refresh.py` covers hint detection/refresh, not glyph position, and should be
unaffected — but run it to confirm.

## Visual (PNG) snapshot tests

The standard agents-list PNG goldens (e.g. `agents_list_120x40.png`, `agents_selected_row_120x40.png`) do **not** set
`diff_path`/`live_file_change_hint`, so they have no pencil and should be byte-identical after the change. The only
visual fixture that gives an agent a `diff_path` is the agents zoom-modal suite
(`tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py`), which renders zoom modals over the row; whether the
moved pencil is visible behind the modal must be verified by running the suite. Run `just test-visual` and, only if a
diff is the intended pencil relocation, regenerate the affected goldens with `--sase-update-visual-snapshots`. Do not
blanket-accept snapshot changes.

## Verification

1. `just install` (ephemeral workspace may have stale deps).
2. `just check` (ruff + mypy + fast tests).
3. `just test-visual`; review any diff and update goldens only for the intended change.
4. Manual smoke (optional): launch `sase ace`, confirm an agent with file changes shows the pencil just before the
   runtime suffix — before `🏃‍♂️` while running, before the finish timestamp once done — and that the LLM provider badge
   is unchanged on the left.

## Out of scope

- No change to how file-change state is detected (`agent_file_change_hint`, the live-hint refresh, or diff
  classification).
- No change to provider badges, the reverted badge, status text, or the runtime/timestamp formatting itself.
- No `sase-core` / non-TUI surfaces.
