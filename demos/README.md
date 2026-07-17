# SASE Demo Videos

This directory contains scripted demo captures for SASE. The checked-in artifacts are the scripts, VHS tapes, and
generated media under `demos/out/`.

## Prerequisites

- `vhs`
- `ttyd`
- `ffmpeg`
- `git`
- the repo virtualenv installed with `just install`

The demo tapes prepend `.venv/bin` to `PATH` during tape setup so the rendered clips use the checked-out SASE code.
`ttyd` must still be available on the outer `PATH` because VHS checks it before the tape setup commands run.

## Layout

- `scripts/` contains deterministic seeders for fake, privacy-safe demo state.
- `tapes/` contains VHS source files.
- `casts/` is reserved for asciinema captures.
- `out/` contains generated GIF, MP4, and metadata stamp files.

## Regenerating

`demos/scripts/seed_sase_ace_demo` creates the fake HOME, SASE_HOME, local bare-git project, terminal agent artifacts,
and curated xprompts used by the tape.

Run:

```bash
just demos
```

The recipe renders all tapes, post-processes their media, updates `demos/out/last_generated_date.txt` after successful
renders, and then prompts to commit the refreshed `demos/out/` artifacts. Pass `-y` or `--yes` to commit without
prompting. Non-interactive runs never commit automatically.

Every GIF is derived from its rendered MP4 with ffmpeg's `palettegen`/`paletteuse` filters at the frame rate measured by
`ffprobe`. Do not infer the output frame rate from `Set Framerate` in a tape: VHS can produce a different rate (the
current artifacts are 25 fps despite requesting 30 fps).

Every tape pins `COLORTERM=truecolor` and `TERM=xterm-256color`, then unsets `FORCE_COLOR` and `NO_COLOR` in its hidden
shell setup, matching the PNG visual-snapshot environment. Keep that environment setup in new tapes so Rich and Textual
preserve the theme and provider badge colors instead of disabling color or quantizing them to a nearly grayscale
256-color palette.

After post-processing, `scripts/check_demo_media` samples representative frames from every final GIF and requires mean
HSV saturation of at least 0.05. The guard runs automatically as part of `just demos` and fails the build if a terminal
environment change makes the demos nearly grayscale again. Run `just --justfile demos/Justfile check` to check existing
artifacts without rerendering them.

## Captions

Add an optional `tapes/<name>.captions.yml` sidecar to burn timed captions into a demo:

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

Cues use absolute timestamps, must be ordered without overlap, and must fit within the measured MP4 duration. Supported
positions are `lower-third`, `bottom-left`, `bottom-center`, `bottom-right`, `center`, `top-left`, `top-center`, and
`top-right`. Captions default to the intended visual language: Fira Code, white text, a 70%-opaque dark box, and 250 ms
fades. Keep demos sparse (no more than about five cues, generally 2.5–4 seconds each).

`scripts/postprocess_demo_media` generates a temporary ASS subtitle file and burns it with ffmpeg/libass. The final
captioned MP4 and its palette-derived GIF replace `out/<name>.mp4` and `out/<name>.gif` in place; no parallel
`*.captioned.*` artifacts are kept, so existing README and PyPI URLs remain stable. The command also supports
`--optimized-gif` (lanczos downscaling plus a reduced palette) and paired `--still`/`--still-at` flags for deterministic
README or blog derivatives. Run `just --justfile demos/Justfile postprocess` to reprocess existing MP4s without
rerunning VHS.

After any tape timing change, render the MP4, scrub or frame-step it to find the new semantic beats, and retime the
sidecar before committing media. The processor validates timing but cannot infer semantic events. It also requires
fontconfig to resolve the configured font exactly, preventing silent typography substitution.

The prompt-input tape writes:

- `demos/out/sase_ace_prompt_input.gif`
- `demos/out/sase_ace_prompt_input.mp4`

The Agents observability tape shows many seeded agent runs from one keyboard-driven control surface and writes:

- `demos/out/sase_ace_agents_observability.gif`
- `demos/out/sase_ace_agents_observability.mp4`

The prompt history and stash tape shows recall, search, stash, and restore inside the ACE prompt input and writes:

- `demos/out/sase_ace_prompt_history_stash.gif`
- `demos/out/sase_ace_prompt_history_stash.mp4`

The PR pipeline tape shows the ACE PRs tab ChangeSpec lifecycle, parent/child navigation, grouping, and folding, and
writes:

- `demos/out/sase_ace_prs_pipeline.gif`
- `demos/out/sase_ace_prs_pipeline.mp4`

The multi-model fan-out tape shows one prompt becoming three launch-previewed agents across Claude, Codex, and Gemini,
then stops at the Launch Approval modal without approving, and writes:

- `demos/out/sase_ace_multi_model_fanout.gif`
- `demos/out/sase_ace_multi_model_fanout.mp4`

The recipe writes:

- `demos/out/last_generated_date.txt`

The seed data is fictional and hermetic. It sets both `HOME` and `SASE_HOME`, then runs ACE from a seeded fake workspace
so prompt `@` file completion never exposes real local project paths. Keep future demos on the same pattern: fixed data,
fixed geometry, pinned seed directories, no live agent submission, and no personal project names. Tapes should disable
auto-refresh and axe (`--refresh-interval 0 -x`), hide startup and teardown capture with VHS `Hide`/`Show`, and export
`SASE_ACE_RELEASE_VERSION_TITLE=1` so editable installs render the clean release title in the ACE header.

Future compression work can add a small `ffmpeg`/`gifsicle` post-processing recipe after `gifsicle` is available.
