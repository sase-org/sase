# VHS Text Overlays for SASE Demo GIFs

Date: 2026-07-08

## Question

SASE uses Charm VHS tapes to generate scripted ACE TUI demos. The current gap is adding explanatory text to the GIF/MP4 at specific moments without changing the TUI itself. This note evaluates practical implementation paths and recommends a direction.

## Current SASE Demo Pipeline

SASE keeps demo sources under `demos/tapes/` and checked-in rendered media under `demos/out/`. The `just demos` recipe currently runs `vhs` once per tape and lets each tape emit both MP4 and GIF outputs directly.

The tapes are deterministic and use a stable visual envelope:

- `Set Width 1920`, `Set Height 1080`, `Set Framerate 30`
- Fira Code, GitHub Dark, hidden setup/teardown via `Hide`/`Show`
- `Wait+Screen` and explicit `Sleep` calls to stabilize the TUI before visible beats

Local tool check on 2026-07-08:

- `vhs version v0.11.0 (c6af91a)`
- `ffmpeg version 7.1.5-0+deb13u1`
- local ffmpeg has the relevant filters: `ass`, `subtitles`, and `drawtext`

That means SASE can burn text overlays into rendered video locally without replacing the installed VHS binary.

## What VHS Supports Today

VHS v0.11.0 does not have a first-class text annotation or overlay command in the released tape DSL. The official command reference lists outputs, requirements, settings, typing/key commands, sleep/wait, hide/show, screenshots, clipboard, `Source`, and `Env`, but no overlay/caption primitive.

VHS can emit several formats from one tape, including GIF, MP4, WebM, and a PNG frame directory. The PNG frame output is useful if SASE ever wants frame-level compositing, but the current pipeline only uses MP4/GIF.

Implication: with stock VHS, custom explanatory text must either be rendered inside the terminal/TUI before capture, or added after VHS produces media.

## Upstream Prior Art

There is active upstream work in Charm VHS that directly matches this problem:

- PR #716, "feat: add Overlay command for text annotations during recording", proposed a generic `Overlay[@<time>] "<string>"` command drawn on the terminal canvas. It was closed after discussion and after a broader approach appeared.
- PR #719, "feat: add keystroke captions and overlays for recorded videos", is open as of this research. It adds `CaptionOn`, `CaptionOff`, and `Overlay[@duration] "text"` commands. The implementation generates ASS subtitle events and burns them into video through ffmpeg's `ass` filter. It also exposes style settings such as overlay font, font size, font color, box color/opacity/padding, alignment, and margins.

That upstream direction is important: the strongest implementation pattern is not ad hoc image drawing. It is timed subtitle generation plus ffmpeg burn-in.

## Implementation Options

### 1. Render Text Inside the TUI

SASE could add a demo-only ACE banner/toast, controlled by an environment variable or fake demo state.

Pros:

- No video post-processing.
- Text timing can be driven by the app state or keyboard actions.
- It would appear in visual snapshot tests if desired.

Cons:

- It pollutes product UI code for a documentation-only concern.
- It cannot annotate outside the terminal viewport.
- It makes demos less faithful to the real TUI.
- It does not solve VHS generally.

This is a poor fit unless a demo needs to showcase an actual in-product notification.

### 2. Post-Process With `drawtext`

ffmpeg's `drawtext` filter can draw text over video frames with font, color, box, and coordinate controls. It also supports timeline gating through filter expressions such as `enable='between(t,12.5,16.0)'`.

Example shape:

```bash
ffmpeg -i raw.mp4 \
  -vf "drawtext=font='Fira Code':fontsize=38:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=18:x=w-text_w-36:y=h-text_h-36:enable='between(t,12.5,16.0)'" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p \
  annotated.mp4
```

Pros:

- Smallest proof of concept.
- Uses an ffmpeg feature likely present in most development environments.
- Fine for one or two simple labels.

Cons:

- Many overlays become a long, fragile filter string.
- Shell/filter escaping gets painful for quotes, colons, commas, paths, and multi-line text.
- Layout features are basic compared with ASS subtitles.
- GIF output still needs a second encode from the annotated MP4.
- Absolute timestamps must be maintained manually.

This is useful for a spike, but not the implementation I would keep.

### 3. Post-Process With ASS Subtitle Overlays

SASE can keep stock VHS and add a small demo renderer that:

1. Renders the VHS tape to a temporary raw MP4.
2. Reads a sidecar overlay spec.
3. Generates a temporary `.ass` subtitle file.
4. Burns the ASS overlay into the MP4 with ffmpeg's `ass` filter.
5. Generates the GIF from the annotated MP4 so MP4/GIF show the same overlays.

Suggested sidecar location:

```text
demos/overlays/sase_ace_prompt_input.yml
demos/overlays/sase_ace_agents_observability.yml
```

Suggested sidecar shape:

```yaml
version: 1
defaults:
  font: "Fira Code"
  font_size: 34
  alignment: "bottom-right"
  margin_right: 36
  margin_vertical: 34
  box_color: "#0d1117"
  box_opacity: 0.82
  box_padding: 16
  font_color: "#f0f3f6"
overlays:
  - start: 8.2s
    duration: 3.5s
    text: "Prompt completion expands #git:nova and file paths."
  - start: 24.6s
    duration: 4s
    alignment: "top-right"
    text: "Launch review shows all generated agent slots."
```

