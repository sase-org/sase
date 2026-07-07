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

The recipe renders both tapes, updates `demos/out/last_generated_date.txt` after successful renders, and then prompts to
commit the refreshed `demos/out/` artifacts. Pass `-y` or `--yes` to commit without prompting. Non-interactive runs
never commit automatically.

The prompt-input tape writes:

- `demos/out/sase_ace_prompt_input.gif`
- `demos/out/sase_ace_prompt_input.mp4`

The Agents observability tape shows many seeded agent runs from one keyboard-driven control surface and writes:

- `demos/out/sase_ace_agents_observability.gif`
- `demos/out/sase_ace_agents_observability.mp4`

The recipe writes:

- `demos/out/last_generated_date.txt`

The seed data is fictional and hermetic. It sets both `HOME` and `SASE_HOME`, then runs ACE from a seeded fake workspace
so prompt `@` file completion never exposes real local project paths. Keep future demos on the same pattern: fixed data,
fixed geometry, no live agent submission, and no personal project names.

Future compression work can add a small `ffmpeg`/`gifsicle` post-processing recipe after `gifsicle` is available.
