---
create_time: 2026-05-07
status: research
---

# Agent-Controlled ACE TUI Screenshots

## Question

How should SASE let coding agents run the `sase ace` TUI, navigate it by emulating keypresses, and save a screenshot to
a temporary image file?

## Recommendation

Build this as a SASE-owned, Textual-native automation path first, not as a tmux/PTY wrapper.

The best first implementation is a headless `AceApp.run_test()` command that:

1. Starts `AceApp` in-process with a deterministic terminal size.
2. Applies a sequence of Textual key names through `Pilot.press()`.
3. Waits for idle or explicit conditions between steps.
4. Saves a screenshot with Textual's SVG screenshot API to a file under the SASE temp directory.
5. Prints machine-readable JSON containing the screenshot path, optional plain-text screen capture, and structured TUI
   state.

This gives agents a Playwright-like "act, observe, assert" loop for SASE's own TUI while preserving access to Textual
widget state. PTY/tmux tools remain useful fallback prior art, but they are a worse default for ACE because they treat
the app as an opaque terminal stream.

## Current SASE Context

ACE is already a Textual app:

- `src/sase/ace/tui/app.py` defines `AceApp`.
- `src/sase/main/ace_handler.py` constructs `AceApp` and calls `app.run()`.
- `src/sase/main/parser_ace.py` currently treats the optional positional argument as the ACE query, so adding an `ace`
  subcommand such as `sase ace screenshot` would conflict with existing query syntax unless the parser is reworked.
- `src/sase/ace/testing.py` already wraps `AceApp.run_test()` in `AcePage`, exposes `press()`, `screen`, structured
  `state`, widget queries, and auto-retrying `expect_*` helpers.
- `tests/test_ace_testing.py`, `tests/test_keymaps_e2e.py`, `tests/test_command_palette_e2e.py`, and related tests
  already prove the repo is comfortable driving ACE through Textual Pilot rather than a real terminal.

One important correction to older research: `sdd/research/202604/tui_e2e_testing.md` described a `sase ace --agent`
mode. In the current codebase, the durable thing that exists is the Python `AcePage` testing DSL; there is no current
`sase ace --agent` CLI path in `parser_ace.py` or `ace_handler.py`.

Concrete repo facts an implementer must respect:

- `AceApp.__init__` (`src/sase/ace/tui/app.py:174`) defaults: `query="!!!"`, `model_tier_override=None`,
  `refresh_interval=10`, `auto_start_axe=True`, `restart_axe=False`. Automation must override the production-flavor
  defaults (`refresh_interval=0`, `auto_start_axe=False`) explicitly; this is not the same `AceApp` `AcePage` constructs
  even though the constructors share an interface.
- `AcePage` monkey-patches `sase.ace.changespec.find_all_changespecs` and `find_all_changespecs_cached` with fixed
  fixture data (`src/sase/ace/testing.py:148`). That is correct for tests but is the wrong default for an agent
  screenshotting a live project — production automation must drive the real ChangeSpec discovery path so the screenshot
  reflects actual project state.
- Plain-text screen capture is already factored as `_capture_screen()` and structured state extraction as
  `_extract_state()` (`src/sase/ace/testing.py:58` and `:71`). Both should be exported from a shared module so the
  test DSL and the agent CLI share one implementation rather than diverging.
- `get_sase_tmpdir()` (`src/sase/core/paths.py:32`) returns `$SASE_TMPDIR` or `None` (so callers fall back to the
  system temp dir). It does not isolate per-agent runs — callers are responsible for unique filenames.
- No `App.export_screenshot()`, `App.save_screenshot()`, or `pytest-textual-snapshot` usage exists in the repo today
  (verified by grep). `cairosvg`, `svglib`, and `reportlab` are not in `pyproject.toml`. The only image library currently
  on the dependency floor is Pillow, used by `src/sase/ace/tui/graphics/cell.py` for terminal-cell rendering, not for
  SVG rasterization. This research's "SVG-first, PNG optional" recommendation is the right shape given those facts.
- ACE already has an image surface — `94de4987` switched ACE image previews to Pillow-only via
  `src/sase/ace/tui/graphics/cell.py`, and `c306e39b` added `tools/test_image_notification`. Neither converts SVG, but
  the notification model already accepts image attachments (see "Agent Delivery Channels" below).

## External Findings

### Textual Has The Right Primitive

