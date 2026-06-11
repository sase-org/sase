# TUI Screenshots & Demo Videos for sase

> Note: this is an independent second research pass on the same question as
> `tui_screenshots_and_demo_videos.md` (written by a parallel agent run). The two docs overlap but each has unique
> material; consider consolidating.

## Goal

Figure out the best way to (1) take polished screenshots of the `sase ace` TUI and (2) record demo videos/GIFs that
show people how sase works — for the README, docs, and sharing. This covers what the repo already provides, the
external tool landscape (verified June 2026), and concrete recommended workflows.

## What We Already Have In-Repo

The PNG visual snapshot suite is, in effect, a production-ready screenshot factory. It already solves the hard
problems (deterministic rendering, fonts, app state seeding):

- **SVG export**: `AceApp` inherits Textual's `export_screenshot()`; `AcePage.export_svg()`
  (`src/sase/ace/testing/__init__.py:207`) captures the current screen as an SVG string. Textual renders to its own
  compositor, so output is pixel-perfect regardless of terminal emulator.
- **SVG → PNG**: `render_svg_to_png()` (`tests/ace/tui/visual/png_diff.py:146`) via cairosvg.
- **Deterministic app state**: `AcePage` wraps `AceApp.run_test(size=...)` (Textual Pilot, headless), and
  `tests/ace/tui/visual/_ace_png_snapshot_helpers.py` provides realistic mock data — `changespecs()`, `agents()`,
  `project_records()`, `axe_collected_data()` — plus `patch_startup_loaders()` to swap all background loaders for
  mocks, and `wait_for_startup()` / `wait_for_visual_idle()` to settle layout before capture.
- **Hermetic rendering**: `tests/ace/tui/visual/conftest.py` pins bundled Fira Code via fontconfig
  (`_hermetic_fontconfig`), forces color, and pins the PID for byte-identical output.
- **Existing goldens**: `tests/ace/tui/visual/snapshots/png/` already contains ~25 representative 120x40 shots
  (`changespec_initial_120x40.png`, `agents_list_120x40.png`, `axe_selected_row_120x40.png`, ...) — some may be
  directly usable as demo material.

There is no screenshot CLI flag, no asciinema/VHS tooling, and no demo video infrastructure in the repo yet. The
README has a single static image (`docs/images/sase_overview.png`). Prior related research:
`sdd/research/202605/tui_screenshot_diff_testing.md` (the epic that built the snapshot suite; its Phase 5 notes
already flagged VHS as an optional future tool).

## Screenshots

### Option A: Reuse the snapshot machinery in a standalone script (recommended)

Write a small script (e.g. `scripts/take_demo_screenshots.py` or a `just screenshots` recipe) that imports `AcePage`,
the mock-data helpers, and `render_svg_to_png()`, then walks a list of (name, setup-keys, size) scenarios and writes
PNGs/SVGs to `docs/images/`. Essentially each visual test minus the assertion:

```python
async with AcePage(query='"visual"', changespecs=changespecs(), size=(120, 40)) as page:
    await wait_for_startup(page)
    await wait_for_visual_idle(page)
    svg = page.export_svg()
    Path("docs/images/changespecs_tab.png").write_bytes(render_svg_to_png(svg))
```

Pros: fully deterministic, scripted key presses via Pilot, regenerable on demand (CI-able), uses the demo-quality
mock data we already maintain. Cons: mock data, not a live session (arguably a pro for screenshots — no real project
names/paths leak).

Two output-format notes:

- **Commit the SVGs too.** GitHub renders SVG in READMEs natively; Textual's SVG output is its highest-fidelity
  format (sharp at any zoom, small files). PNG is for places that can't take SVG.
- **cairosvg font fidelity is the weak link** (its docs admit text support is poor; no `@font-face`). Our hermetic
  fontconfig setup works around this and is fine for snapshots. For hero/marketing images, rendering the SVG with
  headless Chromium (Playwright `page.screenshot()` at `deviceScaleFactor=2`) or `rsvg-convert` gives noticeably
  better text rendering than cairosvg.

### Option B: Live-session capture

For screenshots of real (non-mock) sessions:

- **Ctrl+P command palette → "Save screenshot"** — built into every Textual app today, zero work, saves SVG.
- **`textual run --screenshot DELAY -c sase ace`** — textual-dev (1.8.0) can auto-capture after a delay; pairs with
  the `textual run --dev` workflow already noted in `sdd/research/202605/ace_live_introspection_tooling.md`.
