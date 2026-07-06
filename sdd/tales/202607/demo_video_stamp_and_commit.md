---
create_time: 2026-07-06 19:14:36
status: done
prompt: sdd/prompts/202607/demo_video_stamp_and_commit.md
---
# Plan: `just demo-video` — date stamp, no PNG, and an opt-in commit prompt

## Problem / Goals

`just demo-video` currently does one thing: run `vhs demos/tapes/sase_ace_prompt_input.tape`. The rest of the
regeneration workflow is manual and drifted last time it was exercised:

1. `demos/out/last_generated_date.txt` was created and updated **by hand** (current content: `2026-07-06T18:37:35`, i.e.
   `%Y-%m-%dT%H:%M:%S` local time). The recipe should stamp this file automatically after a successful render.
2. The tape still captures a poster PNG (`Screenshot demos/out/sase_ace_prompt_input.png`). The PNG is no longer wanted
   — only the GIF and MP4 are kept (they are git-tracked as of commit `9232d1579`; the PNG sits untracked in the working
   tree).
3. After regenerating, committing the refreshed `demos/out/` artifacts is a manual step. The recipe should prompt `y/n`
   to commit them, and support `-y|--yes` to auto-approve (verified: `just` passes `-y`/`--yes` through to
   `[positional-arguments]` recipes without complaint).

## Current State (facts gathered)

- `Justfile` recipe (lines ~249-251):

  ```just
  # Render the scripted ACE prompt-input demo video.
  demo-video:
      vhs demos/tapes/sase_ace_prompt_input.tape
  ```

- `demos/tapes/sase_ace_prompt_input.tape` declares `Output` GIF + MP4 at the top and takes the poster PNG mid-tape:

  ```
  Wait+Screen /Launch all/
  Sleep 1.5s
  Screenshot demos/out/sase_ace_prompt_input.png
  Sleep 1s
  Escape
  ```

- Git tracking: `demos/out/sase_ace_prompt_input.gif`, `.mp4`, and `last_generated_date.txt` are **tracked**; commit
  `9232d1579` deleted `demos/out/.gitignore`. The `.png` is untracked. `demos/README.md` still claims rendered media in
  `demos/out/` "is intentionally ignored" and lists the PNG as a tape output — both stale.
- The `Justfile` has no `set shell` directive, so plain recipes run under `sh` (dash on Debian) — `read -p` is not
  available there. A shebang-bash recipe body is the clean way to get the interactive prompt.
- `sdd/tales/202607/sase_ace_demo_video.md` mentions the poster PNG, but tales are historical records — do not edit.

## Design

### 1. New `demo-video` recipe (Justfile)

Replace the one-liner with a `[positional-arguments]` shebang-bash recipe:

```just
# Render the scripted ACE prompt-input demo video (GIF + MP4), stamp
# demos/out/last_generated_date.txt, and offer to commit the results.
# Pass -y/--yes to skip the commit confirmation prompt.
[positional-arguments]
demo-video *args:
    #!/usr/bin/env bash
    set -euo pipefail
    auto_yes=false
    for arg in "$@"; do
        case "$arg" in
            -y|--yes) auto_yes=true ;;
            *) printf 'error: unknown argument: %s\n' "$arg" >&2; exit 2 ;;
        esac
    done
    vhs demos/tapes/sase_ace_prompt_input.tape
    date +%Y-%m-%dT%H:%M:%S > demos/out/last_generated_date.txt
    if ! git status --porcelain -- demos/out | grep -q .; then
        printf '[demo-video] demos/out is unchanged; nothing to commit.\n'
        exit 0
    fi
    git status --short -- demos/out
    if [ "$auto_yes" = true ]; then
        reply=y
    elif [ -t 0 ]; then
        read -r -p "Commit regenerated demos/out artifacts? [y/N] " reply
    else
        reply=n   # non-interactive (e.g. agent/CI) => never auto-commit
    fi
    case "$reply" in
        y|Y)
            git add -A -- demos/out
            git commit -m "doc: Regenerate ACE prompt-input demo artifacts" -- demos/out
            ;;
        *) printf '[demo-video] Skipping commit; demos/out changes left in the working tree.\n' ;;
    esac
```

