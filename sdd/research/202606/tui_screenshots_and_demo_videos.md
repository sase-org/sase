---
create_time: 2026-06-11
status: research
---

# TUI Screenshots and Demo Videos

## Question

How should SASE capture high-quality screenshots of the ACE TUI and create demo videos that show how SASE works?

## Recommendation

Use a three-lane media workflow:

1. **Static screenshots and bug evidence:** use SASE's existing Textual-native SVG and PNG pipeline. It is already
   deterministic, headless, and close to the app internals.
2. **Repeatable product/demo clips:** use Charm VHS tape scripts for polished terminal videos. VHS turns terminal actions
   into code, supports GIF/MP4/WebM outputs, can capture PNG screenshots, and can hide setup/cleanup commands.
3. **Narrated walkthroughs:** use OBS or a browser-hosted Textual session for human-guided videos where voiceover,
   window compositing, or live explanation matters more than byte-for-byte repeatability.

Keep asciinema as the lightweight documentation/archive lane: it is excellent for small, text-native terminal recordings
and embeddable casts, but it is not the best first choice for polished SASE launch media.

## Current SASE Context

SASE already has more capture infrastructure than the older May research implied:

- `AcePage.export_svg()` exposes Textual's `export_screenshot()` through the in-process test DSL
  (`src/sase/ace/testing/__init__.py:207`).
- Agents-tab repro capture writes plain text plus `screen.svg` through Textual screenshot export
  (`src/sase/ace/tui/repro/capture.py:457`).
- `sase repro replay ... --write-artifacts <dir>` writes replay screen and screenshot artifacts
  (`src/sase/ace/tui/repro/cli.py:42`, `src/sase/main/parser_repro.py:74`).
- The PNG visual suite rasterizes SVG with CairoSVG (`tests/ace/tui/visual/png_diff.py:146`) and pins fontconfig/Fira
  Code for stable glyph metrics (`tests/ace/tui/visual/conftest.py:14`).
- The `visual` extra already includes `cairosvg>=2.7,<3`, and `terminal-smoke` includes `pexpect` and `pyte`
  (`pyproject.toml:73`).
- `just test-visual` is the dedicated PNG snapshot lane (`Justfile:202`), and the local memory instructions say markdown
  files under `sdd/research/` do not require `just check`.

Local PATH check in this workspace:

| Tool | Installed here? | Note |
| --- | --- | --- |
| `ffmpeg` | yes | Needed by most video pipelines. |
| `tmux` | yes | Useful fallback for manual capture and scripted panes. |
| `textual` | yes | Required for Textual devtools and `textual serve`. |
| `vhs` | no | Best candidate for repeatable demo clips. |
| `freeze` | no | Useful for one-off terminal screenshots from ANSI output. |
| `asciinema` | no | Good lightweight terminal recording format. |
| `agg` | no | Converts asciinema casts to GIF. |
| `ttyd` | no | Required by VHS unless using Docker; also useful for browser terminal demos. |
| `obs` | no | Best free/open human-narrated recording tool. |

## Lane 1: Textual-Native Static Screenshots

