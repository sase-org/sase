---
type: reference
parent: sase/memory/tui.md
description:
  Read before using or changing `sase screenshot`, live TUI SVG export, or TUI PNG
  visual snapshot capture.
---

# TUI Screenshot Capture

Use `sase screenshot` when an agent needs a PNG of the real `sase tui` state that a user
would see. The command launches or reuses a tmux-backed TUI, drives optional keypresses
and waits, asks the live app to export an SVG, then rasterizes that SVG with the
project-canonical TUI visual renderer.

## Agent Workflow

- `sase screenshot -o /tmp/shot.png` captures a fresh local TUI window.
- Add repeatable `-p/--press` keys and `-w/--wait-for` regexes for simple setup flows.
- Use `--keep` when you want to keep driving the launched window by hand with tmux, then
  capture the same process later with `--window <target>`.
- Use `--host <alias-or-ssh>` to run the SVG capture on a remote machine and rasterize
  the PNG locally. Remote captures show that machine's installed `sase`, not local
  uncommitted changes.
- Use `--svg` only when the SVG artifact is the desired output or when composing a
  transport leg; ordinary agent visual checks should inspect the final PNG.

The command prints machine-readable `key=value` lines such as `png=`, `svg=`,
`sase_tmux_window=`, and `sase_screenshot_dir=`. Prefer those keys over prose parsing.

## Implementation Rules

- The live app export path is externally triggered through `SIGUSR2` and
  `SASE_TUI_SCREENSHOT_DIR`. Keep the signal handler and any Textual pump callbacks
  thin; slow work belongs outside the event loop and outside Textual's serial pump.
- Screenshot request directories contain sequence-numbered `screen_<N>.svg` files plus a
  matching `.done` or `.error` marker. Write response files atomically so polling
  callers never consume partial SVG output.
- Rasterization uses `sase.ace.tui.visual_render.render_svg_to_png()` and the bundled
  Fira Code fonts. Do not fork a second renderer for agent screenshots or visual
  snapshots.
- Visual snapshot goldens live under `tests/ace/tui/visual/snapshots/png/`. Update them
  only for intentional visual changes, after inspecting the actual rendered diff.

Read [[tui_perf.md]] before changing the screenshot export handler, wait/settle logic,
refresh scheduling, or any TUI path that runs while the app is interactive.
