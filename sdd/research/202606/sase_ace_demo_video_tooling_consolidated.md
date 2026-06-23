---
create_time: 2026-06-23
status: research
---

# SASE ACE Demo Video Tooling - Consolidated

Consolidated from the two independent research notes created on 2026-06-23:

- `sdd/research/202606/sase_ace_cli_demo_video_tooling.md`
- `sdd/research/202606/sase_ace_demo_video_tooling.md`

## Question

What tooling and workflow should Bryan use to create great demo videos of himself using `sase ace` from the command
line? Include tooling recommendations, production tips, and related follow-up work.

## Bottom Line

Use a three-lane workflow. No single tool is best for every demo because "me using `sase ace`" splits into scripted
product clips, real narrated walkthroughs, and developer-readable terminal casts.

1. **Scripted loops:** use **Charm VHS** `.tape` files for 20-45 second README/docs/social clips. VHS is demos-as-code:
   reproducible, reviewable, and regenerable after the TUI changes.
2. **Narrated videos:** use **OBS Studio** on Linux/Windows, or **Screen Studio** on macOS if available, when the video
   should actually show Bryan driving ACE with voiceover. This is the flagship "watch me use SASE" lane.
3. **Technical casts:** use **asciinema CLI 3.x** plus **agg** when the audience benefits from selectable terminal text
   and web embeds more than polished video composition.

Start by making one short VHS loop. It forces the story, demo data, terminal geometry, and pacing to become explicit.
Then reuse that tape as the run-of-show for the narrated OBS recording.

For still images, posters, and thumbnails, reuse the existing Textual/ACE screenshot workflow documented in
`sdd/research/202606/tui_screenshots_and_demo_videos.md`; do not pull stills from compressed video frames unless the
frame itself is the point.

## Verification Notes

Checked on 2026-06-23:

- `sase ace --help` supports `--tab {changespecs,agents,axe}` and `--refresh-interval`; default startup tab is
  `agents`.
- The default ACE keymap has `q` for quit, `tab` / `shift+tab` for tab switching, `l` / `L` for expand/layout actions,
  and `Q` for stop-axe-and-quit.
- Current upstream releases: VHS `v0.11.0` (2026-03-10), asciinema `v3.2.1` (2026-06-16), agg `v1.9.0`
  (2026-05-29), OBS Studio `32.1.2` (2026-04-21).
- The older companion note's asciinema `v3.2.0` reference is now stale. For asciinema CLI 3.x examples, prefer
  `--window-size 120x40`; old `--cols` / `--rows` examples are from the 2.x era.
- Local PATH status: installed `ffmpeg`, `ffprobe`, `textual`, `tmux`, `google-chrome`; missing `vhs`, `ttyd`,
  `asciinema`, `agg`, `obs`, `gifsicle`, `chromium`, `screenkey`, `wezterm`, and `ghostty`.
- In interactive zsh, `freeze` is currently `freeze='icebox --freeze /tmp/icebox'`, not Charm Freeze.

## Tooling Matrix

| Tool | Use it for | Strengths | Limits | Recommendation |
|---|---|---|---|---|
| OBS Studio | Narrated walkthroughs, tutorials, launch videos | Free, open source, scenes, window capture, mic/webcam/audio filters | Manual and non-reproducible | Primary live-recording tool on this Linux workspace |
| Screen Studio | Polished macOS product demos | Auto zoom, cursor smoothing, shortcut display, fast exports | macOS-only and paid | Best quality-per-hour if recording on a Mac |
| VHS | README/docs/social loops and B-roll | `.tape` files in repo; outputs GIF/MP4/WebM/PNG frames; regenerable | Scripted, not truly Bryan typing live; xterm.js rendering may differ | First tool to adopt for a short public clip |
| asciinema CLI | Developer casts and docs embeds | Tiny text-native `.cast` files; selectable text; web player | Not a normal video; TUI keypresses are hard to see; fixed geometry matters | Secondary lane for technical docs |
| agg | GIFs from asciinema casts | Good font/theme controls, idle limiting, `--select`, improved box drawing in v1.9.0 | GIFs can still get large; no narration | Use for asciinema GIF fallbacks |
| FFmpeg + gifsicle | Compression, cropping, downscaling, GIF palette optimization | Scriptable and repeatable | Not a creative editor | Put in `just` recipes after capture |
| Descript | Fast cleanup for narrated videos | Text-based edit, transcription, captions | Cloud/product dependency; less precise timeline control | Good for sub-10-minute spoken tutorials |
| DaVinci Resolve | Launch-quality edit | Professional timeline, color, effects, audio | More setup and learning curve | Use when the video needs polish beyond simple cuts |

