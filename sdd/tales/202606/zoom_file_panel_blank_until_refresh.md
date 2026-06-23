---
create_time: 2026-06-23 08:06:38
status: done
prompt: sdd/prompts/202606/zoom_file_panel_blank_until_refresh.md
---
# Fix: ACE Agents-tab zoom file panel renders nothing until manual refresh

## Problem

On the **Agents** tab of the `sase ace` TUI, pressing `z` (zoom) to open the near‑fullscreen detail zoom modal
**frequently shows an empty file panel**. The user must press `r` (refresh) inside the zoom modal to get the file
content to appear. The same empty‑until‑`r` behavior shows up when paging between files with `<ctrl+n>` / `<ctrl+p>`
inside the zoom modal.

This is a regression in interactive behavior — the zoom modal is supposed to paint the content that the underlying
detail panel was already showing, immediately, with no manual refresh.

## Root cause (confirmed empirically)

The repo runs **Textual 8.2.7**. In this version, `textual.widgets.Static` (the base class of every ACE detail panel —
file, prompt/metadata, tools) **no longer exposes a `renderable` attribute**. Content is now stored in and read back
through the `content` property (`Static.update(x)` sets `self.content = x`; the rendered visual is exposed separately as
`.visual`). Verified directly:

- `hasattr(Static, "renderable")` → `False`
- `hasattr(AgentFilePanel, "renderable")` → `False`
- After `panel.update(group)`: `panel.content is group` → `True`

The zoom feature seeds its hosted panels from the live detail panels so the first frame is not empty. That seed capture
reads the **old** attribute name:

- `src/sase/ace/tui/actions/agents/_panel_detail.py`, `_zoom_seed_from_detail()`:
  ```python
  metadata_renderable=getattr(prompt_panel, "renderable", None),
  file_renderable=getattr(file_panel, "renderable", None),
  tools_renderable=getattr(tools_panel, "renderable", None),
  ```
  Because `renderable` no longer exists, `getattr(..., "renderable", None)` always returns **`None`**. So
  `ZoomPanelSeed.metadata_renderable / file_renderable / tools_renderable` are always `None`, and
  `ZoomPanelModal._seed_panels()` — whose job is to "paint base‑panel renderables immediately to avoid an empty first
  frame" — paints **nothing** (it guards each paint with `if self._seed.X_renderable is not None:`).

Why the **file** panel specifically stays blank (instead of just flickering for one frame):

- On mount, `ZoomPanelModal._refresh_active_panel(force=False)` → `_refresh_file(force=False)`.
- For a non‑active (DONE/FAILED/etc.) agent with files, this calls `panel.set_file_list(agent.all_files, ...)`.
- The zoom file panel's `_file_list` **was** seeded correctly (the seed copies `_file_list`, which is a still‑valid
  attribute) and, for a completed agent, the base panel had populated `_file_list` via `set_file_list(agent.all_files)`
  — so the seeded `_file_list` is already **equal** to `agent.all_files`.
- `AgentFilePanel.set_file_list()` early‑returns when `files == self._file_list`:
  ```python
  if files == self._file_list and self._file_list:
      return   # never calls _display_file_at_current_index()
  ```
  So no file is displayed and no read worker is started. With the seed paint dead, the panel is genuinely **blank**.
- Pressing `r` runs `_refresh_file(force=True)`, which calls `display_static_file(current_path)` / `refresh_file(agent)`
  — these unconditionally paint — so the content finally appears. That is exactly the user's workaround.

The **metadata** and **tools** zoom targets mostly escape the persistent‑blank symptom because their refresh path
(`update_display`) repaints on every tick regardless of the seed; the dead seed only costs them a one‑frame flicker. The
**file** target is uniquely broken because its refresh path early‑returns.

The same dead `renderable` access also breaks the `y` (copy) fallback for the metadata target:
`ZoomPanelModal._zoom_text()` does `_renderable_to_text(getattr(active_panel, "renderable", None))` → always `None` →
"No content to copy" when copying the zoomed metadata panel.

`<ctrl+n>` / `<ctrl+p>` inside the zoom modal: with the initial file (index 0) never rendered into the panel's own
state, single‑file agents make `next_file()`/`prev_file()` a no‑op (the panel stays on the blank initial frame), and the
very first file slot remains blank until it is navigated away from and back, or `r` is pressed.

### Scope of the broken attribute access

`grep` shows the dead `"renderable"` access is confined to the zoom feature (4 call sites):

- `src/sase/ace/tui/actions/agents/_panel_detail.py:226–228` (seed capture, 3 fields)
- `src/sase/ace/tui/modals/zoom_panel_modal.py:373` (copy fallback)

(The `graphics/renderable` import is an unrelated module name, not this attribute.)

### Architecture boundary note

This is purely Textual presentation glue (zoom modal seed capture + file‑panel rendering state). It does **not** cross
the Rust core backend boundary — no `sase-core` wire/API/binding changes are needed.

## Fix

Two parts: (1) the root‑cause one‑line‑per‑site attribute fix, and (2) a small robustness fix so the zoom file panel
actually owns/loads its content instead of depending solely on a fragile snapshot.

### Part 1 — Restore seed + copy capture for Textual 8.x (root cause)

Read content through the current `content` property instead of the removed `renderable` attribute.

- In `_zoom_seed_from_detail()` (`actions/agents/_panel_detail.py`), capture `getattr(prompt_panel, "content", None)`,
  `getattr(file_panel, "content", None)`, `getattr(tools_panel, "content", None)` for the three `*_renderable` seed
  fields.
