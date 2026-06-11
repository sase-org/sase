---
create_time: 2026-06-11
status: research
---

# TUI Screenshots and Demo Videos

Consolidated from two independent research passes on the same question (2026-06-11).

## Question

How should SASE capture high-quality screenshots of the ACE TUI and create demo videos/GIFs that show people how sase
works — for the README, docs, and sharing?

## Recommendation

Use a four-lane media workflow:

1. **Static screenshots:** reuse the existing Textual-native SVG/PNG visual snapshot machinery via a small standalone
   script. Deterministic, headless, regenerable, and leaks no real project data. Commit SVGs as well as PNGs — GitHub
   renders SVG natively in READMEs and it is Textual's highest-fidelity output.
2. **Repeatable demo clips (README/docs):** Charm VHS `.tape` scripts committed to the repo — demos-as-code,
   regenerated whenever the TUI changes, output MP4 + GIF.
3. **Long-form/lightweight casts:** asciinema 3.x recordings embedded via the SVG-preview-link pattern, rendered to
   GIF with agg when needed.
4. **Narrated walkthroughs:** OBS (or a browser-hosted Textual session) for human-guided videos with voiceover.

Skip terminalizer, ttygif, svg-term-cli, and termtosvg — all stale or dead as of June 2026.

## What the Repo Already Provides

The PNG visual snapshot suite is effectively a production-ready screenshot factory; it already solves deterministic
rendering, fonts, and app-state seeding:

- **SVG export:** `AcePage.export_svg()` (`src/sase/ace/testing/__init__.py:207`) exposes Textual's
  `export_screenshot()` through the in-process test DSL. Textual renders via its own compositor, so output is
  pixel-perfect regardless of terminal emulator.
- **SVG → PNG:** `render_svg_to_png()` (`tests/ace/tui/visual/png_diff.py:146`) via CairoSVG; the `visual` extra pins
  `cairosvg>=2.7,<3` (`pyproject.toml:74`).
- **Deterministic app state:** `AcePage` wraps `AceApp.run_test(size=...)` (headless Pilot), and
  `tests/ace/tui/visual/_ace_png_snapshot_helpers.py` provides realistic mock data (`changespecs()`, `agents()`,
  `project_records()`, `axe_collected_data()`), `patch_startup_loaders()` to swap background loaders for mocks, and
  `wait_for_startup()` / `wait_for_visual_idle()` to settle layout before capture.
- **Hermetic rendering:** `tests/ace/tui/visual/conftest.py` pins bundled Fira Code via fontconfig, forces color, and
  pins the PID for byte-identical output. `just test-visual` is the dedicated snapshot lane (`Justfile:202`).
- **Existing goldens:** `tests/ace/tui/visual/snapshots/png/` holds 30 representative 120x40 shots
  (`changespec_initial_120x40.png`, `agents_list_120x40.png`, ...) — usable demo material today.
- **Repro evidence capture:** the Agents-tab repro harness writes a text screen dump plus `screen.svg` per replay step
  (`src/sase/ace/tui/repro/capture.py:469`) via
  `sase repro replay <fixture> --assert-stable --json --write-artifacts <dir>` (`src/sase/main/parser_repro.py:75`).

There is no screenshot CLI command and no asciinema/VHS/demo-video infrastructure yet; the README has a single static
image (`docs/images/sase_overview.png`). Prior related research: `sdd/research/202605/tui_pixel_snapshot_testing.md`
(the snapshot-suite epic), `sdd/research/202605/tui_agent_screenshot_automation.md`, and
`sdd/research/202605/textual_serve_ace_web_access.md`.

Local PATH check (this workspace): `ffmpeg`, `tmux`, and `textual` are installed; `vhs`, `ttyd`, `asciinema`, `agg`,
`freeze`, and `obs` are not. VHS needs `ttyd` + `ffmpeg` on PATH (or its official Docker image).

## Lane 1: Screenshots

### Recommended: standalone script reusing the snapshot machinery

Write a small script (e.g. `scripts/take_demo_screenshots.py` or a `just screenshots` recipe) that imports `AcePage`,
the mock-data helpers, and `render_svg_to_png()`, then walks a list of (name, setup-keys, size) scenarios and writes
SVG+PNG into `docs/images/`. Essentially each visual test minus the assertion:

```python
async with AcePage(query='"visual"', changespecs=changespecs(), size=(120, 40)) as page:
    await wait_for_startup(page)
    await wait_for_visual_idle(page)
    svg = page.export_svg()
    Path("docs/images/changespecs_tab.svg").write_text(svg)
    Path("docs/images/changespecs_tab.png").write_bytes(render_svg_to_png(svg))
```

Fully deterministic, scripted key presses via Pilot, regenerable on demand (CI-able), and built on mock data — so no
real project names, paths, prompts, or chat snippets can leak. Note that `AcePage` patches ChangeSpec discovery to
fixture data by design; a future production `sase ace screenshot` command should make the fixture-vs-live data choice
an explicit flag.

Output-format notes:

- Commit the SVGs too: GitHub renders SVG natively in READMEs; it is sharp at any zoom and small.
- CairoSVG's text rendering is the weak link (no `@font-face` support); the hermetic fontconfig setup works around it
  and is fine for snapshots. For hero/marketing images, rendering the SVG with headless Chromium (Playwright
  `page.screenshot()` at `deviceScaleFactor=2`) or `rsvg-convert` gives noticeably better text.

### Live-session capture

- **Ctrl+P command palette → "Save screenshot"** — built into every Textual app, zero work, saves SVG.
- **`textual run --screenshot DELAY -c sase ace`** — textual-dev can auto-capture after a delay.
- A dedicated keybinding calling `self.save_screenshot()` is a ~5-line addition if Ctrl+P feels clunky, but per CLI
  conventions it needs config + `default_config.yml` entries — only worth it if live captures become frequent.

### One-off command output

Charm Freeze generates PNG/SVG/WebP from ANSI output (`--execute`, or pipe in `tmux capture-pane`). Good for static
command examples and log snippets; not the first choice for full-screen ACE shots since Textual already exports SVG.

## Demo Video Tool Landscape (verified June 2026)

| Tool | Latest | Status | Output | Role |
|---|---|---|---|---|
| VHS (charmbracelet) | v0.11.0, Mar 2026 | Active | GIF/MP4/WebM/PNG | Scripted, reproducible tapes; CI-friendly |
| asciinema | 3.2.0, Mar 2026 | Active (Rust rewrite since 3.0) | `.cast` | Live recording; web player embeds |
| agg | v1.9.0, May 2026 | Active | GIF from `.cast` | High-quality GIF render (gifski-based) |
| t-rec | pushed Jun 2026 | Active | GIF | Screenshots the real terminal window (X11/macOS) |
| terminalizer | Aug 2024 | Stale | GIF | Avoid |
| ttygif / svg-term-cli / termtosvg | 2024 or earlier | Dead/dormant | — | Avoid |

## Lane 2: VHS for Repeatable Demo Clips