Avoid `terminalizer`, `ttygif`, `svg-term-cli`, and `termtosvg` for this job. The companion research found them stale or
dormant relative to VHS/asciinema/agg, and they do not solve the hard parts for ACE: current TUI rendering,
deterministic state, visible keyboard intent, narration, and polished exports.

## Recommended Production Plan

### 1. Build a 20-30 Second VHS Loop First

Goal: a silent, repeatable clip that proves the public story.

The strongest first story is not "SASE has a TUI." It is "SASE makes many agent runs observable, resumable, and
coordinated from one keyboard-driven control surface."

Good first beats:

- Start at the shell and type `sase ace --tab agents --refresh-interval 0`.
- Let ACE open on the Agents tab.
- Move through a few agent rows and reveal details/files/output.
- Jump from an agent to its related ChangeSpec or plan state.
- End on a clean quit.

This should be source-controlled under a future `demos/` directory:

```text
demos/
  README.md
  scripts/
    seed_sase_ace_demo
  tapes/
    sase_ace_agents.tape
  casts/
    .gitignore
  out/
    .gitignore
```

The seeder is the most important missing piece. Without deterministic demo data, every recording tool produces fragile
or privacy-risky output.

### 2. Record the Flagship Narrated Video in OBS

Once the tape story feels right, record Bryan operating the same flow live:

- Capture only the terminal window, not the full desktop.
- Use a clean terminal profile, fixed geometry, high-contrast theme, no transparency, and no desktop notifications.
- Add a keystroke overlay (`screenkey` on Linux, KeyCastr on macOS) because ACE is keymap-driven.
- Use a real mic and record mic audio on a separate OBS track.
- Rehearse from the VHS tape, then record a short take. Cut setup, waiting, and mistakes afterward.

OBS baseline:

- Canvas/output: 1920x1080 or 2560x1440, 30 fps.
- Source: terminal window capture.
- Record: MKV if that is your normal resilient OBS workflow; remux/export MP4 H.264 for publishing.
- Audio: 48 kHz, light noise suppression only after a test confirms it does not clip quiet words.
- Export: MP4 H.264, `yuv420p`, AAC or Opus audio, Fast Start metadata.

Screen Studio is a strong macOS alternative when automatic zoom/cursor polish matters more than open-source tooling.
For terminal-only videos, manually review auto-zooms; TUI state changes often happen without mouse movement.

### 3. Use asciinema + agg for Text-Native Casts

Use this lane for developer docs, not flagship product videos. It is excellent when users should be able to pause,
copy text, or inspect terminal output without downloading a video.

For asciinema CLI 3.x:

```bash
asciinema rec --window-size 120x40 -i 2 \
  -c 'sase ace --tab agents --refresh-interval 0' \
  demos/casts/sase_ace_agents.cast
```

Then render a GIF excerpt:

```bash
agg \
  --theme github-dark \
  --font-family "Fira Code" \
  --font-size 24 \
  --line-height 1.3 \
  --idle-time-limit 1 \
  --fps-cap 20 \
  --select 3..25 \
  demos/casts/sase_ace_agents.cast \
  demos/out/sase_ace_agents.gif
```

For GitHub READMEs, do not try to embed the asciinema JS player. Use an SVG preview image linking to the hosted cast,
or render a GIF/MP4 fallback.

## Recording Environment

Make one reproducible demo profile and keep it boring.

- **Data:** use a throwaway `SASE_HOME` and `SASE_TMPDIR`; never record live home-server/project state.
- **Geometry:** pin at least 120x40 cells. ACE visual goldens use 120x40, and smaller sizes can wrap or hide useful
  panels.
- **Refresh:** use `--refresh-interval 0` for stable recorded state unless the clip is explicitly about live updates.
- **Font:** use Fira Code or JetBrains Mono at a size that remains readable at 50% playback size. Fira Code matches the
  repo's visual snapshot lane.