- A tiny dedicated keybinding (e.g. on a debug/leader key) calling `self.save_screenshot()` would be a ~5-line
  addition if Ctrl+P feels clunky; per CLI conventions it would need config + default_config.yml entries, so only
  worth it if we capture live screenshots often.

## Demo Videos / GIFs

The repo has nothing for this yet; this is where external tools come in. Tool landscape as of June 2026:

| Tool | Latest | Status | Output | Role |
|---|---|---|---|---|
| VHS (charmbracelet) | v0.11.0, Mar 2026 | Active | GIF/MP4/WebM/PNG | Scripted, reproducible tapes; CI-friendly |
| asciinema | 3.2.0, Mar 2026 | Active (Rust rewrite since 3.0) | `.cast` | Live recording; web player embeds |
| agg | v1.9.0, May 2026 | Active | GIF from `.cast` | High-quality GIF render (gifski-based) |
| t-rec | pushed Jun 2026 | Active | GIF | Screenshots the real terminal window (X11/macOS) |
| terminalizer | last push Aug 2024 | Stale | GIF | Avoid |
| ttygif / svg-term-cli / termtosvg | 2024 or earlier | Dead/dormant | — | Avoid |

### Option A: VHS tapes (recommended for README/docs demos)

[VHS](https://github.com/charmbracelet/vhs) runs a scripted `.tape` file through ttyd + a headless browser + ffmpeg
and emits GIF/MP4/WebM. Tapes are plain text we can commit (e.g. `demos/*.tape`) and regenerate whenever the TUI
changes — same philosophy as our golden snapshots, but for motion.

```tape
Output demos/sase_ace_tour.mp4
Output demos/sase_ace_tour.gif
Set FontFamily "Fira Code"
Set FontSize 28
Set Width 1400
Set Height 800
Set TypingSpeed 75ms
Set Theme "github-dark"
Hide
Type "sase ace" Enter
Sleep 3s            # let the alt-screen app paint fully
Show
Down Down Enter
Sleep 2s
Type "l"            # reveal child agent entries
Sleep 2s
```

Key settings: `TypingSpeed 50–100ms` for human-feel typing, `Hide`/`Show` to cut setup out of the recording, `Wait`
(regex on output) instead of fixed sleeps where possible, `WindowBar` for a polished window chrome. Requirements:
`vhs`, `ttyd`, `ffmpeg` on PATH; the font must be installed on the recording machine (Fira Code, matching our
snapshots).

Caveats for full-screen TUIs: always sleep 1–3s after launching before `Show`; VHS has known rendering discrepancies
between the real terminal and its ttyd/xterm.js layer (issues
[#344](https://github.com/charmbracelet/vhs/issues/344), [#412](https://github.com/charmbracelet/vhs/issues/412)) —
inspect output and adjust. Playback is fully scripted; no ad-libbing.

One sase-specific wrinkle: a good demo needs a populated workspace. Options, in increasing effort: record against a
real project with innocuous data; build a seeded throwaway demo project first (could itself be a `Hide`-section in
the tape); or add a `sase ace` demo/fixture mode reusing `patch_startup_loaders()`-style mock data outside tests
(most work, fully deterministic — only worth it if demos become a maintained CI artifact).

### Option B: asciinema 3.x for live/long-form demos

[asciinema](https://github.com/asciinema/asciinema) 3.2 (Rust, asciicast v3 format) is the right tool for recording
*real* interactive sessions: `asciinema rec demo.cast` (use a fixed window size, e.g. 120x36, and
`--idle-time-limit 2` to cap dead air). One recording then serves two outputs:

- **Web embed**: upload to asciinema.org (or self-host) — tiny file, selectable text, crisp at any size. GitHub
  READMEs can't embed the JS player, but the documented pattern is an SVG-preview link:
  `[![asciicast](https://asciinema.org/a/<id>.svg)](https://asciinema.org/a/<id>)`.
- **GIF**: `agg demo.cast demo.gif --font-family "Fira Code" --theme github-dark` — agg uses gifski and bundles Nerd
  Font/emoji fallback.

Alt-screen caveat: a `.cast` of a full-screen TUI garbles if played in a terminal smaller than the recorded
cols x rows; when embedding, set the player's `cols`/`rows` to match the cast header. For scripted (non-live)
asciinema sessions, drive the app via `tmux send-keys` while recording the attached session — more fragile than VHS
but captures the genuine PTY with no browser rendering layer.

### Option C: Real screen recording (OBS / Screen Studio)

For narrated, marketing-style videos: record an actual terminal (Ghostty/kitty/WezTerm render nicest in 2026) with
OBS Studio (free, cross-platform) or Screen Studio (macOS, paid, auto-zoom polish). Captures true font
rendering and allows voiceover, but is non-reproducible and manual — wrong tool for README assets that need
refreshing as the TUI evolves.

## GitHub README Constraints & File-Size Notes

- Images/GIFs in READMEs: **10 MB max**. GIFs autoplay/loop (best attention-grabber) but are 256-color and heavy.
- Video: drag-and-drop an **H.264 MP4** into the README editor → GitHub renders an inline `<video>` player (10 MB
  free plan / 100 MB paid). Better quality-per-byte than GIF; doesn't autoplay.
- Static SVG (Textual's native export) renders directly in READMEs — highest fidelity, smallest size for stills.
- GIF slimming: ffmpeg two-pass `palettegen`/`paletteuse`, then `gifsicle -O3 --lossy=80` (typically halves terminal
  GIFs). Lower framerates (VHS `Set Framerate`) and trimmed idle time matter more than codec tweaks.
- Render at ~2x display size (README column is ~830px wide) so retina screens look sharp.

## Recommendation

1. **Screenshots now**: add a small standalone script/`just` recipe that reuses `AcePage` + the visual-test helpers
   to emit named SVG+PNG shots into `docs/images/`. Near-zero new machinery; regenerable forever. Use the existing
   goldens in `tests/ace/tui/visual/snapshots/png/` in the meantime.
2. **README/docs videos**: adopt **VHS**; commit `.tape` files under `demos/`, output MP4 (attach to README as
   inline video) plus a <10 MB GIF fallback. Start by recording against a seeded demo project.
3. **Long-form/interactive demos**: **asciinema 3.x** recordings, published with the SVG-preview-link pattern in the
   README, with agg as the GIF renderer for the same casts.
4. Skip terminalizer/ttygif/svg-term-cli (stale); skip building a Pilot-based *video* pipeline (Textual has no
   native animation-capture path — stills only).

## Sources

- Textual screenshot APIs: <https://textual.textualize.io/api/app/>, <https://textual.textualize.io/guide/testing/>,
  <https://textual.textualize.io/guide/command_palette/>; docs-image pipeline:
  <https://github.com/Textualize/textual/blob/main/src/textual/_doc.py> (`take_svg_screenshot`)
- textual-dev `--screenshot`: <https://github.com/Textualize/textual-dev/blob/main/src/textual_dev/cli.py>,
  <https://pypi.org/project/textual-dev/>
- cairosvg font limitations: <https://cairosvg.org/documentation/>; headless-Chromium SVG→PNG:
  <https://docs.imgix.com/en-US/getting-started/tutorials/developer-guides/convert-svg-to-png-using-headless-chrome>
- VHS: <https://github.com/charmbracelet/vhs> (v0.11.0, Mar 2026); TUI rendering issues
  [#344](https://github.com/charmbracelet/vhs/issues/344), [#412](https://github.com/charmbracelet/vhs/issues/412)
- asciinema 3.0 rewrite: <https://blog.asciinema.org/post/three-point-o/>; changelog:
  <https://github.com/asciinema/asciinema/blob/develop/CHANGELOG.md>; README embedding:
  <https://docs.asciinema.org/manual/server/embedding/>; player cols/rows:
  <https://docs.asciinema.org/manual/player/options/>
- agg: <https://github.com/asciinema/agg> (v1.9.0, May 2026), <https://docs.asciinema.org/manual/agg/>
- GitHub README media limits: <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files>
- GIF optimization: <https://blog.pkh.me/p/21-high-quality-gif-with-ffmpeg.html>,
  <https://github.com/ImageOptim/gifski/releases>,
  <https://www.digitalocean.com/community/tutorials/how-to-make-and-optimize-gifs-on-the-command-line>
- Stale-tool status (GitHub activity): <https://github.com/faressoft/terminalizer>, <https://github.com/icholy/ttygif>,
  <https://github.com/marionebl/svg-term-cli>, <https://github.com/nbedos/termtosvg> (archived 2020)
