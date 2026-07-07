---
create_time: 2026-07-07 16:11:52
status: done
prompt: sdd/prompts/202607/tools_panel_detail_levels.md
---
# Plan: Collapse/Expand Tools-Panel Detail Levels with `h`/`l`

## Product Context

The Agents-tab Tools panel (`AgentToolsPanel`) renders a compact one-line-per-call timeline of an agent's tool-call
artifacts: `HH:MM:SS  status  [chip]  ToolName  target  duration`, plus an optional single dim detail line. This compact
view is great for scanning, but the underlying artifact records (written by `src/sase/llm_provider/_tool_call_*.py`)
store far more than the panel shows today:

- Full input summaries up to 512 chars per field (`command`, `file_path`, `pattern`, `url`, `description`, `timeout`,
  edit/content lengths, `subagent_type`, `prompt_length`, ...). The compact row truncates the primary target to ~88-96
  chars and drops the rest.
- Full response summaries: `exit_code`, `success`, `interrupted`, and multi-line
  `stdout_preview`/`stderr_preview`/`output_preview`/`content_preview`/`result_preview` blocks (512 chars each). The
  compact detail line shows at most one of these, squashed to one line and cut at 140 chars.
- Full `error` text (currently cut at 140 chars).
- Provenance metadata: `completed_at`, `runtime`, `source` (hook vs stream), `cwd`, `permission_mode`, `agent_type`,
  `tool_use_id`, `session_id`, and the artifact `source_path` + `line_number` the row came from.

This plan adds progressive disclosure of that data: `h`/`l` collapse/expand the Tools panel's level of detail, both when
the Tools panel is the active detail panel on the Agents tab and inside the Agents-tab Zoom modal. The default rendering
stays **exactly** as it is today — levels only ever add information.

## Design

### Detail levels

A single panel-wide detail level (no per-row cursor exists in this panel; it is one rendered `Static`), modeled as a
small enum with three states:

| Level | Name       | What renders                                                                                                     |
| ----- | ---------- | ---------------------------------------------------------------------------------------------------------------- |
| 0     | `compact`  | Byte-identical to today's rendering. Default.                                                                    |
| 1     | `expanded` | Compact row is kept unchanged; beneath each call, an indented detail block appears (see "Expanded block" below). |
| 2     | `full`     | Everything in `expanded`, plus one dim provenance/metadata line per call.                                        |

Three levels (not a boolean) because the forensic metadata in `full` is genuinely useful when debugging an agent run but
would pollute the "what did this call do" reading of `expanded`. The progression mirrors vim-style fold semantics the
user already has in their fingers on this tab.

### Key behavior

- `l` — expand one level (clamped at `full`).
- `h` — collapse one level (clamped at `compact`).
- `L` — jump straight to `full`; `H` — jump straight to `compact`. Mirrors the existing "expand/collapse all" semantics
  of `L`/`H` on the agents list.
- At a clamp boundary the key is a quiet no-op (matching fold actions, which are also silent at their boundaries).

### Routing (Agents tab)

There is no separate Textual-focus concept for the Tools panel on the base Agents tab — the panel is "focused" exactly
when the detail-panel mode is `DetailPanelMode.TOOLS` (cycled with `]`/`[`, i.e. `AgentDetail.is_tools_visible()`).
Routing therefore lives in the existing actions rather than new keymap entries:

- `action_expand_or_layout` (`l`), `action_hooks_or_collapse` (`h`), `action_expand_all_folds` (`L`), and
  `action_hooks_or_collapse_all` (`H`) in `src/sase/ace/tui/actions/agents/_folding.py` gain one new early branch: on
  the agents tab, if `AgentDetail.is_tools_visible()`, route to the Tools panel detail-level change and return;
  otherwise fall through to today's fold behavior unchanged.
- While the Tools panel is showing, `h`/`l`/`H`/`L` belong exclusively to it. No fall-through to list folding at clamp
  boundaries — fall-through would make the same keypress do two unrelated things depending on invisible state. Users
  toggle out of tools mode with `[`/`]` to fold groups.