Textual is the right primitive for deterministic stills because ACE is a Textual app. Textual documents `run_test()` as
a headless context that returns a `Pilot` for keyboard and mouse interaction, and `save_screenshot()` saves SVG
screenshots of the current screen. Sources: [Textual testing guide](https://textual.textualize.io/guide/testing/) and
[Textual App API](https://textual.textualize.io/api/app/).

Best uses:

- README/docs screenshots.
- Visual evidence attached to bugs and SDD research.
- Regression fixtures where the captured state should be deterministic.
- Agent-readable visual artifacts generated without a desktop session.

Current usable command for repro evidence:

```bash
sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json \
  --assert-stable \
  --json \
  --write-artifacts /tmp/sase-agents-tab-repro-artifacts
```

This writes one text screen dump and one SVG screenshot per replay step, according to `tests/ace/tui/repro/README.md`.

Useful next implementation:

- Add a small production-oriented `sase ace screenshot` or `sase media screenshot` wrapper around the existing
  Textual-native path.
- Let it choose between fixture/demo data and live project data explicitly.
- Emit both SVG and PNG, reusing the existing CairoSVG renderer and pinned-font approach rather than inventing a second
  rasterization pipeline.

Important caveat: `AcePage` is a test DSL and currently patches ChangeSpec discovery to deterministic fixture data. That
is useful for docs and tests, but a live product screenshot command should drive production data intentionally, with a
separate `--demo-fixture` mode for sanitized examples.

## Lane 2: VHS for Repeatable Demo Clips

Charm VHS is the strongest fit for reusable SASE demos. Its README describes it as writing terminal GIFs as code for
integration testing and demos. Tape files set terminal width/height, font size, theme, typing speed, waits, screenshots,
and output formats. It supports multiple outputs such as GIF, MP4, WebM, and a PNG frame directory, plus a `Screenshot`
command for a PNG of the current frame. It also supports `Wait`, `Hide`, `Show`, and `Require`, which are exactly the
controls needed for stable demos. Source: [Charm VHS README](https://github.com/charmbracelet/vhs).

Best uses:

- README and homepage clips.
- Short social/demo videos where the exact flow should be repeatable.
- "SASE in 30 seconds" scenarios with scripted setup and sanitized state.
- CI-regenerated media, if the project decides to commit tape files and rendered artifacts.

Why it fits SASE:

- Demo scripts can live in the repo as reviewable `.tape` files.
- Hidden setup commands can create a clean temporary SASE home/project, then show only the user-facing interaction.
- `Wait+Screen /.../` is better than blind sleeps when the TUI needs time to load agents or background status.
- `Screenshot path.png` can produce stills from the same scene used for the video.

Example shape:

```text
Output docs/media/sase_agents_tab.mp4
Output docs/media/sase_agents_tab.gif

Require sase
Set Shell "bash"
Set FontSize 22
Set Width 1280
Set Height 720
Set Theme "Catppuccin Frappe"
Set TypingSpeed 35ms

Hide
Type "export SASE_HOME=/tmp/sase-demo-home"
Enter
Type "sase demo seed agents-tab && clear"
Enter
Show

Type "sase ace"
Enter
Wait+Screen /Agents/
Sleep 1s
Tab
Wait+Screen /RUNNING|DONE|FAILED/
Screenshot docs/media/sase_agents_tab.png
Sleep 2s
Ctrl+C
```

Dependencies to plan for:

- VHS requires `ttyd` and `ffmpeg` on PATH, or the official Docker image can run with dependencies included.
- This workspace already has `ffmpeg` but not `vhs` or `ttyd`.

## Lane 3: Asciinema for Lightweight Terminal Casts

Asciinema records terminal output into lightweight `.cast` files rather than heavyweight video. Its docs describe
recording with `asciinema rec demo.cast`, replaying locally, embedding with the player, and optional upload/self-hosting.
The `agg` tool converts asciicast files to animated GIF. Sources:
[asciinema CLI docs](https://docs.asciinema.org/manual/cli/),
[asciinema quick start](https://docs.asciinema.org/manual/cli/quick-start/), and
[agg docs](https://docs.asciinema.org/manual/agg/).

Best uses:

- Longer technical walkthroughs where text fidelity and small file size matter.
- Docs pages that can embed an interactive terminal player.
- Low-friction capture during development.

Weaknesses for launch media:

- It is a terminal event recording, not a composed product video.
- It has no voiceover or browser/window composition.
- Visual polish depends on the player and terminal dimensions.
- The docs recommend replaying in a terminal at least as large as the recording size, which matters for full-screen TUIs.

Recommended role: keep as an optional archival/docs format, not the primary launch-video pipeline.

## Lane 4: Browser-Hosted or Human-Narrated Recording

For narrated demos, use a conventional screen recorder. OBS is free/open source and built for video recording and live
streaming on Windows, macOS, and Linux. It supports scenes with window capture, browser windows, images, text, webcams,
and audio sources. Source: [OBS Studio](https://obsproject.com/).

Two useful SASE patterns:

1. **Terminal window recording:** run `sase ace` in a clean terminal profile and record only that window.
2. **Browser-hosted TUI recording:** use Textual devtools to serve the app in a browser, then record the browser window.
   Textual documents `textual serve "textual keys"` and other commands for serving apps in a browser. Source:
   [Textual devtools](https://textual.textualize.io/guide/devtools/).

Browser-hosted recording can produce cleaner capture boundaries and makes it easier to use browser/video tooling. Be
careful with exposure: `textual-web -t` can serve a terminal through a random public URL, and its README explicitly warns
not to share that URL with anyone you would not trust with machine access. Sources:
[textual-web README](https://github.com/textualize/textual-web) and [ttyd README](https://github.com/tsl0922/ttyd).

## One-Off Terminal Screenshots

Charm Freeze is useful when the source is a command's ANSI output or a captured pane, not a live interactive app. It can
generate PNG, SVG, and WebP images of code or terminal output, and can run a command with `--execute`. Source:
[Charm Freeze README](https://github.com/charmbracelet/freeze).

Recommended role:

- Good for static command examples and log snippets.
- Useful with `tmux capture-pane` when you want a quick image of the current terminal contents.
- Not the first choice for full-screen ACE screenshots because Textual already exports SVG directly and SASE already has
  a PNG rasterization lane.

## Lower-Priority Option: Terminalizer

Terminalizer records terminal sessions to YAML, can replay them, and renders GIF output. Its README also says GIF
compression is not implemented and recommends an external compressor. Source:
[Terminalizer README](https://github.com/faressoft/terminalizer).

Recommended role: do not start here. VHS gives SASE more useful scripting controls, output formats, waits, screenshots,
and setup hiding for demos-as-code.

## Demo Hygiene

SASE demos can leak useful but private context unless capture is deliberately isolated. Use these rules for every public
or semi-public artifact:

- Capture from a fresh temporary `SASE_HOME` or a committed demo fixture, not Bryan's live home/project state.
- Use commit-safe repro bundles when sharing bug evidence.
- Redact or synthesize project names, branch names, prompts, chat snippets, file paths, and notification text.
- Pin terminal size, theme, font, and font size for every screenshot/video.
- Disable desktop notifications and avoid full-desktop capture.
- Prefer MP4/WebM for videos and GIF only for README/social fallbacks.
- Keep source scripts (`.tape`, seed commands, fixture bundles) in repo so demos can be regenerated after UI changes.

## Proposed Near-Term Plan

1. Add a `tools/demo/` or `docs/demo/` directory with one small demo data seeder and one VHS `.tape` file.
2. Add a SASE CLI screenshot wrapper that can write `svg`, `png`, and `json` metadata from a chosen ACE state.
3. Reuse existing CairoSVG/fontconfig conventions for PNG output.
4. Render one canonical Agents-tab still, one Changespec-tab still, and one 20-30 second VHS clip.
5. Use OBS only for the longer narrated "what is SASE?" walkthrough after the scripted clips exist.

## Sources

- Textual App API: <https://textual.textualize.io/api/app/>
- Textual testing guide: <https://textual.textualize.io/guide/testing/>
- Textual devtools serve docs: <https://textual.textualize.io/guide/devtools/>
- pytest-textual-snapshot: <https://github.com/Textualize/pytest-textual-snapshot>
- Charm VHS: <https://github.com/charmbracelet/vhs>
- Charm Freeze: <https://github.com/charmbracelet/freeze>
- asciinema CLI: <https://docs.asciinema.org/manual/cli/>
- asciinema quick start: <https://docs.asciinema.org/manual/cli/quick-start/>
- agg: <https://docs.asciinema.org/manual/agg/>
- textual-web: <https://github.com/textualize/textual-web>
- ttyd: <https://github.com/tsl0922/ttyd>
- OBS Studio: <https://obsproject.com/>
- Terminalizer: <https://github.com/faressoft/terminalizer>