Textual's testing guide documents `App.run_test()` as an async context manager that runs the app headlessly and returns
a `Pilot` object for keyboard and mouse interaction. The same docs say `Pilot.press()` simulates key presses, including
non-printable key names and modifiers. The API reference also documents `run_test(size=(width, height))`, which gives
SASE deterministic screenshot dimensions.

Textual also has built-in screenshot support. `App.export_screenshot()` exports the current screen as SVG, and
`App.save_screenshot()` writes an SVG screenshot to a file. `App.action_screenshot()` and `deliver_screenshot()` are
user-facing variants of the same capability.

Implication: for SASE's own Textual TUI, the shortest correct path is not terminal scraping. It is exposing a small CLI
around the same in-process mechanism the tests already use.

### SVG Is The Native Screenshot Format

Textual screenshots are SVG, not PNG. That is acceptable as a first-class "image file" and is likely the best default:
it has no new dependencies, it preserves terminal cell geometry and colors, and it is generated directly from Textual's
current screen model.

If SASE specifically needs PNG for an agent runtime's image-viewing tool, PNG conversion should be a second layer:

- CairoSVG can convert SVG to PNG through a Python API or CLI, but it is LGPLv3 and depends on Cairo/libffi system
  packages.
- Headless Chromium/Playwright can rasterize SVG, but that brings a browser dependency for a terminal workflow.
- Pillow is already a SASE dependency, but Pillow does not render arbitrary SVG by itself.

Recommendation: ship SVG first, with a `--format png` best-effort path only if an optional converter is installed.
Keep the JSON response explicit about the actual output format.

### tmux Is Useful But Not The Default

tmux can send keys to panes and capture visible pane contents. The tmux wiki documents `send-keys` for simulating key
presses and `capture-pane -p` for printing pane content. Charmbracelet's `freeze` README shows a practical pipeline:
run a TUI in tmux, `capture-pane`, then pipe it to `freeze` to generate an image.

This is valuable for arbitrary external TUIs, but it is a weak default for ACE:

- It loses Textual widget identity and structured state.
- It depends on an external tmux server and terminal geometry.
- It captures terminal output after terminal emulation, not the actual Textual widget tree.
- It creates more process/session cleanup concerns for agents.
- It cannot reliably see Textual internals such as selected agent metadata, modal stack, current tab, or hidden state.

For SASE's own app, tmux should be a fallback or manual debugging path, not the primary automation API.

### PTY Automation Tools Are Prior Art, Not A Replacement

Several newer tools are converging on "Playwright for terminals":

- `agent-tui` is a Rust CLI/daemon for AI agents to spawn TUI apps, take snapshots, send keystrokes, wait for text or
  stable screens, and get JSON output. It uses PTY management and terminal emulation under the hood.
- Microsoft's `@microsoft/tui-test` is a TypeScript framework that uses PTY processes and xterm/headless. Its README
  highlights auto-waiting, terminal contexts, screenshots/snapshots, tracing, and text assertions.
- `pytest-textual-snapshot` can snapshot Textual apps to SVG and supports pressing keys before capture, but it is aimed
  at pytest visual regression tests, not interactive agent operation.

The design lesson is useful: agents need stable commands, JSON output, wait conditions, and screenshots. But adopting a
black-box PTY stack would duplicate what Textual already provides in-process and would make SASE agents less informed
than SASE's tests.

## CLI Surface Options

The flag-based shape (`sase ace ... --agent-screenshot`) is the least-disruptive choice, but two alternatives are
worth weighing before committing:

| Option | Pros | Cons |
| --- | --- | --- |
| `sase ace '<query>' --agent-screenshot ...` (recommended) | Reuses the existing parser, query semantics, and config plumbing; agents already know `sase ace`. | Mode flag pollutes the interactive command surface; help output gets noisier. |
| New sibling `sase ace-screenshot` (or `sase ace-shot`) | Clean separation of interactive vs. automation; no parser conflict; easy to omit interactive-only flags. | Two commands to maintain; cross-cutting flags (model tier, refresh interval) duplicated. |
| New namespace `sase tui screenshot` | Future-proof for non-ACE TUIs; matches `sase axe …` style. | Premature generalization; ACE is the only Textual TUI today. |

The flag approach is best for the first version. If automation grows enough scripted-step or daemon surface to dwarf
the interactive flags, a sibling `sase ace-screenshot` is the cleanest second step.

## Proposed Product Shape

Use a non-interactive ACE automation mode rather than a long-lived session daemon at first.

Example command shape:

```bash
sase ace '!!!' \
  --agent-screenshot \
  --keys tab,j,enter \
  --size 140x50 \
  --format svg \
  --json
```

