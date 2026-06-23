---
create_time: 2026-06-23
status: research
---

# Demo Videos of `sase ace` — Tooling, Workflow, and Tips

How to produce great **demo videos** of a human driving the `sase ace` TUI from the command line: which
tools to use, how to set up the recording environment, concrete recipes, and a tips/pitfalls checklist.

## Relationship to prior research (read this first)

A broad companion already exists: **`sdd/research/202606/tui_screenshots_and_demo_videos.md`** (2026-06-11). It
covers the full four-lane media workflow — static screenshots, VHS clips, asciinema casts, narrated walkthroughs —
plus the repo's existing SVG/PNG snapshot machinery, GitHub README media limits, and demo-data hygiene. **That
document is the authoritative reference for screenshots and the overall media strategy; this one does not repeat it.**

This doc is narrower and deeper on one thing the companion only sketches: the **craft of producing a motion demo
video of you personally operating `sase ace`** — the decision between scripted vs. live, the recording environment,
post-production without a video editor, audio narration, and ACE-specific gotchas. Where the two overlap (VHS tape
syntax, asciinema, README limits), this doc defers to the companion and adds only what's new.

## TL;DR recommendation

There is no single "best" tool — there are **two video types with different tools**, and you likely want both:

1. **Scripted, reproducible loops (README / docs / social):** **Charm VHS** `.tape` files committed to the repo.
   Demos-as-code; regenerate whenever the TUI changes; outputs GIF/MP4/WebM with zero manual editing. Pair with a
   one-pass **ffmpeg** filter chain for zoom/speed/palette and **gifsicle** for size.
2. **Narrated "here's me using it" walkthroughs (launch video / tutorial / talk):** **OBS Studio** screen-recording a
   clean GPU-accelerated terminal (Ghostty or WezTerm), with a **keystroke overlay** (`screenkey`) and a decent
   microphone. This is the right tool when *you* are the on-screen operator and there's voiceover.

If you only have time for one: start with **VHS** for a 20–30s silent loop (an hour of work, fully regenerable),
then graduate to OBS for the longer narrated piece once the script is proven.

Skip terminalizer, ttygif, svg-term-cli, termtosvg — stale/dead (see companion doc).

## Pick the video type before the tool

| | Scripted (VHS) | Live narrated (OBS / screen capture) | Interactive cast (asciinema + agg) |
|---|---|---|---|
| Best for | README/docs loops, CI-regenerated media | Launch/tutorial/talk videos, voiceover | Embeddable, copy-pasteable interactive casts |
| "Me using it" feel | Simulated (no human at keyboard) | Authentic — you really drive it | Authentic — you really drive it |
| Reproducible | ✅ fully (text tape) | ❌ manual, one-take | ⚠️ re-recordable, timing varies |
| Audio narration | ❌ add in post only | ✅ native | ❌ |
| Pixel fidelity of TUI | xterm.js (slight drift) | true terminal rendering | depends on player; alt-screen caveat |
| Effort to regenerate | trivial (`vhs demo.tape`) | high (re-shoot) | medium (re-record + `agg`) |
| Output | GIF/MP4/WebM/PNG frames | MP4 (any res, audio) | `.cast` → web embed or GIF |

The key insight: **VHS does not record you** — it replays a script. So "demo videos of *me* using `sase ace`" splits
into "demos that *look* hand-driven" (VHS, good enough for loops) and "demos that *are* hand-driven with my voice"
(OBS). Choose per audience.

## The recording environment (applies to all three)

Get this right once and every recording improves. Most of these mirror the determinism the repo already enforces for
visual snapshots (Fira Code pinned via fontconfig — see `tests/ace/tui/visual/`).

- **Terminal emulator (live recording):** use a GPU-accelerated emulator with ligature + truecolor support —
  **Ghostty** (clean, modern, fast) or **WezTerm** (scriptable in Lua, runs everywhere). **Avoid Alacritty for
  demos**: it deliberately omits font ligatures, so Fira Code won't look like the snapshots. Kitty is also fine.
  (For VHS the emulator is irrelevant — it renders via ttyd/xterm.js — but `FontFamily`/`Theme` still matter.)