[VHS](https://github.com/charmbracelet/vhs) runs a scripted `.tape` file through ttyd + a headless browser + ffmpeg
and emits GIF/MP4/WebM plus `Screenshot` PNGs of the current frame. Tapes are plain text committed to the repo (e.g.
`demos/*.tape`) and regenerated whenever the TUI changes — the same philosophy as the golden snapshots, but for
motion. Best for README/homepage clips, "SASE in 30 seconds" flows, and CI-regenerated media.

```tape
Output demos/sase_ace_tour.mp4
Output demos/sase_ace_tour.gif

Require sase
Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 22
Set Width 1280
Set Height 720
Set Theme "github-dark"
Set TypingSpeed 75ms

Hide
Type "export SASE_HOME=/tmp/sase-demo-home"
Enter
Type "sase demo seed agents-tab && clear"   # hypothetical seeder
Enter
Show

Type "sase ace"
Enter
Sleep 3s                       # let the alt-screen app paint fully
Wait+Screen /Agents/
Down Down Enter
Sleep 2s
Type "l"                       # reveal child agent entries
Screenshot demos/sase_agents_tab.png
Sleep 2s
Ctrl+C
```

Key controls: `TypingSpeed 50–100ms` for human-feel typing; `Hide`/`Show` to cut setup out of the recording;
`Wait+Screen /regex/` instead of blind sleeps where possible; `WindowBar` for polished chrome; `Require` to fail fast
on missing binaries. Set `FontFamily "Fira Code"` to match the snapshot suite (the font must be installed on the
recording machine).

Caveats: always sleep 1–3s after launching a full-screen TUI before `Show`; VHS has known rendering discrepancies
between real terminals and its ttyd/xterm.js layer (issues
[#344](https://github.com/charmbracelet/vhs/issues/344), [#412](https://github.com/charmbracelet/vhs/issues/412)) —
inspect output and adjust. Playback is fully scripted; no ad-libbing.

**Demo data wrinkle:** VHS records a real session, so a good demo needs a populated workspace. Options in increasing
effort: (1) record against a real project with innocuous data; (2) seed a throwaway demo project/`SASE_HOME` first
(can itself be a `Hide` section in the tape); (3) add a `sase ace` demo/fixture mode reusing
`patch_startup_loaders()`-style mock data outside tests — the most work, fully deterministic, only worth it if demos
become a maintained CI artifact.

## Lane 3: asciinema for Lightweight/Long-Form Casts

[asciinema](https://github.com/asciinema/asciinema) 3.x records real interactive sessions into tiny text-native
`.cast` files (asciicast v3): `asciinema rec demo.cast` with a fixed window size (e.g. 120x36) and
`--idle-time-limit 2` to cap dead air. One recording serves two outputs:

- **Web embed:** upload to asciinema.org or self-host — selectable text, crisp at any size. GitHub READMEs can't embed
  the JS player; use the SVG-preview-link pattern:
  `[![asciicast](https://asciinema.org/a/<id>.svg)](https://asciinema.org/a/<id>)`.
- **GIF:** `agg demo.cast demo.gif --font-family "Fira Code" --theme github-dark`.

Alt-screen caveat: a cast of a full-screen TUI garbles if replayed in a terminal smaller than the recorded cols×rows;
when embedding, set the player's `cols`/`rows` to match the cast header. Recommended role: long-form technical
walkthroughs and docs embeds — not the primary launch-media pipeline (no voiceover or composition, and visual polish
depends on the player).

## Lane 4: Narrated / Screen-Recorded Walkthroughs

For narrated, marketing-style videos, record a real terminal with OBS Studio (free, cross-platform; scenes composite
window capture, browser, webcam, and audio) — or Screen Studio on macOS for paid auto-zoom polish. This captures true
font rendering and allows voiceover, but is manual and non-reproducible — the wrong tool for README assets that need
refreshing as the TUI evolves.

Two useful patterns:

1. **Terminal window recording:** run `sase ace` in a clean terminal profile and record only that window.
2. **Browser-hosted TUI:** `textual serve` hosts the app in a browser for cleaner capture boundaries. Exposure
   warning: `textual-web -t` serves a terminal through a random public URL — do not share it with anyone you would not
   trust with machine access.

## GitHub README Media Constraints

- Images/GIFs: **10 MB max**. GIFs autoplay/loop (best attention-grabber) but are 256-color and heavy.
- Video: drag-and-drop an **H.264 MP4** into the README editor → GitHub renders an inline video player (10 MB free /
  100 MB paid). Better quality-per-byte than GIF; doesn't autoplay.
- Static SVG renders directly in READMEs — highest fidelity, smallest size for stills.
- GIF slimming: ffmpeg two-pass `palettegen`/`paletteuse`, then `gifsicle -O3 --lossy=80` (typically halves terminal
  GIFs). Lower framerates (VHS `Set Framerate`) and trimmed idle time matter more than codec tweaks.
- Render at ~2x display size (README column ≈ 830px wide) so retina screens look sharp.

## Demo Hygiene

For every public or semi-public artifact:

- Capture from a fresh temporary `SASE_HOME` or a committed demo fixture, not live home/project state.
- Redact or synthesize project names, branch names, prompts, chat snippets, file paths, and notification text.
- Pin terminal size, theme, font, and font size for every shot/video.
- Disable desktop notifications and avoid full-desktop capture.
- Prefer MP4/WebM for videos; GIF only as README/social fallback.
- Keep source scripts (`.tape` files, seed commands, fixture bundles) in repo so media can be regenerated after UI
  changes.

## Proposed Near-Term Plan

1. Add a screenshots script/`just` recipe reusing `AcePage` + the visual-test helpers; emit named SVG+PNG shots into
   `docs/images/`. Use the existing goldens in the meantime.
2. Install `vhs` + `ttyd`; add a `demos/` directory with a small demo-data seeder and one `.tape` file; render one
   Agents-tab still, one ChangeSpec-tab still, and one 20–30s clip (MP4 for inline README video + <10 MB GIF fallback).
3. Publish long-form walkthroughs as asciinema casts (SVG-preview links in the README), with agg for GIF renders of
   the same casts.
4. Use OBS only for the longer narrated "what is SASE?" video after the scripted clips exist.
5. Optionally add a production `sase ace screenshot` CLI wrapper with an explicit fixture-vs-live data flag, reusing
   the existing CairoSVG/fontconfig conventions rather than a second rasterization pipeline.

## Sources

- Textual: app API <https://textual.textualize.io/api/app/>, testing guide
  <https://textual.textualize.io/guide/testing/>, devtools <https://textual.textualize.io/guide/devtools/>,
  docs-image pipeline (`take_svg_screenshot`)
  <https://github.com/Textualize/textual/blob/main/src/textual/_doc.py>
- textual-dev `--screenshot`: <https://pypi.org/project/textual-dev/>
- textual-web: <https://github.com/textualize/textual-web>; ttyd: <https://github.com/tsl0922/ttyd>
- VHS: <https://github.com/charmbracelet/vhs> (v0.11.0); TUI rendering issues
  [#344](https://github.com/charmbracelet/vhs/issues/344), [#412](https://github.com/charmbracelet/vhs/issues/412)
- Charm Freeze: <https://github.com/charmbracelet/freeze>
- asciinema: 3.0 rewrite <https://blog.asciinema.org/post/three-point-o/>, CLI docs
  <https://docs.asciinema.org/manual/cli/>, embedding <https://docs.asciinema.org/manual/server/embedding/>, player
  options <https://docs.asciinema.org/manual/player/options/>
- agg: <https://github.com/asciinema/agg> (v1.9.0), <https://docs.asciinema.org/manual/agg/>
- CairoSVG limitations: <https://cairosvg.org/documentation/>
- GitHub README media limits:
  <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files>
- GIF optimization: <https://blog.pkh.me/p/21-high-quality-gif-with-ffmpeg.html>; gifski
  <https://github.com/ImageOptim/gifski/releases>
- OBS Studio: <https://obsproject.com/>
- Stale/dead tools: terminalizer <https://github.com/faressoft/terminalizer>, ttygif
  <https://github.com/icholy/ttygif>, svg-term-cli <https://github.com/marionebl/svg-term-cli>, termtosvg
  <https://github.com/nbedos/termtosvg> (archived)