Example JSON:

```json
{
  "image_path": "/tmp/sase/ace_screenshot_20260507_153012.svg",
  "format": "svg",
  "size": [140, 50],
  "state": {
    "tab": "agents",
    "idx": 1,
    "modal": null
  },
  "screen_path": "/tmp/sase/ace_screenshot_20260507_153012.txt",
  "error": null
}
```

Keep flags alphabetized in `parser_ace.py` if implemented there, per local convention.

Because the optional positional query makes `sase ace screenshot ...` ambiguous, the least disruptive CLI addition is
flag-based. A future parser redesign could add `sase ace agent screenshot`, but that is not necessary for the first
usable version.

## API Design Details

Add a production-facing helper separate from test-only fixtures:

- `src/sase/ace/automation.py`
  - `AceAutomationRequest`
  - `AceAutomationResult`
  - `run_ace_automation(request) -> AceAutomationResult`
- Move or share state/screen extraction from `src/sase/ace/testing.py` so tests and CLI do not drift.
- Keep `AcePage` as a test DSL over the lower-level automation primitives where practical.

Request fields:

- `query: str`
- `keys: list[str]`
- `size: tuple[int, int]`
- `format: Literal["svg", "png"]`
- `output_dir: Path | None`
- `refresh_interval: int = 0` for automation unless explicitly overridden
- `auto_start_axe: bool = False` by default for deterministic agent screenshots
- `wait: list[WaitSpec]` or a simpler global `settle: bool = True`

Result fields:

- `schema_version: int` — pin so future state changes don't silently break agent parsers.
- `image_path: str`
- `format: str`
- `size: tuple[int, int]`
- `state: dict[str, Any]`
- `screen: str | None` or `screen_path`
- `warnings: list[str]`
- `error: str | None`

The state schema today (from `_extract_state()`) includes `tab`, `idx`, `total`, `query`, `canonical_query`, `marked`,
`modal`, fold flags, and a `selected` block. Treat it as the v1 schema and freeze the existing key names; add new keys
rather than rename them.

Key parsing should accept both comma-separated strings and repeated flags:

```bash
--keys tab,j,enter
--key tab --key j --key enter
```

Textual key names should be passed through directly where possible. Avoid inventing a second key naming scheme unless
agent ergonomics prove it is needed.

## Mouse, Modifiers, And Timing Controls

`Pilot.press()` is sufficient for keyboard-driven flows, but ACE has mouse-clickable widgets (footer buttons, modal
controls, tab strip) and the existing `AcePage.click(selector)` already wraps `Pilot.click()`. The agent CLI should
accept clicks too, e.g. `--click "#footer-quit"` or as a step type in the JSON script:

```json
[{"click": "#footer-help"}, {"wait_text": "Help"}, {"press": ["escape"]}]
```

Other Textual primitives worth surfacing:

- `Pilot.press(*keys, delay=...)` for animations that need inter-key spacing.
- `Pilot.pause(delay=...)` for explicit settle windows when no specific signal is available.
- `Pilot.hover()` for tooltip-driven UI; only add if a real flow needs it.

Avoid inventing a new key alias namespace until a real agent failure proves Textual's names (`tab`, `enter`, `escape`,
`ctrl+r`, `shift+tab`, etc.) are insufficient.

## Determinism Knobs

Stable screenshots across runs and parallel agents need every nondeterministic surface pinned:

- **Theme/colors.** Force a known theme (e.g. `app.theme = "textual-dark"`) before capture; do not honor
  `$TEXTUAL_THEME` from the calling environment.
- **Animations.** Set `App.show_animations = "none"` (or pass `headless=True`-style flags exposed via `run_test`).
  Headless mode already disables most animation, but explicit is better.
- **Notifications/toasts.** Suppress notification widgets unless `--include-notifications` is passed; ACE plugins or
  background jobs may otherwise pop a toast mid-capture.
- **Cursor blink.** Disable blink so two adjacent runs produce byte-identical SVG when nothing else changed.
- **Background work.** `auto_start_axe=False` and `refresh_interval=0` together stop the periodic refresh and the
  child Axe process from racing the screenshot.
- **Locale and time.** SVG screenshots embed visible timestamps and counts; pin `TZ` / `LC_ALL` if the agent uses
  screenshots for diff-style regression checks.

## Wait Semantics

Do not rely on arbitrary sleeps as the core synchronization model.

Minimum first version:

- After all keypresses, call `Pilot.pause()` with no delay so Textual can settle to idle.
- Support `--wait-text TEXT` for common agent use.
- Support `--wait-state state.path=value` only if the parsing stays small and testable.

Better second version:

- Accept a JSON steps file:

```json
[
  {"press": ["tab"]},
  {"wait_text": "Agents"},
  {"press": ["j", "enter"]},
  {"screenshot": true}
]
```

This lets agents perform multi-step scripted exploration in one process without a daemon. A true persistent session
daemon can come later if agents repeatedly need interactive round trips across separate shell commands.

## Temporary File Handling

Use SASE's existing temp directory helper (`get_sase_tmpdir`) rather than raw `/tmp` when possible. Include timestamp
and a short random suffix to avoid collisions across parallel agents.

Suggested files:

- `ace_screenshot_<timestamp>_<suffix>.svg`
- `ace_screenshot_<timestamp>_<suffix>.png` only when conversion succeeds
- `ace_screenshot_<timestamp>_<suffix>.txt` for plain screen text when requested
- `ace_screenshot_<timestamp>_<suffix>.json` only if a caller asks to persist the full result

Screenshots should be best-effort artifacts, not durable project files.

### Concurrency And Parallel Agents

Multiple SASE agents can run concurrently in `sase_<N>` workspaces, and each one may take screenshots. The temp dir
(`get_sase_tmpdir()`) is shared, not per-workspace, so:

- Always include a short random suffix alongside the timestamp to avoid same-second collisions.
- Optionally honor a `SASE_AGENT_ID` / workspace-scoped subdir (e.g. `<tmp>/ace_screenshots/<workspace>/`) so cleanup
  scripts can sweep one agent's artifacts without touching another's.
- Do not assume the SVG file outlives the calling process — return paths relative to a stable namespace if the agent
  runtime needs them later, or attach them through `sase notify create` to persist into `~/.sase/notifications/`.

## Agent Delivery Channels

A screenshot file is only useful if it actually reaches the agent or human reading the output. SASE already has two
viable delivery surfaces, neither of which the original draft called out:

- **Notification system.** `Notification` (`src/sase/notifications/models.py`) carries a `files: list[str]` field, and
  `tools/test_image_notification` already demonstrates calling `sase notify create` with an image attachment. An
  `--notify` flag on the screenshot command (or a default for headless runs) would surface the screenshot in the
  user's notification inbox and any mobile/Telegram notifier without a new IPC channel.
- **Stdout JSON contract.** Returning the SVG path on stdout is enough for a host agent runtime that knows how to
  attach local files to its next user turn. The skill/xprompt that wraps the command is responsible for telling the
  runtime to read or display the file; the CLI should not assume runtime-specific image upload.

For SASE's own agent runtimes (Claude Code, Gemini, Codex), the typical pattern is: the agent runs the CLI, parses
the JSON, and either reads the file directly (if it can ingest images) or relies on the plain-text `screen` field as
a fallback. Treat the image as the primary artifact and the `screen` text as the universal fallback.

## Keymap Self-Discovery

Agents need to know which keys to press without reading source. ACE's bindings live in two places:

- `default_config.yml` (root config) — declarative per-mode keymap.
- `src/sase/ace/tui/keymaps/` — typed registry (`AppKeymaps`, `_BINDING_META`) with `(action_name, description,
  priority)` entries; loaded via `load_keymap_registry()`.

A small companion command — `sase ace --list-bindings --json` — that dumps `{action, keys, description, scope}` would
let agents introspect the current keymap rather than hard-coding string sequences. Without it, agents will silently
break the first time a user customizes a binding. This is cheap to add alongside the screenshot CLI and amortizes
the parser-change cost.

## PNG Conversion Strategy

Make `svg` the default and implement `png` as optional.

Recommended order for `--format png`:

1. Save the SVG with Textual.
2. If `cairosvg` is importable, call `cairosvg.svg2png(url=svg_path, write_to=png_path)`.
3. Else if `rsvg-convert` or another configured converter exists, shell out to it.
4. Else return a non-fatal warning and the SVG path unless the user passed `--require-format png`.

This avoids making Cairo a mandatory dependency of the core TUI. It also keeps the implementation honest: Textual
captures SVG; rasterization is an adapter.

## Why Not A Browser Or Desktop Screenshot?

A browser-style screenshot is the wrong abstraction for a terminal-native Textual app. It would require launching a
terminal emulator or `textual-serve`-style web surface, then using Playwright or desktop automation to screenshot that
surface. That adds fragile environment assumptions and loses the direct app state that Textual already exposes.