- **Font:** **Fira Code** to match the snapshot suite (`memory/build_and_run.md`; pinned in
  `tests/ace/tui/visual/fonts/`). ACE leans on box-drawing and geometric Unicode (`● ✓ █ ░ ▶ ■ □ ├ ┤`), not Nerd
  Font glyphs, so a plain Fira Code install suffices — no patched Nerd Font required. Install Fira Code on whatever
  machine renders (your terminal for OBS; the host running VHS/agg).
- **Color / theme:** ACE emits 24-bit truecolor (Rich inline styles like `#87D7FF`). Pick a high-contrast dark theme
  and keep it identical across takes. VHS: `Set Theme "github-dark"` or a Catppuccin variant. Ensure `NO_COLOR` is
  unset and `TERM` advertises truecolor (`xterm-256color` + `COLORTERM=truecolor`).
- **Size:** ACE's snapshot goldens are **120×40**; treat that as the floor. Smaller and panels wrap/clip. Pin
  cols×rows explicitly (`tmux new -x 120 -y 40`, VHS `Set Width/Height`, asciinema `--cols/--rows`).
- **Resolution & font size — record big, downscale later.** Large font + high canvas gives you headroom to crop/zoom
  in post without pixelation. A proven recipe records at **2750×1625 with a 50pt font**, then downscales in ffmpeg.
  For OBS, capture at 1440p or 4K and export 1080p.
- **Prompt hygiene:** a minimal one-line shell prompt (or hide the prompt entirely in VHS with `Hide`/`Show`). No
  hostname, no git noise, no secrets in scrollback. Clear the screen before the app launches.
- **Demo hygiene (non-negotiable for anything public):** record from a throwaway `SASE_HOME`, synthesize project /
  branch / prompt / chat text, and **turn off desktop notifications / enable Do-Not-Disturb** before any live capture.
  Full list in the companion doc's "Demo Hygiene" section.

## TUI-specific gotchas (the part that bites everyone)

`sase ace` is a full-screen, alt-screen, keyboard-driven Textual app. That breaks naive terminal recording in
predictable ways:

- **Alt-screen needs settling time.** After launching, the app clears and repaints asynchronously. Always wait
  1–3s before you start capturing content (VHS: `Sleep 2s` after `Enter`, or better `Wait /Agents/`). asciinema casts
  of alt-screen apps **garble if replayed in a terminal smaller than the recorded cols×rows** — pin player size to
  the cast header.
- **Keystrokes are invisible by default — surface them.** ACE is driven by keymaps (leader keys, `h`/`l` to
  hide/reveal child agent rows, tab navigation — see `memory/glossary.md`). A viewer can't follow a keyboard demo
  without seeing the keys. For **live** recording add an on-screen keystroke overlay (`screenkey` or `key-mon` on
  Linux; `KeyCastr` on macOS). For **VHS**, the typed text is visible but chords aren't — narrate them in captions or
  on-screen text.
- **Reproducible demo state is the hard problem.** VHS records a *real* session, so the workspace must be populated
  and deterministic. The snapshot suite's mock-data machinery (`AcePage`, `patch_startup_loaders()`,
  `make_changespec()` / `DEFAULT_CHANGESPECS` in `src/sase/ace/testing/__init__.py`) is **test-only** and not reachable
  from a live `sase ace`. Three options, increasing effort (also in the companion doc):
  1. Record against a real project with innocuous data.
  2. Seed a throwaway demo project / `SASE_HOME` first (do it inside a VHS `Hide` block).
  3. **Add an env-gated demo/mock mode** to `sase ace` (e.g. `SASE_ACE_DEMO=1`) that swaps live loaders for canned
     fixtures *at the data layer, not the UI layer* — so the demo doubles as an integration smoke test. This is the
     gold standard for a maintained CI media artifact and the natural productization of the existing test fixtures.
     Per `memory/rust_core_backend_boundary.md`, seeded demo *data* belongs behind the Rust core / adapter boundary,
     not hardcoded in Textual widgets.
- **Pacing for agent runs.** If a demo shows agents working, real latency is non-deterministic and slow. A demo mode
  can keep two clocks: a short *actual* delay (recording stays fast) and a realistic *displayed* duration the UI
  reports — so it reads as real work without the wait.
