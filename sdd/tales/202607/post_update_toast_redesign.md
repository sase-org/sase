---
create_time: 2026-07-01 07:25:18
status: done
---
# Plan: Redesign the post-update confirmation toast

## Goal

Make the toast that ACE shows right after a `sase` self-update **intuitive, reliable, and beautiful**. Today the toast
crams the file-change summary against the version line and can wrap mid-diffstat, which reads as "mangled." We will
restructure the layout, guarantee it never wraps on realistic content, and — importantly — fix the fact that the toast's
own visual regression test never actually renders the toast.

## Current behavior (what's wrong)

The post-update toast is built in `src/sase/ace/tui/actions/post_update_toast.py`. For a real dev self-update (single
`sase` repo), it renders:

```
✓ Updated to sase 0.6.1+43.g937278ecb          ← title
sase  0.6.1+41.g26e9d358d → 0.6.1+43.g937278ecb   +171 −26     ← primary line (58 cols)
8 files changed · Reloaded into the new version.               ← tail line
```

Textual's `Toast` is `width: 60` with `padding: 1 1` + a left border, so the usable content width is only **~57
columns**. The primary line above is **58 columns**, so `−26` wraps onto its own line, and the dim tail ("8 files
changed · Reloaded …") then butts right up against it with no separation. Verified by rendering
`_format_post_update_toast_message` directly on the screenshot's receipt.

Two distinct defects:

1. **Wrap:** long dev version strings (`0.6.1+41.g26e9d358d`, from `git describe`) plus the inline `+ins −del` diffstat
   overflow the ~57-col budget and wrap uglily.
2. **No breathing room:** the summary/reassurance tail sits directly under the (wrapped) diffstat, so the "file change
   summary is mangled with the rest of the toast message" (the reported symptom).

### Reliability gap discovered while investigating

The toast has visual snapshot tests (`tests/ace/tui/visual/test_ace_png_snapshots_post_update_toast.py`) and golden PNGs
(`tests/ace/tui/visual/snapshots/png/post_update_toast*.png`) — **but the goldens do not contain the toast at all.**
Root cause: `AcePage` (`src/sase/ace/testing/__init__.py`) calls `self._app.run_test(size=...)`, and Textual's
`run_test` defaults `notifications=False`, which sets `app._disable_notifications = True`. With notifications disabled
the `Screen` never inserts a `ToastRack`, so no `Toast` widget is ever mounted; the SVG/PNG export captures a normal ACE
screen with no toast. Verified empirically: the notification object exists (`_notifications == 1`) but
`screen.query(Toast) == 0`, and the exported SVG contains neither "Updated to" nor "Reloaded". This means the current
tests are a **false guard** — they cannot catch any regression (or improvement) in how the toast actually looks. Also
verified: passing `notifications=True` to `run_test` mounts the toast and it appears in the SVG, and a blank line
(`\n\n`) renders as a real empty row inside the toast.

## Design

Keep the strong parts of the current toast — the ✓ success glyph, the "Updated to sase `<new>`" title, the
accent-colored package name, the `old → new` transition, and the green/red diffstat — and fix the layout so it always
breathes and never wraps.

### Principles

- **A toast is glanceable.** Priority: (1) it succeeded, (2) the new version, (3) roughly how big the change was, (4)
  reassurance that ACE reloaded. Full detail lives in the Updates tab.
- **Never wrap on realistic content.** The layout must be robust to long `git describe` dev versions, not just short
  semver.
- **Clear vertical zones.** Separate "what changed" from the "reloaded" reassurance with real whitespace.

### Target layout

Three visual zones separated by blank lines. The primary repo is the hero (bold, accent name, no bullet); plugins are
compact bulleted rows; the tail is dim (de-emphasized roll-up).

**Dev self-update (the screenshot case — single repo, has churn):**

```
✓ Updated to sase 0.6.1+43.g937278ecb        ← title (unchanged)

sase  0.6.1+41.g26e9d358d → 0.6.1+43.g937278ecb
      +171  −26

8 files changed · Reloaded into the new version.
```

**Managed update (short semver, plugins, no churn):**

```
✓ Updated to sase 0.6.0

sase           0.5.0 → 0.6.0
• sase-github   1.2.0 → 1.3.0
• sase-telegram 0.5.0 → 0.6.0

+2 dependencies · Reloaded into the new version.
```

**Dev multi-repo (rare):** primary churn stacked; compact plugins keep churn inline; tail rolls up.

```
sase           0.5.0+1.gabc123def → 0.5.0+2.gdef456abc
               +1,234  −567
• sase-github   1.2.0 → 1.3.0   +42 −7
• sase-telegram 0.5.0 → 0.6.0   1 file
…and 2 more                     +80 −11

16 files changed · +2 dependencies · Reloaded into the new version.
```

### The three concrete changes to the layout

1. **Stack the primary repo's churn onto its own line**, indented to align under the version column (indent =
   `name_width + 2`). This is the key wrap fix: the primary transition line is now just `name  old → new` (reliably fits
   ~57 cols even with long dev versions and a widened toast), and its `+ins −del` / `N files` sits on the next line. The
   wide `name → new  +ins −del` line that overflowed is eliminated. Plugin/overflow rows keep churn inline (short
   semver + small churn fit comfortably), preserving compactness in the multi-repo case.
   - Optional flourish to make the stacked churn read as "stats for this bump": prefix it with a dim `↳ `. Decide during
     implementation against the live snapshot; default to plain aligned indentation if it looks busy.