The only reason to add a browser rasterization path is PNG conversion, and even then it should be an optional converter
behind the Textual SVG capture.

## Related SASE Research

- `sdd/research/202604/tui_e2e_testing.md` — earlier exploration that proposed the `sase ace --agent` mode; useful
  background but its CLI proposal predates the current `parser_ace.py` shape and the `AcePage` test DSL.
- `sdd/research/202604/tui_image_pdf_support.md` — image rendering inside the TUI; tangential but relevant if PNG
  output ever needs to be re-rendered as a TUI preview.
- `sdd/research/202605/textual_image_rendering_research.md` — current state of Textual image surfaces; informs the
  Pillow/SVG dependency posture.
- `sdd/research/202604/tui_profiling_strategies.md` — profiling hooks that may interact with `refresh_interval=0`
  automation runs.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Textual screenshot includes cursor/blink or transient notifications | Disable notifications in `run_test()` unless requested; call `Pilot.pause()` before capture. |
| Automation accidentally starts Axe or mutates live state | Default `auto_start_axe=False`, `refresh_interval=0`, and document side effects of keys that trigger real actions. |
| Agents need iterative exploration across shell commands | Add JSON step scripts first; only build a daemon if this proves insufficient. |
| PNG support adds heavy native dependencies | Keep SVG as default; make PNG optional and explicit. |
| State extraction drifts from TUI changes | Share extraction helpers between `AcePage` and the CLI; cover result schema with tests. |
| Key names differ between agent expectations and Textual names | Document `textual keys` names; support small aliases only after real failures. |

## Implementation Plan

1. Extract `_capture_screen()` and `_extract_state()` from `src/sase/ace/testing.py` into a shared module
   (`src/sase/ace/automation.py` or `src/sase/ace/state.py`) so the test DSL and the agent CLI consume identical
   logic. Delete the test-only copies.
2. Add `run_ace_automation()` that constructs `AceApp(refresh_interval=0, auto_start_axe=False, ...)`, runs
   `app.run_test(size=...)`, applies determinism knobs (theme, animations, notifications), presses keys, waits, calls
   `app.save_screenshot(path)`, captures state/screen, and returns a versioned dataclass result.
3. Add flag-based CLI support in `parser_ace.py` (alphabetized) and branch in `ace_handler.py` before `app.run()`.
   Keep the interactive default behavior unchanged.
4. Use `get_sase_tmpdir()` for default output paths; include a workspace-scoped subdir + random suffix for parallel
   safety.
5. Add `sase ace --list-bindings --json` (or equivalent) so agents can self-discover key bindings instead of
   hard-coding them.
6. Add tests for:
   - keypress navigation writes a screenshot file;
   - JSON result includes state, schema_version, and path;
   - invalid key returns a useful error;
   - `--format png` degrades gracefully when no converter is installed;
   - `--wait-text` succeeds and times out deterministically;
   - parallel invocations (two `run_ace_automation()` calls) write to distinct paths;
   - bindings listing matches the active keymap registry.

## Open Questions

- Do SASE's target agent runtimes accept local SVG image attachments, or do they require PNG/JPEG? If any runtime needs
  raster images, make `--format png --require-format png` part of that runtime's local skill/instructions rather than
  changing the default.
- Should screenshots include notification toasts? For debugging user-visible flows, yes; for deterministic agent
  reasoning, no.
- Should the command return the plain-text screen inline by default? Inline text helps agents that cannot open images,
  but it can make command output noisy. A good compromise is JSON with `screen_path` by default and `--include-screen`
  for inline text.

## Sources

- Textual testing guide: https://textual.textualize.io/guide/testing/
- Textual `Pilot` API: https://textual.textualize.io/api/pilot/
- Textual `App` API (`run_test`, `export_screenshot`, `save_screenshot`):
  https://textual.textualize.io/api/app/
- pytest-textual-snapshot: https://pypi.org/project/pytest-textual-snapshot/
- tmux advanced use (`send-keys`, `capture-pane`): https://github.com/tmux/tmux/wiki/Advanced-Use
- Charmbracelet Freeze TUI screenshot note: https://github.com/charmbracelet/freeze
- CairoSVG documentation: https://cairosvg.org/documentation/index.html
- agent-tui docs.rs package page: https://docs.rs/crate/agent-tui/0.3.4
- Microsoft tui-test README: https://github.com/microsoft/tui-test
- Charmbracelet VHS (terminal "tape" automation prior art for the JSON step format):
  https://github.com/charmbracelet/vhs