- In `ZoomPanelModal._zoom_text()` (`modals/zoom_panel_modal.py`), capture `getattr(active_panel, "content", None)` for
  the copy fallback.

Notes / care:

- A freshly‑constructed `Static` has `content == ""` (empty string, **not** `None`). To keep the original "don't paint
  an empty first frame" intent, `_seed_panels()` should treat empty content as "nothing to seed" (switch the
  `is not None` guards to a truthiness check, or skip when `not seed.X_renderable`). Painting `""` is harmless, but
  skipping is cleaner and matches intent.
- The captured `content` is the same Rich renderable that was passed to `update()`, so it can be re‑applied via the zoom
  panel's `update()` and printed via `console.print()` in the copy path — both verified.
- `ZoomPanelSeed` field names (`*_renderable`) can stay as‑is to keep the change minimal; optionally rename to
  `*_content` for clarity (cosmetic, not required).

### Part 2 — Make the zoom file panel load its current file on first show (robustness)

Even with Part 1 restoring the instant paint, the seed is only a static snapshot: the zoom file panel's own trim/content
state (`_full_content`, `_base_trim_size`, …) is never initialized when `set_file_list` early‑returns, so `=` (show all)
/ `-` (reset trim) silently no‑op on the first file and the content can't live‑update. Fix the early‑return so it only
skips work **after** the panel has actually displayed something:

- In `AgentFilePanel.set_file_list()` (`widgets/file_panel/__init__.py`), tighten the unchanged‑list early‑return guard
  to also require that content has already been displayed:
  ```python
  if files == self._file_list and self._file_list and self._has_displayed_content:
      return
  ```
  On a fresh zoom panel `_has_displayed_content` is `False`, so the first `set_file_list` proceeds to
  `_display_file_at_current_index()` and loads the current file (diff/plan/etc.) into the panel's own state —
  `=`/`-`/scroll‑trim then work, and the panel no longer depends on the seed being correct.

Why this is safe:

- The base `AgentFilePanel` never hits the new condition: on an agent's first display its `_file_list` differs from the
  incoming `files` (it was `[]` or the previous agent's list), so it already proceeds; on later same‑agent refreshes
  `_has_displayed_content` is `True`, so the early‑return still fires and the user's `<ctrl+n>` selection / trim are
  preserved exactly as today.
- The existing regression test `test_zoom_file_show_all_survives_periodic_refresh` continues to pass: its first
  `set_file_list` proceeds (empty seed list), sets `_has_displayed_content`, and the later periodic `set_file_list`
  early‑returns (now also gated on `_has_displayed_content == True`) so the user's show‑all survives.

Together: Part 1 gives an instant, correct first paint (no flicker, no blank); Part 2 makes the panel fully functional
and resilient even if the seed capture were to break again on a future Textual upgrade.

## Files to change

- `src/sase/ace/tui/actions/agents/_panel_detail.py` — seed capture via `.content` (Part 1).
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — copy fallback via `.content`; treat empty seed content as "nothing to
  seed" in `_seed_panels()` (Part 1).
- `src/sase/ace/tui/widgets/file_panel/__init__.py` — gate `set_file_list` early‑return on `_has_displayed_content`
  (Part 2).

## Tests

Add to `tests/ace/tui/test_agents_zoom_panel.py` (and keep existing tests green):

1. **Seed paints the file panel immediately (Textual‑API regression).** Build/populate a real `AgentDetail`'s file panel
   with a diff renderable, capture a seed through the real `AgentPanelDetailMixin._zoom_seed_from_detail()`, and assert
   `seed.file_renderable` is non‑`None` (this fails today and would fail again if a future Textual renames `content`).
   Mount `ZoomPanelModal` with that seed and assert the zoom file panel shows the content **before** any `r`/force
   refresh.

2. **Completed‑agent zoom loads the file without `r`.** Seed a modal whose `file_list` already equals `agent.all_files`
   (the DONE‑agent case, on‑disk diff/extra files in `tmp_path`), `has_file_content=True`, status `DONE`. After mount +
   a couple of `pilot.pause()`s, assert the `_ZoomFilePanel` has loaded real content (`_full_content is not None` /
   visible file text), with no force refresh.

3. **`<ctrl+n>` shows the next file.** From test 2, `action_next_file()` then assert the panel renders the second file's
   content.

4. **Metadata copy fallback.** With a metadata‑only seed, assert `_zoom_text()` returns the metadata text (previously
   `None`).

5. Confirm `test_zoom_file_show_all_survives_periodic_refresh` and the other existing `test_agents_zoom_panel.py` tests
   still pass.

Also run the ACE PNG visual snapshot for the file zoom modal
(`tests/ace/tui/visual/snapshots/png/agents_file_zoom_modal_120x40.png`) and refresh the golden only if the (now
non‑empty) render is the intended visual change.

## Validation

- `just check` (lint + mypy + tests), after `just install`.
- `just test-visual` for the zoom snapshot suite; update the golden with `--sase-update-visual-snapshots` only if the
  file‑zoom modal's content is the intended change.
- Manual smoke in `sase ace`: select a completed agent, press `z` on the file panel → content appears with no `r`;
  `<ctrl+n>`/`<ctrl+p>` page files with no blank; `=`/`-` trim works; `y` copies the visible panel including metadata.

## Out of scope / notes

- No keymap, CLI option, or help‑popup changes (no user‑facing option is being added or altered), so the `?` help modal
  and footer keybinding docs do not need updates.
- No `sase-core` changes (presentation‑only).
