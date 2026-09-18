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

- Capture after a TUI code, styling, layout, state, navigation, refresh, or screenshot
  export change when text logs do not prove the visible result. Live captures complement
  the golden visual lane: use them for real workflow confidence and debugging, then rely
  on approved visual snapshots for deterministic regression coverage.
- `sase screenshot -o /tmp/shot.png` captures a fresh local TUI window. Add repeatable
  `-p/--press` keys and `-w/--wait-for` regexes for setup flows, for example
  `sase screenshot -o /tmp/agents.png -p tab -w "Agents|Loading" -- -t axe`.
- Use `--keep` for iterative inspection. Capture once with
  `sase screenshot --keep -o /tmp/one.png`, copy the printed `sase_tmux_target=...`,
  drive that exact target with `tmux send-keys -t <target> ...`, then recapture with
  `sase screenshot --window <target> -o /tmp/two.png`. The target is the owned tmux
  window identity; prefer it over the display name when driving or cleaning up.
- Use `--host <alias-or-ssh>` to run the SVG capture on a remote machine and rasterize
  the PNG locally. Remote captures show that machine's installed `sase`, not local
  uncommitted changes. Check the printed `remote_sase_version=` before trusting a remote
  workflow result.
- Use `--svg` only when the SVG artifact is the desired output or when composing a
  transport leg; ordinary agent visual checks should inspect the final PNG.

The command prints machine-readable `key=value` lines such as `png=`, `svg=`,
`sase_tmux_target=`, `sase_tmux_window=`, `sase_screenshot_dir=`, and
`remote_sase_version=`. Prefer those keys over prose parsing. Inspect the PNG itself,
not just its signature or existence.

Live captures include real timestamps, running procs, and host state. Assert stable
layout, focus, and visible behavior, but do not treat live PNG bytes as deterministic
goldens unless the fixture controls time and data.

## Troubleshooting

- Missing visual extra: install the project visual dependencies; the screenshot command
  should report an actionable renderer/import error rather than falling back to a second
  renderer.
- Missing tmux or launch timeout: use a private tmux socket for tests, remove only
  test-owned windows, and keep the overall screenshot timeout bounded. Failure messages
  should include the last known pane text when available.
- Old remote `sase`: the remote host must have the screenshot contract installed. If
  `remote_sase_version=` is absent or too old, verify the shell transport regressions
  locally and do not assume local uncommitted changes exist on the remote.
- Settling timeout: wait for a meaningful visual state with `-w/--wait-for` and a
  delayed interaction. Do not paper over recurring background refreshes with unbounded
  waits or broad reloads.

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