Reusing the existing actions (instead of adding new keymap actions) means user keymap overrides of these keys keep
working automatically, and no changes to `src/sase/default_config.yml` or `keymaps/types.py` key definitions are needed.
The action _description_ strings shown in the command palette / help (`commands/_app_metadata.py`, e.g. "Expand entry /
change layout") are updated to mention the tools-detail meaning.

### Routing (Zoom modal)

`ZoomPanelModal` uses hardcoded `Binding`s and currently leaves `h`/`l`/`H`/`L` unbound. Add bindings for all four, with
actions that adjust the zoomed `_ZoomToolsPanel`'s detail level only when `self._target == ZoomPanelTarget.TOOLS`, and
quietly no-op on other targets.

The zoom modal seeds its panels from the base tab (`ZoomPanelSeed`); add a `tools_detail_level` seed field so zooming
preserves whatever detail level the base panel is showing (one-way seed, like the other seed fields).

### State and lifecycle

- `AgentToolsPanel` holds `_detail_level` (default `compact`), with a small public API: `expand_detail()`,
  `collapse_detail()`, `set_detail_level(...)` — each returns whether the level changed — plus a read-only
  `detail_level` property. The zoomed subclass inherits all of it.
- The level is per-panel-instance UI state: it persists across `j`/`k` agent switches and background refreshes (like
  `_panel_mode` does) and resets to `compact` on app restart. It is not persisted to config (possible future
  enhancement, out of scope).
- On a level change, the panel re-renders **synchronously from its cached rows** (`_last_entries`/`_last_rows`) via the
  existing `_display_tools_with_timestamp` path — no worker, no disk I/O, no new refresh path — and preserves the scroll
  position with the existing save/restore helpers. If the panel has no content ("No tools artifact available" / "No tool
  calls recorded" / no agent), level changes are no-ops.
- Background refresh workers and the zoom modal's refresh timer re-render through the same builder, which reads the
  instance's current level — so a refresh landing mid-session keeps the chosen level with no race.

### Expanded rendering (the "beautiful" part)

The compact row is never altered — stepping levels only grows each call downward, so the eye keeps its anchor. At
level >= 1, each call gains an indented block aligned under the tool-name column, grouped by a dim `│` gutter so
multi-line blocks read as one call; a blank line separates calls.

Level 1 (`expanded`) block content, rendering only fields that exist:

1. **Full target** — the full stored value of the primary input (`command`, `file_path`, `url`, `pattern`, `query`),
   shown only when the compact row had to truncate it. Wrapped, not squashed to one line.
2. **Input fields** — the remaining input-summary keys (`description`, `timeout`, `replace_all`, `offset`/`limit`,
   `content_length`, `old/new_string_length`, `edits_count`, `subagent_type`, `prompt_length`, `input_keys`, `raw` under
   `SASE_TOOL_LOG_FULL`, ...) as `key value` pairs, small scalars packed onto shared lines to stay tight. Key labels dim
   italic, values plain.
3. **Response** — scalar line (`exit 2 · failed · interrupted`) followed by labeled multi-line preview blocks (`stdout`,
   `stderr`, `content`, ...) rendered from the stored 512-char previews, each capped at ~6 lines with a
   `… (+N more lines)` tail. stdout/content dim; stderr in a muted red tint.
4. **Error** — full stored error text, bold red, multi-line.

Level 2 (`full`) appends one dim metadata line per call: completed time (HH:MM:SS, local tz), `runtime`/`source` (e.g.
`claude/hook`), `permission_mode`, `agent_type`, `cwd`, `tool_use_id`, short `session_id`, and `source_path:line_number`
of the artifact row.

Header feedback: at level >= 1 the existing dim summary line ("N calls · N failures · ... · refreshed HH:MM:SS") gains a
`· detail: expanded` / `· detail: full` suffix. At level 0 the output stays byte-identical to today (hard requirement),
so no indicator is added there.

Styling reuses the panel's existing palette (dim metadata, `#87D7FF` accents, `#D7D7AF` targets, bold red failures) so
the expanded view reads as the same surface, just deeper.

### Markdown export parity

`get_tools_text()` / `_build_tools_timeline_markdown` become detail-level aware so `E` (edit in editor) and `y` (copy,
zoom) export what is on screen — expanded blocks appear as indented sub-lines under each `|`-joined row.

### Discoverability

- **Footer** (`_keybinding_bindings.py` / `keybinding_footer.py`): per the footer convention (conditional keymaps only),
  add chips shown only when the agents tab has the Tools panel active: `l` -> `more detail` (hidden at `full`) and `h`
  -> `less detail` (hidden at `compact`). The host passes the tools visibility + level into `_compute_agents_bindings`.
- **Zoom hints label**: the static hint line gains `h/l detail` while the TOOLS target is active (updated from
  `_show_target`, which already runs on every target change).
- **Help modal** (`modals/help_modal/agents_bindings.py`): document the contextual meaning — e.g. extend the folding
  section entry with "(Tools panel showing: adjust detail level)" — per the ace CLAUDE.md rule that the `?` popup must
  stay in sync.

## Technical Notes

### Files touched (all presentation-layer Python; no `sase-core` changes — artifact parsing already

lives in this repo and detail levels are pure TUI state)

- `src/sase/ace/tui/widgets/tools_panel.py` — detail-level enum + state + public API; extend
  `_build_tools_timeline_text` / `_build_tools_timeline_markdown` with a `detail_level` parameter (level 0 output
  unchanged); synchronous cached re-render with scroll preservation.
- `src/sase/ace/tui/widgets/agent_detail.py` (or the panel mixin) — thin pass-throughs (`expand_tools_detail()` etc.)
  that query the tools panel, used by the app actions.
- `src/sase/ace/tui/actions/agents/_folding.py` — tools-detail early branch in the four fold actions (agents tab only).
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — `h`/`l`/`H`/`L` bindings + target-guarded actions;
  `ZoomPanelSeed.tools_detail_level`; dynamic hint line.
- `src/sase/ace/tui/actions/agents/_panel_detail.py` — seed the new field in `_zoom_seed_from_detail`.
- `src/sase/ace/tui/widgets/_keybinding_bindings.py` + `keybinding_footer.py` — conditional footer chips.
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`, `src/sase/ace/tui/commands/_app_metadata.py` — documentation
  strings.

### Performance (per `memory/tui_perf.md`)

- Level changes never touch disk: they re-render from `_last_rows` synchronously. Building Rich Text for a few hundred
  entries is the same magnitude of work the panel already does on every worker completion; no event-loop I/O is
  introduced.
- No new refresh paths: level changes reuse `_display_tools_with_timestamp`; data refreshes keep flowing through the
  existing worker/cache pipeline.
- Preview blocks are line-capped, keeping worst-case render size bounded (~10-14 lines per call at `full`).

## Edge Cases

- Empty/missing tools content: `h`/`l` still route to the Tools panel while it is the active mode but no-op (no fold
  side effects).
- Pending calls (no response yet): expanded block renders input fields only.
- `SASE_TOOL_LOG_FULL=1` `raw` summaries: rendered through the generic bounded key/value path.
- Attempt-pinned view bypasses the tools panel entirely (existing behavior) — no routing change.
- Root aggregate rows (source chips from multiple agents): expanded blocks indent identically; the chip stays on the
  compact row only.

## Testing

- **Timeline unit tests** (`tests/ace/tui/widgets/test_tools_panel_timeline.py` style): level-0 output identical to
  current expectations (regression lock); level 1 surfaces full targets, input fields, stdout/stderr previews, and full
  errors; level 2 surfaces provenance; preview line-capping; markdown export at each level; header suffix only at
  level >= 1.
- **Widget behavior tests**: expand/collapse clamping and return values; no-op without content; level persists across
  `update_display`/worker completion; scroll preserved on level change.
- **Action routing tests** (pilot-based, like `test_panel_mode_cycle_refresh.py`): with TOOLS mode active,
  `h`/`l`/`H`/`L` change the tools detail level and leave fold state untouched; with the file panel active, fold
  behavior is unchanged (regression).
- **Zoom modal tests** (`test_agents_zoom_panel_modal.py` style): `l`/`h` adjust detail only on the TOOLS target; seed
  carries the base panel's level into the modal.
- **PNG visual snapshots** (`tests/ace/tui/visual/test_ace_png_snapshots_tools.py`): new goldens for `expanded` and
  `full` on the Agents tab (fixture extended with multi-line stdout/stderr/error previews so the snapshots exercise the
  block layout), keeping the existing compact snapshot as the unchanged-default guard.
- **Footer/help checks**: footer chip visibility conditions; help-modal text updated.

## Out of Scope / Future

- Per-call (row-level) expansion — no row cursor exists in this panel today.
- Persisting the preferred detail level to config.
- Raising the 512-char artifact preview limit at write time (would require changes on the `llm_provider` writer side and
  affects artifact size; the display layer renders whatever is stored).