- **Don't record `Ctrl+C` ugliness.** End the tape/clip with a clean quit (ACE's quit keybinding), not a raw
  interrupt that dumps a traceback or leaves the alt-screen half-restored.

## Recipe A — Scripted loop with VHS (no editor needed)

VHS runs a text `.tape` through ttyd + headless Chromium + ffmpeg and emits GIF/MP4/WebM (and `Screenshot` PNGs).
Tapes live in the repo (e.g. `demos/*.tape`) and regenerate on demand. Full command reference is in the companion
doc; the additions here are the **high-res + ffmpeg post** pattern.

```tape
# demos/sase_ace_tour.tape
Output demos/sase_ace_tour_raw.mp4
Output demos/sase_ace_tour_raw.gif

Require sase
Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 50            # record big; downscale in ffmpeg
Set Width 2750
Set Height 1625
Set Theme "github-dark"
Set TypingSpeed 75ms       # human-feel typing
Set CursorBlink false      # steadier frames, smaller files
Set WindowBar Colorful     # optional polished chrome

Hide                       # setup the viewer never sees
Type "export SASE_HOME=/tmp/sase-demo-home SASE_ACE_DEMO=1"
Enter
Type "clear"
Enter
Show

Type "sase ace"
Enter
Wait /Agents/              # settle alt-screen instead of a blind Sleep
Sleep 1s
Down Down Enter            # navigate the Agents tab
Sleep 1500ms
Type "l"                   # reveal child agent rows
Sleep 2s
Screenshot demos/agents_tab.png
# quit cleanly with ACE's quit key (adjust to the real binding)
Ctrl+Q
Sleep 500ms
```

Then one ffmpeg pass turns the raw capture into a tuned GIF + MP4 (downscale, optional zoom on the first beats,
optional speed ramp, palette optimization). Drive it from a `just` recipe or Makefile target so a single command
regenerates everything:

```bash
# downscale + palette-optimized GIF (high quality, small)
ffmpeg -i demos/sase_ace_tour_raw.gif -filter_complex \
  "[0:v]scale=1100:-1:flags=lanczos,split[s0][s1];\
   [s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=sierra2_4a" \
  -r 12 -y demos/sase_ace_tour.gif

# web/README MP4 (H.264, downscaled)
ffmpeg -i demos/sase_ace_tour_raw.mp4 -vf "scale=1280:-2:flags=lanczos" \
  -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart -y demos/sase_ace_tour.mp4

gifsicle -O3 --lossy=80 -o demos/sase_ace_tour.gif demos/sase_ace_tour.gif   # final squeeze
```

For zoom/speed effects in the *same* pass (cropping a region and overlaying it for the first few seconds, plus
`setpts=N*PTS` speed ramps), the technique is a single `-filter_complex` chain — see the cited "polished TUI demo
without a video editor" write-up. Lower `-r` (framerate) and trimmed idle time shrink GIFs far more than codec tweaks.