Key behaviors:

- **Stamp after success**: `set -e` means the date file is only written when `vhs` exits 0 ("once all artifacts have
  been generated"). Local time, `%Y-%m-%dT%H:%M:%S`, matching the manual precedent.
- **Commit scope is `demos/out` only**: `git add -A -- demos/out` + pathspec-limited `git commit -- demos/out` so a
  dirty tape/README or unrelated staged changes are never swept into the artifact commit.
- **Safe defaults**: no TTY on stdin → treat as "n" (regenerate but leave the commit to the caller). `-y|--yes` is the
  only auto-approve path. Unknown args error out rather than being silently ignored.
- **No-op detection**: if `demos/out` is byte-identical after the render (unlikely, since the date stamp changes, but
  possible if `vhs` fails midway is excluded by `set -e`), say so instead of prompting.

### 2. Drop the PNG (tape + working tree)

- In `demos/tapes/sase_ace_prompt_input.tape`, delete the `Screenshot demos/out/sase_ace_prompt_input.png` line and
  merge the adjacent `Sleep 1.5s` / `Sleep 1s` into a single `Sleep 2.5s` so the rendered video timing is unchanged.
- Delete the stale untracked `demos/out/sase_ace_prompt_input.png` from the working tree (it is untracked, so a plain
  `rm` suffices — no history rewrite involved).

### 3. Documentation refresh (`demos/README.md`)

- Fix the stale intro: rendered media in `demos/out/` is now **committed**, not ignored.
- Update the "The tape writes:" list to GIF + MP4 only, and document `demos/out/last_generated_date.txt` as an
  auto-written stamp.
- Update the layout bullet ("out/ contains generated GIF, MP4, and poster PNG files") to drop the PNG.
- Document the new recipe behavior: the y/N commit prompt, `just demo-video -y` / `--yes`, and that non-interactive runs
  never commit.

## Files Touched

| File                                     | Change                                                     |
| ---------------------------------------- | ---------------------------------------------------------- |
| `Justfile`                               | Rewrite `demo-video` recipe (args, stamp, prompt, commit)  |
| `demos/tapes/sase_ace_prompt_input.tape` | Remove `Screenshot` line; merge adjacent sleeps            |
| `demos/README.md`                        | Drop PNG references; document stamp file, prompt, and `-y` |
| `demos/out/sase_ace_prompt_input.png`    | Delete (untracked leftover from the previous render)       |

No Python/Rust source changes; the Rust core boundary is not involved.

## Verification

1. **Arg plumbing without rendering**: prepend a stub `vhs` to `PATH` (a tiny script that touches the GIF/MP4 paths and
   exits 0) and confirm:
   - `just demo-video` (stdin a TTY) renders, stamps the date file, and prompts; answering `n` leaves the working tree
     dirty and makes no commit.
   - `echo | just demo-video` (non-TTY) skips the commit without hanging.
   - `just demo-video --bogus` exits 2 with a usage error.
   - `just demo-video -y` and `--yes` take the commit path — exercise this in a **throwaway clone** of the repo (e.g.
     under `mktemp -d`) so no real commit is created outside the normal commit workflow; confirm the commit contains
     only `demos/out/` paths even when an unrelated file is staged.
2. **Date format**: assert the stamp matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$`.
3. **Real render (if `vhs`/`ttyd`/`ffmpeg` are available)**: run `just demo-video`, answer `n`, and confirm only the
   GIF/MP4/date-stamp change — no new PNG appears.
4. `just check` (per repo policy for file changes), noting the known pre-existing failures documented in memory.

## Out of Scope

- Rewriting git history to purge the previously-generated PNG (it was never committed).
- Editing `sdd/tales/202607/sase_ace_demo_video.md` (historical record).
- GIF compression post-processing (tracked separately in the demos README as future work).