- **Terminal:** prefer Ghostty, WezTerm, or another modern truecolor terminal for live recording. Alacritty is usable,
  but if matching Fira Code ligatures matters, choose an emulator with ligature support.
- **Color:** use a high-contrast opaque dark theme; keep `NO_COLOR` unset and use truecolor-capable `TERM`/`COLORTERM`.
- **Prompt:** use a minimal prompt such as `$ `. Hide setup in VHS with `Hide` / `Show`.
- **Notifications:** enable Do Not Disturb and capture only the app window.

For OBS, running ACE inside a fixed-size tmux pane is useful:

```bash
tmux new -s ace_demo -x 120 -y 40
sase ace --tab agents --refresh-interval 0
```

## ACE-Specific Gotchas

- **Alt-screen settling:** after launching ACE, wait 1-3 seconds or use a screen predicate such as `Wait+Screen
  /Agents/` before capturing the meaningful portion. Full-screen TUIs repaint asynchronously.
- **Keystrokes are invisible:** live recordings need `screenkey`/KeyCastr; silent VHS loops need captions or title
  callouts for important chords. Otherwise viewers cannot follow why the UI changed.
- **Demo state is the hard problem:** the existing `AcePage`, `patch_startup_loaders()`, and `DEFAULT_CHANGESPECS`
  fixtures are test-only. A real maintained demo should add an env-gated demo mode, for example `SASE_ACE_DEMO=1`,
  that seeds data behind the backend/adapter boundary instead of hardcoding data in Textual widgets.
- **Avoid live LLM latency:** seed believable completed/running agent state, or cut waits in edit. If a future demo mode
  simulates running work, it can show realistic displayed durations while keeping actual delays short.
- **Quit cleanly:** use `q`, not `Ctrl+C`, so the alt screen restores cleanly and the capture does not end on a
  traceback or half-restored terminal.

## VHS Tape Skeleton

This is a proposed skeleton; it depends on adding `demos/scripts/seed_sase_ace_demo`.

```tape
Output demos/out/sase_ace_agents.mp4
Output demos/out/sase_ace_agents.gif

Require bash
Require sase
Require ffmpeg
Require ttyd

Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 22
Set Width 1280
Set Height 720
Set Theme "github-dark"
Set TypingSpeed 75ms
Set Framerate 30
Set CursorBlink false

Hide
Type "export SASE_HOME=$(mktemp -d)"
Enter
Type "export SASE_TMPDIR=$(mktemp -d)"
Enter
Type "./demos/scripts/seed_sase_ace_demo"
Enter
Type "clear"
Enter
Show

Type "sase ace --tab agents --refresh-interval 0"
Enter
Wait+Screen /Agents/
Sleep 1s
Down 2
Sleep 700ms
Type "l"
Sleep 1s
Screenshot demos/out/sase_ace_agents.png
Sleep 1s
Type "q"
```

VHS tips:

- Use `Require` for every assumed binary so render machines fail early.
- Use `Hide` / `Show` for setup and seeding.
- Prefer `Wait+Screen /regex/` plus a short settling sleep over blind sleeps alone.
- Render MP4 and GIF, but publish MP4 wherever possible. GIF is mainly for README/social fallbacks.
- Inspect output for xterm.js rendering drift; VHS is not Bryan's real terminal emulator.

Post-process with FFmpeg/gifsicle from a `just` recipe:

```bash
ffmpeg -i demos/out/sase_ace_agents.mp4 \
  -vf "scale=1280:-2:flags=lanczos" \
  -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart \
  -y demos/out/sase_ace_agents_web.mp4

ffmpeg -i demos/out/sase_ace_agents.gif -filter_complex \
  "[0:v]scale=1000:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=sierra2_4a" \
  -r 12 -y demos/out/sase_ace_agents_small.gif

gifsicle -O3 --lossy=80 \
  -o demos/out/sase_ace_agents_small.gif \
  demos/out/sase_ace_agents_small.gif
```

## Output Targets

- **GitHub README:** GIF/image uploads are capped at 10 MB; videos are 10 MB on free plans or 100 MB on paid plans.
  Use optimized GIF only for very short autoplay loops. Prefer H.264 MP4 for quality-per-byte, or a poster image
  linking to YouTube/docs for longer videos.