**Caveats:** VHS renders through xterm.js, which has documented rendering drift vs. real terminals for some TUIs
(VHS issues #344, #412) — always eyeball the output. Playback is fully scripted; no ad-libbing. `TypingSpeed`
50–100ms reads as human; faster looks robotic, slower drags.

## Recipe B — Live narrated walkthrough with OBS

This is the tool for "**me** using `sase ace`" with voice — launch videos, tutorials, conference demos.

- **Capture source:** add a single *window capture* of your terminal (not full-desktop) so notifications and other
  windows can't leak in. Run ACE inside `tmux new -x 120 -y 40` (or your target size) for a pinned, chrome-free pane.
- **Resolution / canvas:** set the OBS base canvas to 1440p or 4K, export 1080p. Bump the terminal font live
  (`Ctrl+=`) until text is legible at the export size — terminal demos need a *much* bigger font than daily use.
- **Keystroke overlay:** run `screenkey` (Linux) / `KeyCastr` (macOS) so viewers see the chords. Essential for ACE's
  keymap-heavy flows. Position it in a low corner of the OBS scene.
- **Audio:** narrate live with a real mic (USB condenser or headset beats laptop mic). Record a separate audio track
  in OBS so you can fix narration without re-shooting video. Add a noise-suppression filter.
- **Cursor / zoom:** on Linux, zoom in post (ffmpeg crop/scale, or kdenlive/Shotcut). On macOS, **Screen Studio**
  gives automatic cursor-follow zoom and is worth the license for marketing-grade polish.
- **Pacing:** rehearse with the script from the VHS tape so the live take hits the same beats. Pause briefly before
  each keypress so the overlay registers.
- **Browser alternative:** `textual serve` / textual-web can host ACE in a browser for a cleaner capture boundary —
  but `textual-web -t` exposes a **public URL with terminal access**; never share it. (Detail in companion doc.)

## Recipe C — Interactive cast with asciinema + agg

When you want an embeddable, text-native, copy-pasteable cast (docs pages, long-form), record with **asciinema 3.x**
at a fixed size and cap idle time, then render a high-quality GIF with **agg** (gifski-based). The key agg quality
lever: **set a large `--font-size`** (default 16 looks bad) and match the font/theme.

```bash
asciinema rec --cols 120 --rows 40 --idle-time-limit 2 demos/ace.cast
agg --font-family "Fira Code" --font-size 28 --theme github-dark \
    --speed 1.5 --fps-cap 24 --idle-time-limit 1 demos/ace.cast demos/ace.gif
```

agg bundles **Symbols Nerd Font** for powerline/devicon glyphs automatically and renders emoji from installed color
emoji fonts. Use asciinema only as a secondary lane — see companion doc for the alt-screen replay caveat and the
GitHub SVG-preview-link embed pattern (`[![asciicast](.../<id>.svg)](.../<id>)`).

## Post-production without a video editor

Everything below is one-pass ffmpeg, scriptable into a `just` recipe — no timeline editor required:

- **Downscale:** `scale=W:-2:flags=lanczos` (record big, ship small; `-2` keeps even dimensions for H.264).
- **Speed ramp:** `setpts=0.5*PTS` (2× faster) for boring stretches; combine with audio `atempo` if narrated.
- **Zoom highlight:** `crop` a region + `scale` back up + `overlay ... enable='lt(t,N)'` to punch in for the first N
  seconds.
- **GIF palette:** two-stage `palettegen` (`max_colors=128`) + `paletteuse=dither=sierra2_4a`; then `gifsicle -O3
  --lossy=80` (often halves terminal GIFs).
- **MP4 for web:** `-c:v libx264 -pix_fmt yuv420p -crf 18..23 -movflags +faststart`.
- **Captions:** burn-in keymap callouts with the `drawtext` filter, or ship a sidecar `.srt`. Captions are how you
  convey chords in silent VHS loops and how you make narrated videos accessible.

## Output targets & constraints

(See companion doc for the full GitHub README media table; summary here.)

- **GitHub README:** images/GIFs **10 MB max** (autoplay/loop, 256-color, heavy). Drag-and-drop **H.264 MP4** →
  inline player (10 MB free / 100 MB paid, no autoplay, better quality-per-byte). Static SVG = highest fidelity for
  stills. Render at ~2× display width (README column ≈ 830px).
- **X/Twitter, LinkedIn:** MP4 autoplays in-feed and beats GIF on quality and size — prefer MP4 for social.
- **YouTube / talks:** 1080p+ MP4 with narration audio; this is the OBS lane.
- **Docs site / asciinema.org:** the asciinema web player (selectable text, crisp at any zoom).

## Local environment status (this workspace, 2026-06-23)

Verified on PATH:

- **Installed:** `ffmpeg`, `ffprobe`, `textual`, `tmux`, `google-chrome`.
- **Missing:** `vhs`, `ttyd`, `asciinema`, `agg`, `obs`, `gifsicle`, `chromium`.
- **Watch out:** `freeze` resolves to an **`icebox` alias on this machine, not Charm Freeze** — installing Charm
  Freeze (for ANSI-output stills) requires a separate, explicitly-named binary.

To stand up the scripted lane: install `vhs` (needs `ttyd` + `ffmpeg`, or use VHS's official Docker image which
bundles both), plus `gifsicle` for GIF squeezing. For the live lane: install `obs` + `screenkey` and a GPU terminal
(Ghostty/WezTerm). `google-chrome` can substitute for `chromium` if VHS or textual-web needs a headless browser.

## Tips & pitfalls checklist

- Decide video type first (scripted loop vs. narrated walkthrough); use the right tool for each.
- Record big, downscale in post — never the reverse.
- Pin size (≥120×40), font (Fira Code), and theme for every take; keep them identical across takes.
- Always settle the alt-screen (1–3s or `Wait /regex/`) before capturing ACE content.
- Surface keystrokes: `screenkey` for live, captions for VHS.
- Solve demo state deliberately: throwaway `SASE_HOME`, or (better) an env-gated `SASE_ACE_DEMO` mock mode reusing
  the existing fixtures behind the core boundary.
- Use `Hide`/`Show` (VHS) to cut setup; clear the screen before launch.
- Turn off notifications / enable DND; window-capture, never full-desktop.
- End on a clean quit, not `Ctrl+C`.
- Keep the source (`.tape`, seed commands, ffmpeg recipe) in-repo so media regenerates after UI changes.
- Eyeball VHS output for xterm.js rendering drift.
- Prefer MP4 over GIF wherever the platform allows it.

## Recommendations / next steps

1. **Now (silent loop):** install `vhs` + `ttyd` + `gifsicle`; add `demos/sase_ace_tour.tape` and a `just demo` recipe
   that runs VHS then the ffmpeg/gifsicle post-pass. Ship an MP4 (README inline video) + <10 MB GIF fallback.
2. **Next (reproducibility):** add an env-gated `SASE_ACE_DEMO` mode that seeds canned ChangeSpec/agent state at the
   data layer (productizing `patch_startup_loaders()`/`DEFAULT_CHANGESPECS` through the Rust-core/adapter boundary), so
   demos are deterministic and double as a smoke test.
3. **Then (narrated):** record the longer "here's me using `sase ace`" walkthrough in OBS with `screenkey` + mic,
   reusing the proven tape script as the run-of-show; export 1080p MP4 for YouTube/social.
4. Reuse the screenshot lane and overall strategy from `tui_screenshots_and_demo_videos.md` rather than re-solving it.

## Sources

- Companion repo research: `sdd/research/202606/tui_screenshots_and_demo_videos.md` (2026-06-11)
- VHS: <https://github.com/charmbracelet/vhs>, README/tape reference
  <https://github.com/charmbracelet/vhs/blob/main/README.md>, demo tape
  <https://github.com/charmbracelet/vhs/blob/main/examples/demo.tape>
- "Making a Polished TUI Demo Video Without a Video Editor" (VHS + ffmpeg, high-res + filter chains):
  <https://blog.kunchenguid.com/p/making-a-polished-tui-demo-video>
- VHS deep-dive: <https://tywer.dev/beyond-screenshots-capture-cli-magic-with-charmbracelet-vhs>
- asciinema: <https://github.com/asciinema/asciinema>, 3.0 rewrite <https://blog.asciinema.org/post/three-point-o/>
- agg: <https://github.com/asciinema/agg>, usage <https://docs.asciinema.org/manual/agg/usage/>
- Terminal emulator comparison (ligatures/truecolor): <https://blog.codeminer42.com/modern-terminals-alacritty-kitty-and-ghostty/>,
  <https://blog.luminoid.dev/Terminal-Emulator-Comparison-2026/>
- High-quality GIF with ffmpeg (palettegen/paletteuse): <https://blog.pkh.me/p/21-high-quality-gif-with-ffmpeg.html>
- OBS Studio: <https://obsproject.com/>; Screen Studio (macOS auto-zoom): <https://screen.studio/>
- Textual app/devtools/serve: <https://textual.textualize.io/>; textual-web: <https://github.com/textualize/textual-web>
- Repo grounding: `src/sase/ace/testing/__init__.py`, `tests/ace/tui/visual/`, `memory/glossary.md`,
  `memory/rust_core_backend_boundary.md`, `memory/build_and_run.md`
