---
bead_id: sase-614
status: done
---

# File Content Trimming for Agents Tab File Panel

## Context

Large files in the Agents tab file panel slow down the TUI because all content is rendered at once via Rich `Syntax`
widgets. This feature trims files to the panel's visible height by default, with keybindings to expand/collapse, and
auto-expand on scroll-at-bottom.

## Phase 1: Core Trimming + Visual Indicators

**Goal**: Files auto-trim to fit the panel. Border subtitle shows line counts. No expand/collapse keys yet.

### Files to Modify

#### 1. `src/sase/ace/tui/widgets/file_panel.py` — Core trimming logic

**New message class** — Add `FileTrimChanged(Message)` after existing message classes:

- Fields: `visible_lines: int`, `total_lines: int`, `is_trimmed: bool`

**New state in `__init__`**:

- `_total_line_count: int = 0` — total lines in current content
- `_visible_line_count: int = 0` — lines currently shown
- `_base_trim_size: int = 0` — initial page size (viewport height - 4)
- `_is_trimmed: bool = False`
- `_full_content: str | None = None` — stored for re-render on expand/collapse
- `_full_content_lexer: str = "text"` — lexer for re-rendering
- `_content_mode: str = "none"` — `"static"`, `"diff"`, or `"static_diff"`
- `_static_header_path: str | None = None` — file path header for static mode

**New methods**:

- `_compute_trim_size() -> int` — Returns `max(10, container.scrollable_content_region.height - 4)` using
  `_get_scroll_container()`. Returns 0 if container not mounted.
- `_reset_trim_state()` — Zeros all trim fields. Called on agent/file switch.
- `_render_trimmed_content()` — Re-renders `_full_content` using `Syntax(..., line_range=(1, visible_lines))` when
  trimmed. Appends a `Text(f"\n  ▾ {remaining} more lines below", style="dim italic #87D7FF")` indicator. Posts
  `FileTrimChanged`.
- `_post_trim_changed()` — Posts the `FileTrimChanged` message.

**Modify `display_static_file`** (line 550):

- After reading content, store in `_full_content`, detect lexer, count lines
  (`content.count('\n') + (1 if not content.endswith('\n') else 0)`)
- Compute trim size. If `total > trim_size`: use `line_range=(1, trim_size)` and append "more lines" indicator
- If content fits: render normally (no `line_range`)
- Post `FileTrimChanged` in both paths

**Modify `_display_file_with_timestamp`** (line 309):

- Store `diff_with_header` in `_full_content`, set `_content_mode = "diff"`
- Count lines, compute trim, render with `line_range` if needed
- Append "more lines" indicator when trimmed

**Modify `display_static_diff`** (line 514):

- Same pattern: store content, count, trim, render with `line_range`

**Call `_reset_trim_state()`** at the start of:

- `set_file_list()` (line 162)
- `update_display()` (line 116)
- `show_empty()` (line 508)

**Preserve trim state on background refresh**: In `on_worker_state_changed`, when content unchanged, keep current
`_visible_line_count` instead of resetting to `_base_trim_size`.

#### 2. `src/sase/ace/tui/widgets/agent_detail.py` — Border subtitle for trim info

**New state in `__init__`**:

- `_trim_visible_lines: int = 0`
- `_trim_total_lines: int = 0`
- `_trim_is_trimmed: bool = False`

**Import** `FileTrimChanged` from file_panel (line 14).

**New handler `on_file_trim_changed`**: Stores trim state, calls `_update_file_scroll_subtitle()`.

**New method `_update_file_scroll_subtitle`**: Sets `#agent-file-scroll.border_subtitle`:

- When trimmed: `"Lines 1-{visible} of {total}"` in dim #87D7FF
- When showing all: `"{total} lines"` in dim green
- When empty: `""`

**Reset** trim state in `show_empty()`.

#### 3. `src/sase/ace/tui/styles.tcss` — CSS for file scroll subtitle

Add `border-subtitle-align: center;` to `#agent-file-scroll` (line 444-449).

#### 4. `src/sase/ace/tui/widgets/__init__.py` — Export new message

Add `FileTrimChanged` to imports from `file_panel` and to `__all__`.

### Key API Details

- Rich `Syntax(code, lexer, line_range=(1, N))` — renders only lines 1 through N (inclusive, 1-indexed). Verified
  working.