- **Docs/blog:** MP4 or WebM plus a sharp poster PNG/SVG. Use the Textual screenshot lane for posters.
- **YouTube:** MP4, H.264, AAC-LC or Opus audio, 48 kHz sample rate, Fast Start metadata.
- **Social:** MP4 usually beats GIF for quality and size. Export a square or vertical crop only after the horizontal
  master exists.
- **Developer docs:** asciinema player or SVG-preview-link to hosted asciicast; agg GIF fallback when the site cannot
  embed the player.

## Demo Content Recommendations

Strong public beats:

- Open from the shell so viewers see this is command-line-native.
- Show agent observability: current runs, statuses, prompts, files, and outcomes.
- Show coordination: move from an agent to the related ChangeSpec/plan state.
- Show launch ergonomics: start a safe new agent or show the prompt flow.
- Show durability: exit/reopen ACE or briefly show that CLI state agrees with ACE.

Avoid in the first video:

- Deep configuration panels unless the video is about configuration.
- Long waits for model output.
- Real project names, prompts, chat snippets, local paths, notification text, or PR metadata.
- Tiny text. Most terminal demos fail from unreadability before they fail from tooling.

## Checklist

Before capture:

- Fresh `SASE_HOME` and seeded demo data.
- Terminal geometry fixed and tested.
- Font/theme/prompt profile selected.
- Notifications disabled.
- Secrets and personal project state absent.
- Mic levels checked with a 10-second sample.
- Dry run completed without narration.

During capture:

- Pause briefly after each major screen change.
- Move slower than normal keyboard speed; viewers process video slower than users operate TUIs.
- If narration goes wrong, pause, restate, and keep going; cut it later.
- Do not interact with unrelated windows.

After capture:

- Watch at 50% size with audio off to test readability.
- Listen without watching to test whether narration carries the story.
- Make sure the first meaningful ACE screen appears in the first five seconds.
- Export a master MP4, compressed web MP4, poster PNG/SVG, and GIF/asciinema only when the channel needs them.

## Implementation Recommendations

1. Add `demos/scripts/seed_sase_ace_demo`. Seed 4-8 ChangeSpecs and 2-4 agent runs with fake but realistic state. This
   supports OBS, VHS, asciinema, screenshots, and future release media.
2. Add one VHS tape and a `just demo-video` recipe that runs VHS plus FFmpeg/gifsicle post-processing.
3. Add an env-gated `SASE_ACE_DEMO` path if demos become maintained assets. Put seeded demo data behind the
   backend/adapter boundary so the demo can double as a smoke/integration path, not a UI-only mock.
4. Add `demos/README.md` documenting font, geometry, theme, clip naming, export targets, and privacy rules.
5. Record the narrated OBS walkthrough only after the silent loop proves the story.

## Sources

- Prior local research: `sdd/research/202606/tui_screenshots_and_demo_videos.md`
- Repo grounding: `sase ace --help`, `src/sase/default_config.yml`, `src/sase/ace/testing/__init__.py`,
  `memory/build_and_run.md`, `memory/rust_core_backend_boundary.md`
- VHS README and tape reference: <https://github.com/charmbracelet/vhs/blob/main/README.md>
- VHS `v0.11.0` release: <https://github.com/charmbracelet/vhs/releases/tag/v0.11.0>
- asciinema quick start: <https://docs.asciinema.org/manual/cli/quick-start/>
- asciinema `v3.2.1` release: <https://github.com/asciinema/asciinema/releases/tag/v3.2.1>
- asciinema 3.0 notes: <https://blog.asciinema.org/post/three-point-o/>
- agg usage: <https://docs.asciinema.org/manual/agg/usage/>
- agg `v1.9.0` release: <https://github.com/asciinema/agg/releases/tag/v1.9.0>
- OBS download/release status: <https://obsproject.com/download>,
  <https://github.com/obsproject/obs-studio/releases/tag/32.1.2>
- Screen Studio: <https://screen.studio/>
- Descript: <https://www.descript.com/>
- DaVinci Resolve: <https://www.blackmagicdesign.com/products/davinciresolve>
- GitHub attachment limits: <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files>
- YouTube recommended upload encoding settings: <https://support.google.com/youtube/answer/1722171?hl=en>