The generated ASS should set `PlayResX: 1920` and `PlayResY: 1080` to match the tape resolution, define a small number of stable styles, then emit one `Dialogue:` row per overlay. ASS also handles multiline text via `\N`, alignment via numpad-style alignment values, margins, and styled boxes.

Example burn-in command shape:

```bash
ffmpeg -y -i raw.mp4 \
  -vf "ass=overlays.ass" \
  -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
  demos/out/sase_ace_prompt_input.mp4
```

Then generate the GIF from the annotated MP4, preferably with a palette pass:

```bash
ffmpeg -y -i demos/out/sase_ace_prompt_input.mp4 \
  -filter_complex "[0:v] fps=30,split [a][b];[a] palettegen=max_colors=256 [p];[b][p] paletteuse=dither=bayer" \
  demos/out/sase_ace_prompt_input.gif
```

Pros:

- Keeps using released, package-manager VHS.
- Aligns with upstream PR #719's design, making future migration easier.
- Handles styling, multiline text, boxes, margins, and alignment cleanly.
- Avoids `drawtext` filter-string explosion.
- Produces identical annotations in MP4 and GIF when GIF is derived from the annotated MP4.
- Can fail early if `ffmpeg -filters` lacks `ass`.

Cons:

- Overlay timing is explicit seconds, not semantic "at this tape command" timing.
- If a `Wait+Screen` duration changes materially, timestamps may need adjustment.
- Requires a small wrapper script and one new sidecar format.

The timing downside is manageable for SASE because the demos are already deterministic and use explicit sleeps around visible beats. A `--timecode` debug mode can make timestamp calibration cheap:

```bash
ffmpeg -y -i raw.mp4 \
  -vf "drawtext=font='Fira Code':fontsize=32:fontcolor=yellow:box=1:boxcolor=black@0.65:x=20:y=20:text='%{pts\\:hms}'" \
  debug-timecode.mp4
```

### 4. Frame-by-Frame Compositing

VHS can output a PNG frame directory. SASE could render frames, composite text with Pillow or ImageMagick, then encode MP4/GIF.

Pros:

- Maximum control over typography, boxes, animations, arrows, highlights, and non-text callouts.
- Avoids ffmpeg ASS/drawtext escaping.
- Easy to test individual frames if SASE wants visual assertions around overlays.

Cons:

- Much more custom code.
- Larger temporary artifacts.
- Need to own video/GIF encoding details.
- Overkill for simple explanatory captions.

This is the right fallback only if SASE needs animated callouts or non-subtitle graphics that ASS cannot express.

### 5. Use a VHS Fork or Wait for Upstream Overlay Support

SASE could build a pinned VHS fork with PR #719, or later move to released upstream support if it merges.

Pros:

- Best authoring experience: `Overlay@4s "..."` can live directly in the tape at the semantic moment.
- VHS knows the current frame, so `Wait+Screen` timing is naturally correct.
- No separate sidecar timestamps.
- Same direction as active upstream work.

Cons:

- A fork makes `just demos` depend on a custom Go tool instead of normal `vhs`.
- PR #719 is still open, and its syntax may change before merge.
- SASE would inherit maintenance for a documentation feature.
- Contributors need one more nonstandard setup step.

This is attractive long-term, but I would not make SASE depend on an unreleased VHS fork for the first implementation.

## Sources

- Charm VHS README and command reference: <https://github.com/charmbracelet/vhs>
- VHS v0.11.0 Arch manual page: <https://man.archlinux.org/man/vhs.1.en>
- VHS PR #716, generic overlay command: <https://github.com/charmbracelet/vhs/pull/716>
- VHS PR #719, captions and overlay command using ASS subtitles: <https://github.com/charmbracelet/vhs/pull/719>
- FFmpeg filter documentation, `drawtext`: <https://ffmpeg.org/ffmpeg-filters.html#drawtext-1>
- FFmpeg filter documentation, `ass`: <https://ffmpeg.org/ffmpeg-filters.html#ass>
- FFmpeg filter documentation, `subtitles`: <https://ffmpeg.org/ffmpeg-filters.html#subtitles-1>
- FFmpeg filter documentation, timeline editing: <https://ffmpeg.org/ffmpeg-filters.html#Timeline-editing>

## Recommended Solution

Implement a SASE-local ASS overlay post-processor first. Keep the installed VHS binary stock, add `demos/overlays/*.yml` sidecars, and replace the body of `just demos` with a wrapper that renders raw MP4 from each tape, burns ASS overlays when a sidecar exists, then derives the GIF from the annotated MP4.

This gives SASE custom explanatory text quickly with the dependencies it already has, avoids carrying a VHS fork, and follows the same technical model as upstream PR #719. Use syntax and option names that mirror PR #719 where possible (`Overlay`, alignment, font/color/box settings) so that if VHS later ships native overlays, the sidecars can be migrated into the tapes with a mechanical conversion.