2. **Insert a blank line between the transition block and the tail line.** This is the direct fix for the reported "add
   some blank space." The dim tail (`[N files changed · ][+K dependencies · ]Reloaded into the new version.`) keeps its
   current content — the files-changed grand total stays meaningful as a cross-repo roll-up, complementary to the
   per-repo line churn.

3. **Give the ACE toast a little more room and let it size to content.** Add a scoped Textual CSS rule for `Toast` in
   `src/sase/ace/tui/styles.tcss` so long transition lines have headroom while short toasts stay tight (e.g.
   `width: auto; min-width: ~44; max-width: ~72`, tuned against the snapshot; this also nudges the startup "Updates
   available" toast to a consistent width). This is a safety margin on top of change (1), not the primary fix — the
   layout must still look right at the default ~57-col width.

The managed path currently reuses "legacy" rendering when there is no diffstat
(`_format_legacy_post_update_toast_message`). Both the diffstat and non-diffstat paths must get the blank-line separator
before the tail so every variant breathes.

## Implementation outline

All changes are presentation-only ACE/TUI code (no Rust core boundary crossing; no CLI/web surface; no new config keys —
`ace.updates.*` in `src/sase/default_config.yml` is unchanged).

1. **`src/sase/ace/tui/actions/post_update_toast.py`** — the layout rewrite:
   - Add the blank line before the tail in **both** `_format_diffstat_post_update_toast_message` and
     `_format_legacy_post_update_toast_message` (join transition-block lines, append `""`, append the tail).
   - In the diffstat path, split the **primary** transition into two lines: the `name  old → new` line (no inline churn)
     plus an aligned churn line built from `_diffstat_markup(...)`, indented by the version-column offset. Keep
     plugin/overflow rows as they are (inline churn). Update the alignment helpers (`_diffstat_transition_line`,
     prefix-width math) accordingly.
   - Keep the accent/color scheme (`center_tab_accent("updates")`, `+green` / `−#D75F5F`, dim tail).

2. **`src/sase/ace/tui/styles.tcss`** — add the scoped `Toast` width rule near the existing `ToastRack` block; tune
   `min/max-width` against the regenerated snapshot.

3. **Reliability: make the visual test actually render the toast**
   - **`src/sase/ace/testing/__init__.py`** — add a `notifications: bool = False` parameter to `AcePage.__init__` and
     thread it into both `run_test(...)` call sites (`run_test(size=self._size, notifications=self._notifications)`).
     Default `False` preserves every existing snapshot; only the toast tests opt in.
   - **`tests/ace/tui/visual/test_ace_png_snapshots_post_update_toast.py`** — construct
     `AcePage(..., notifications=True)` in both toast snapshots, and add a wait for the `Toast` widget to mount
     (`screen.query(Toast)`), not just for `_notifications` to be non-empty.
   - Regenerate the two goldens with `just test-visual --sase-update-visual-snapshots` so they show the real, redesigned
     toast, then eyeball the PNGs to confirm the design looks right (no wrap, clear blank line, aligned churn).

4. **Unit tests: `tests/ace/tui/test_post_update_toast.py`** — update assertions for the new structure: assert the
   blank-line separator exists before the tail; assert the primary churn is on its own line (not inline with the
   version). Keep the existing content assertions (version strings, `+2 dependencies`, `Reloaded into the new version.`,
   `…and 2 more`, per-repo `+ins`/`−del`). Consider adding a focused case for the exact screenshot receipt (single dev
   repo, `+171 −26`, 8 files) that asserts no rendered line exceeds the content-width budget.

5. **Docs/config sync:** none required — no keybindings or `ace` options change (so no help-modal or
   `default_config.yml` update per the ACE guidelines); the toast text is not referenced by the help popup.

## Testing & acceptance

- `just install` then `just check` (lint + mypy + fast tests).
- `just test-visual` passes with regenerated goldens that **visibly contain** the redesigned toast.
- Manual acceptance against the reported case: the single-repo dev receipt renders with the version bump on one line,
  `+171 −26` on its own aligned line, a blank line, then the dim "N files changed · Reloaded into the new version." tail
  — no wrapping, no crammed lines.

## Out of scope / non-goals

- No changes to when/whether the toast fires, its 10s timeout, or the `ace.updates.*` config surface.
- No changes to the receipt schema (`update_receipt.py`) or the dev/managed update pipelines.
- No new runtime-specific behavior; rendering stays uniform across agent runtimes.

```

```