- `VerticalScroll.scrollable_content_region.height` — viewport rows (accounts for border, padding with
  `scrollbar-gutter: stable`)

---

## Phase 2: Keybindings + Auto-Expand on Scroll-at-Bottom

**Goal**: Users can expand/collapse/reset/show-all with keyboard. Ctrl+D at bottom auto-expands.

### Files to Modify

#### 1. `src/sase/ace/tui/widgets/file_panel.py` — Trim manipulation methods

**New public methods**:

- `expand_by_page()` — `visible_line_count = min(visible + base_trim_size, total)`, re-render
- `collapse_by_page()` — `visible_line_count = max(visible - base_trim_size, base_trim_size)`, save/restore scroll,
  re-render
- `reset_trim()` — Recompute `base_trim_size` from current viewport, set `visible_line_count = min(base, total)`,
  re-render
- `show_all_lines()` — `visible_line_count = total`, re-render
- `is_trimmed` property — Returns `_is_trimmed`

#### 2. `src/sase/ace/tui/widgets/agent_detail.py` — Proxy methods

**New methods** that delegate to file panel:

- `expand_file_trim()`, `collapse_file_trim()`, `reset_file_trim()`, `show_all_file_lines()`
- `is_file_trimmed() -> bool`

#### 3. `src/sase/ace/tui/actions/agents/_interaction.py` — Action methods

**New actions** (tab-guarded, file-visible-guarded):

- `action_expand_file_trim()` → `agent_detail.expand_file_trim()`
- `action_collapse_file_trim()` → `agent_detail.collapse_file_trim()`
- `action_reset_file_trim()` → `agent_detail.reset_file_trim()`
- `action_show_all_file_lines()` → `agent_detail.show_all_file_lines()`

#### 4. `src/sase/ace/tui/app.py` — Keybindings

Add after line 178 (E binding):

```python
Binding("plus", "expand_file_trim", "Expand", show=False),
Binding("minus", "collapse_file_trim", "Collapse", show=False),
Binding("equals_sign", "reset_file_trim", "Reset Trim", show=False),
Binding("asterisk", "show_all_file_lines", "Show All", show=False),
```

Textual key names (verified): `"plus"`, `"minus"`, `"equals_sign"`, `"asterisk"`

#### 5. `src/sase/ace/tui/actions/navigation/_basic.py` — Auto-expand on Ctrl+D

**Modify `action_scroll_detail_down`** (line 100):

- When on agents tab with `#agent-file-scroll`:
  1. Check `scroll_container.scroll_y >= scroll_container.max_scroll_y - 1`
  2. If at bottom AND `agent_detail.is_file_trimmed()`: call `agent_detail.expand_file_trim()`
  3. Schedule scroll-down via `call_after_refresh(lambda: scroll_container.scroll_relative(y=height//2, animate=False))`
  4. Return early (don't do the normal scroll)
- If not at bottom or not trimmed: do normal half-page scroll

#### 6. `src/sase/ace/tui/widgets/keybinding_footer.py` — Footer hint

Add to `_compute_agent_bindings` (around line 391, after layout toggle):

```python
if file_visible:
    bindings.append(("+/-", "trim"))
```

#### 7. `src/sase/ace/tui/modals/help_modal/bindings.py` — Help modal

Add to `AGENTS_BINDINGS` "Agent Actions" section (after Ctrl+N/P entry at line 133):

```python
("+ / -", "Expand / collapse file content"),
("=", "Reset file trim to default"),
("*", "Show all file lines"),
```

---

## Verification

After each phase, test with:

```bash
# Basic display (needs agents with files to test trimming)
.venv/bin/sase ace --agent --size 120x40 --keys tab

# Navigate and check file content is trimmed
.venv/bin/sase ace --agent --size 120x40 --keys tab j

# Run lint + tests
just lint && just test
```

Manual testing in live TUI:

1. Open `sase ace`, switch to Agents tab
2. Select an agent with a large file — verify content is trimmed, subtitle shows "Lines 1-N of M"
3. (Phase 2) Press `+` to expand, `-` to collapse, `=` to reset, `*` to show all
4. (Phase 2) Scroll to bottom with `ctrl+d`, verify auto-expand when trimmed
5. Switch files with `ctrl+n` — verify trim resets
6. Switch agents with `j/k` — verify trim resets
