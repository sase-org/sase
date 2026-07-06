# SASE Demo Videos

This directory contains scripted demo captures for SASE. The checked-in artifacts are the scripts and VHS tapes;
rendered media belongs in `demos/out/` and is intentionally ignored.

## Prerequisites

- `vhs`
- `ttyd`
- `ffmpeg`
- `git`
- the repo virtualenv installed with `just install`

The prompt-input demo prepends `.venv/bin` to `PATH` during tape setup so the rendered clip uses the checked-out SASE
code. `ttyd` must still be available on the outer `PATH` because VHS checks it before the tape setup commands run.

## Layout

- `scripts/` contains deterministic seeders for fake, privacy-safe demo state.
- `tapes/` contains VHS source files.
- `casts/` is reserved for asciinema captures.
- `out/` contains generated GIF, MP4, and poster PNG files.

## Regenerating

`demos/scripts/seed_sase_ace_demo` creates the fake HOME, SASE_HOME, local bare-git project, terminal agent artifacts,
and curated xprompts used by the tape.

Run:

```bash
just demo-video
```

The tape writes:

- `demos/out/sase_ace_prompt_input.gif`
- `demos/out/sase_ace_prompt_input.mp4`
- `demos/out/sase_ace_prompt_input.png`

The seed data is fictional and hermetic. It sets both `HOME` and `SASE_HOME`, then runs ACE from a seeded fake workspace
so prompt `@` file completion never exposes real local project paths. Keep future demos on the same pattern: fixed data,
fixed geometry, no live agent submission, and no personal project names.

Future compression work can add a small `ffmpeg`/`gifsicle` post-processing recipe after `gifsicle` is available.
