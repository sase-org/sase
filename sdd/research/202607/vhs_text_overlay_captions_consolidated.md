# VHS Text Overlays for SASE Demo GIFs

Date: 2026-07-08

## Request

SASE uses Charm VHS tapes to generate ACE TUI demo GIFs and MP4s. The missing
capability is explanatory text that appears at specific points in the rendered
media, without changing the TUI itself. This note consolidates the two prior
research passes, verifies their claims against the current repo and upstream
sources, and ends with a recommended implementation.

## Verified Current State

SASE's demo pipeline is small and explicit:

- `demos/tapes/` contains five VHS tapes:
  `sase_ace_prompt_input`, `sase_ace_agents_observability`,
  `sase_ace_prompt_history_stash`, `sase_ace_prs_pipeline`, and
  `sase_ace_multi_model_fanout`.
- `just demos` runs `vhs demos/tapes/<name>.tape` once per tape, then updates
  `demos/out/last_generated_date.txt` and offers to commit `demos/out/`.
- Each tape currently emits both `demos/out/<name>.mp4` and
  `demos/out/<name>.gif`.
- The tapes use a consistent visual envelope: `Set Width 1920`,
  `Set Height 1080`, `Set FontFamily "Fira Code"`, `Set Framerate 30`, GitHub
  Dark, hidden setup/teardown via `Hide`/`Show`, and many `Wait+Screen` checks.
- `demos/README.md` already names ffmpeg/gifsicle post-processing as a future
  extension point.

Local toolchain verification on 2026-07-08:

- `vhs version v0.11.0 (c6af91a)`.
- `ffmpeg version 7.1.5-0+deb13u1`, built with `--enable-libass`,
  `--enable-libfreetype`, `--enable-libfontconfig`, and `--enable-librsvg`.
- `ffmpeg -filters` includes `ass`, `subtitles`, `drawtext`, `overlay`,
  `palettegen`, and `paletteuse`.
- ImageMagick is installed; `gifsicle` is not.
- `vhs validate` rejects `Subtitle "hello world"` as an invalid command.
- `demos/out/sase_ace_prompt_input.mp4` reports `r_frame_rate=25/1` and
  `duration=28.840000`, despite the tape setting `Set Framerate 30`.

The frame-rate mismatch matters: caption timing should be measured from the
rendered artifact, not inferred from the tape's nominal framerate.

## Upstream VHS State

Released VHS does not currently solve this. The current upstream README command
reference lists `Output`, `Require`, `Set`, typing/key commands, `Sleep`,
`Wait`, `Hide`, `Show`, `Screenshot`, clipboard, `Source`, and `Env`, but no
caption, subtitle, or overlay command. It does support multiple outputs,
including `.gif`, `.mp4`, `.webm`, and a PNG frame directory.

As of this research, GitHub releases show `v0.11.0` as the latest VHS release.
That matches the installed binary and explains why native captions are not
available locally.

Upstream activity is relevant, but not ready to depend on:

- Issue #735, "Allow specifying subtitles in tape files", is open. It asks for
  tape-stored subtitles because external subtitle timing is difficult.
- PR #716 added a generic `Overlay[@<time>]` command, but it is closed.
- PR #719 is open and more directly matches SASE's need. It adds keystroke
  captions and an `Overlay[@duration] "text"` command, implemented by generating
  ASS subtitle events and burning them with ffmpeg. It also exposes style knobs
  for font, color, box, margins, alignment, and multiline text.

The important takeaway from upstream is architectural, not dependency-related:
the likely right primitive is timed subtitle/overlay events burned into the
video, not custom terminal rendering.

## Options

| Approach | Fit for SASE | Notes |
| --- | --- | --- |
| Render text inside ACE | Poor | Avoid adding demo-only UI state or making demos less faithful to the real TUI. |
| Wait for native VHS captions | Poor now, attractive later | Issue #735 and PR #719 show direction, but no released support exists. A VHS fork would add setup and maintenance for a docs feature. |
| ffmpeg `drawtext` | Good for a spike | It can draw timed text with `enable='between(t,start,end)'`, but escaping and styling become brittle as cues grow. |
| ffmpeg + ASS/libass | Best MVP | Clean sidecar data, strong styling, multiline text, fades, boxes, alignment, and a path that matches PR #719's implementation model. |
| PNG frame compositing | Later fallback | Maximum control for arrows/highlights/animations, but more code and heavier artifacts than needed for captions. |

## Timing Strategy

The hard part is not drawing text; it is syncing text to the right demo moment.
SASE tapes are event-driven through `Wait+Screen`, so the wall-clock timestamp
of a semantic moment can move when the tape or renderer changes.

Use two phases:

1. Start with absolute timestamps.
   A sidecar cue such as `at: 12.0s` / `until: 15.5s` is simple, reviewable,
   and good enough for stable demos. Authors can calibrate by scrubbing the
   rendered MP4 or extracting frames with ffmpeg.

2. Add marker-based anchoring only if drift becomes painful.
   VHS already has `Screenshot examples/screenshot.png`, which captures the
   current frame. A later renderer can allow `at: marker:history_opened`, render
   marker screenshots during the tape, then locate the nearest matching frame in
   the MP4/GIF by image distance. Do not require byte equality; H.264, yuv420p,
   antialiasing, and GIF palette conversion make exact comparison fragile. Use
   lowest-MSE or SSIM within a bounded search window and fail loudly if the
   match confidence is poor.

## Proposed MVP Design

Keep stock VHS. Add a SASE-local post-processing step under `demos/`:

1. Render the tape with VHS as today.
2. If a sidecar exists, generate a temporary `.ass` file from it.
3. Burn the `.ass` into the MP4 using ffmpeg's `ass` or `subtitles` filter.
4. Generate the captioned GIF from the captioned MP4 using
   `palettegen`/`paletteuse`, so MP4 and GIF stay visually consistent.

Use sidecars next to the tapes:

```text
demos/tapes/sase_ace_prompt_input.captions.yml
demos/tapes/sase_ace_agents_observability.captions.yml
```

Suggested schema:

```yaml
version: 1
defaults:
  font: "Fira Code"
  size: 40
  position: lower-third
  margin_x: 80
  margin_y: 90
  fade_ms: 250
  box_color: "#000000"
  box_opacity: 0.70
  text_color: "#ffffff"
cues:
  - at: 2.0s
    until: 4.5s
    text: "Recall prior prompts instantly"
  - at: 12.0s
    until: 15.0s
    position: top-right
    text: "One prompt becomes a launch preview"
```

Example generated ASS shape:

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lower,Fira Code,40,&H00FFFFFF,&H00000000,&HB0000000,-1,3,8,0,2,80,80,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.00,0:00:04.50,Lower,,0,0,0,,{\fad(250,250)}Recall prior prompts instantly
```

Example commands:

```bash
ffmpeg -y -i demos/out/name.mp4 \
  -vf "ass=/tmp/name.captions.ass" \
  -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -movflags +faststart \
  demos/out/name.captioned.mp4

ffmpeg -y -i demos/out/name.captioned.mp4 \
  -filter_complex "[0:v]fps=25,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
  demos/out/name.captioned.gif
```

Use the measured source FPS when generating GIFs. Hard-coding `fps=30` would
contradict the verified 25 FPS output for the current prompt-input demo.

Implementation can be a small Python script, for example
`demos/scripts/render_captions.py`, because it needs YAML parsing, timestamp
validation, ASS escaping, `ffprobe` duration/FPS checks, and subprocess calls.
It belongs in this repo rather than `sase-core`: demo captioning is build-time
presentation tooling, not shared runtime domain behavior.

## Risks and Guardrails

- Absolute cue drift: keep captions sparse, retime after tape edits, and add
  marker anchoring only when the manual retiming cost becomes real.
- Font drift: make the script fail or warn if Fira Code cannot be resolved.
  Captioned artifacts should use the same font assumptions as the tapes and
  visual snapshot setup.
- Shell escaping: never construct long `drawtext` strings for real use. Generate
  ASS files and pass file paths to ffmpeg.
- Output policy: decide whether `*.captioned.{mp4,gif}` is committed alongside
  clean artifacts, replaces clean artifacts when sidecars exist, or is generated
  on demand. For reviewability, separate `*.captioned.*` files are safest first.
- Future upstream support: if PR #719 or a successor ships, SASE can either keep
  sidecars or mechanically translate cues into native `Overlay` tape commands.

## Sources

- Charm VHS README and command reference:
  https://github.com/charmbracelet/vhs/blob/main/README.md
- Charm VHS releases, latest `v0.11.0`:
  https://github.com/charmbracelet/vhs/releases
- VHS issue #735, "Allow specifying subtitles in tape files":
  https://github.com/charmbracelet/vhs/issues/735
- VHS PR #716, closed generic overlay command:
  https://github.com/charmbracelet/vhs/pull/716
- VHS PR #719, open captions/overlays via ASS subtitles:
  https://github.com/charmbracelet/vhs/pull/719
- FFmpeg filter docs for `ass`, `subtitles`, `drawtext`, timeline editing, and
  GIF palette filters:
  https://ffmpeg.org/ffmpeg-filters.html

## Recommended Solution

Implement a SASE-local ffmpeg/libass caption post-processor driven by
per-tape `*.captions.yml` sidecars. Keep the stock released VHS binary and the
current tapes. After each VHS render, generate an ASS subtitle file, burn it into
`demos/out/<name>.captioned.mp4`, and derive
`demos/out/<name>.captioned.gif` from that annotated MP4 using
`palettegen`/`paletteuse`.

Ship Phase 1 with absolute timestamps because it is simple, reviewable, and
works with the verified local toolchain today. Preserve clean uncaptioned
outputs at first. Add marker-based timing only if cue drift becomes a repeated
maintenance problem. This gives SASE custom explanatory text now, avoids a VHS
fork, and stays aligned with the direction of upstream VHS overlay work if it
lands later.
