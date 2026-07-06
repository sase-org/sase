---
create_time: 2026-07-06 14:32:18
status: done
prompt: sdd/prompts/202607/sase_ace_demo_video.md
---
# Plan: First SASE Demo Video (VHS) — ACE Prompt Input Widget

## Goal

Create sase's first demo video using `vhs`, following the recommendations in
`sdd/research/202606/sase_ace_demo_video_tooling_consolidated.md`:

1. Initialize the `demos/` directory scaffold recommended by the research doc.
2. Add `demos/scripts/seed_sase_ace_demo` that seeds deterministic, fake-but-realistic demo data.
3. Author a VHS tape that shows off the most important features of the **prompt input widget** (`PromptInputBar` /
   `PromptTextArea`) in the ACE TUI.
4. Actually run `vhs` to produce `demos/out/sase_ace_prompt_input.gif` and `demos/out/sase_ace_prompt_input.mp4`.

## Key Findings (from research + codebase exploration)

### Tooling status on this machine

- `vhs v0.11.0` and `ffmpeg` are installed.
- **`ttyd` is NOT installed and vhs hard-fails without it** (verified with a probe tape: "ttyd is not installed").
  `gifsicle` is also missing, but it is optional polish, not required for this task.
- `sase` resolves both globally (`~/.local/bin/sase`) and in the repo venv (`.venv/bin/sase`). The tape should use the
  repo venv's `sase` (prepend `.venv/bin` to `PATH` in the hidden setup) so the demo reflects the checked-out code.

### How ACE data can be seeded (no code changes required)

- `SASE_HOME` is honored everywhere via `sase_home()` (`src/sase/core/paths.py`), **but** `CONFIG_DIR` is hard-coded to
  `~/.config/sase` from `HOME` (`src/sase/config/core.py`). → The seed environment must override **both `HOME` and
  `SASE_HOME`** to be hermetic and to inject demo xprompts/config deterministically.
- **Agents tab**: the Rust scanner (`scan_agent_artifacts`) walks
  `$SASE_HOME/projects/<proj>/artifacts/<workflow>/<YYYYmmddHHMMSS>/` and parses plain JSON markers (`agent_meta.json`,
  `done.json`, ...). When `$SASE_HOME/agent_artifact_index.sqlite` is absent, the loader falls back to a full source
  scan — so writing raw JSON files is enough. Field shapes are defined in `src/sase/core/agent_scan_wire_markers.py`,
  and `tests/agent_scan_golden/fixture_builder.py` is a production-shaped template to model.
- **Running agents are filtered unless their PID is alive** — so the seeder will create only terminal-state agents
  (DONE/FAILED, which are always visible per `DISMISSABLE_STATUSES`).
- **ChangeSpecs tab**: discovered from `$SASE_HOME/projects/<name>/<name>.sase` text files (format per
  `tests/core_golden/myproj.sase`); a project is "registered" simply by that file existing, and lifecycle defaults to
  active.
- **xprompts for `#` completion**: bundled internal xprompts (e.g. `#split_file`, `#coder`) load with zero seeding;
  demo-specific xprompts can be added via an `xprompts:` block in the throwaway `$HOME/.config/sase/sase.yml` (or
  `$HOME/xprompts/*.md`). Demo xprompts should declare `input:` args so the argument-hint panel has something to show.
- No `SASE_ACE_DEMO` mode, demo script, or `just` demo recipe exists today; `AcePage` / `DEFAULT_CHANGESPECS` are
  in-memory test patches, not usable for a live `sase ace` run.

### Prompt input widget — the features worth showing

From `src/sase/ace/tui/widgets/prompt_input_bar.py` + `prompt_text_area.py` and the default keymap
(`src/sase/default_config.yml`):

- Opened from the Agents tab with `space` (home-mode prompt). Placeholder advertises
  `[^K] history  [^T] complete  [^R] find  [^G g] editor  [^Y] workflow  [^J] newline`.
- `#name` xprompt completion: auto menu (`auto_xprompt_menu: true`, 90ms debounce), soft inline suggestion, `Ctrl+L`
  accepts; accepting an xprompt with declared inputs pops the argument-hint panel.
- `@`/path file completion via `Ctrl+T` (works off the real filesystem).
- Full vim editing (Escape → NORMAL mode) with the `g` prefix driving multi-agent prompt stacks: `g-` adds a pane
  (border title becomes `Prompt · 2 agents`), `gj`/`gk` focus panes.
- `Enter` on a multi-pane stack opens the `PromptSubmitChoiceModal` (launch all vs current).
- `Ctrl+G Ctrl+C` cancels all panes; `Ctrl+C` cancels the active pane; `q` quits ACE cleanly.
- Jinja `{{ }}` live highlighting and `%model` directive completion need zero external state (optional beats if the clip
  has room).

## Design Decisions

1. **Files-only seeding, no product code changes.** Everything the demo needs can be seeded by writing plain files under
   a throwaway `HOME`/`SASE_HOME`. The env-gated `SASE_ACE_DEMO` mode from the research doc's recommendation #3 is
   explicitly deferred.
2. **Never submit/launch a real agent in the demo.** The story ends at the submit-choice modal, then cancels — no LLM
   latency, no side effects.
3. **Deterministic state**: fixed artifact timestamps, terminal-state agents only, `--refresh-interval 0`, axe daemon
   disabled (verify the exact flag, e.g. `-x`, against `sase ace --help` during implementation), broad explicit
   ChangeSpec query (the default `!!!` query would hide seeded specs).
4. **Privacy**: all seeded names are fictional (e.g. project `nova`, agents `nova--plan-0`, `nova--code`); no real
   project names, paths, or prompts.
5. **Geometry**: target ≥120x40 terminal cells (matches ACE visual goldens; smaller sizes wrap or hide panels). Tune VHS
   `Width`/`Height`/`FontSize` (starting point: 1920x1080 @ FontSize ~22) and verify actual cells with a probe tape
   (`tput cols`/`tput lines`) before recording. Use Fira Code if fontconfig can see it (matches the repo's visual
   snapshot lane); otherwise fall back to another installed monospace font — check `fc-list` during implementation.
6. **Outputs are generated, not committed**: `demos/out/` and `demos/casts/` carry `.gitignore` files per the research
   doc layout; the tape and seeder are the source-controlled artifacts.

## Implementation Steps

### 1. Install ttyd (prerequisite for vhs)

- Download the ttyd static x86_64 binary from its GitHub releases into `~/.local/bin/ttyd`, `chmod +x`, and verify
  `ttyd --version` and that the earlier vhs probe tape now renders.
- Document ttyd/vhs/ffmpeg as prerequisites in `demos/README.md`.
- (No sudo required; avoids apt.)

### 2. Initialize the `demos/` scaffold

Per the research doc layout:

```text
demos/
  README.md            # font/geometry/theme conventions, clip naming, privacy rules,
                       # prerequisites, how to regenerate outputs
  scripts/
    seed_sase_ace_demo # executable bash seeder (below)
  tapes/
    sase_ace_prompt_input.tape
  casts/
    .gitignore         # ignore * except .gitignore (reserved for the asciinema lane)
  out/
    .gitignore         # ignore * except .gitignore
```

### 3. Write `demos/scripts/seed_sase_ace_demo`

Executable bash script. Interface: seeds a target directory (arg 1, default `mktemp -d`) and prints eval-able
`export HOME=... SASE_HOME=... SASE_TMPDIR=...` lines so the tape (or a human) can do
`eval "$(demos/scripts/seed_sase_ace_demo)"`. Seeds:

- **Project + ChangeSpecs**: `$SASE_HOME/projects/nova/nova.sase` with a header (`WORKSPACE_DIR:` pointing at a seeded
  fake workspace dir) and 4-6 ChangeSpec entries across the status lifecycle (WIP/Draft/Ready/Mailed/Submitted), some
  with PARENT links and simple COMMITS/HOOKS sections — modeled on `tests/core_golden/myproj.sase`.
- **Agents**: 3-4 terminal-state agent artifact dirs under
  `$SASE_HOME/projects/nova/artifacts/ace-run/<fixed 14-digit TS>/` with `agent_meta.json` + `done.json` (mostly
  `outcome: completed`, one `failed` for visual variety), named as one agent family (`nova--plan-0`, `nova--plan-1`,
  `nova--code`, ...) so the Agents tab shows family grouping — modeled on `tests/agent_scan_golden/fixture_builder.py`.
- **Demo xprompts**: `$HOME/.config/sase/sase.yml` with an `xprompts:` block defining 2-3 well-named demo xprompts (e.g.
  `add_tests` with a `file_path: path` input) so the `#` completion menu and the argument-hint panel both have curated
  demo content.
- **Fake workspace**: a small dir with a handful of plausible source files (e.g. `src/parser.py`, `src/cli.py`,
  `README.md`) to back the `@`-file completion beat.
- Idempotent and safe: refuses to seed into a non-empty directory that it didn't create.

### 4. Author `demos/tapes/sase_ace_prompt_input.tape`

Based on the research doc's skeleton (`Require` guards for bash/sase/ttyd/ffmpeg, `Hide`/`Show` around setup,
`Set Shell "bash"`, `TypingSpeed ~75ms`, `Framerate 30`, `CursorBlink false`, github-dark theme). Outputs both
`demos/out/sase_ace_prompt_input.mp4` and `.gif`, plus a `Screenshot` poster PNG for QA.

Hidden setup: prepend the repo venv `bin` to `PATH`, `eval` the seeder, `clear`.

**Storyboard (visible portion, ~35-50s):**

1. Type `sase ace --refresh-interval 0 -t agents ...` and launch; `Wait+Screen /Agents/` + settling sleep — seeded agent
   family rows are the backdrop.
2. `space` → prompt input bar opens; pause so the placeholder's feature hints are readable.
3. Type a short natural prompt, then `#add_te...` — the xprompt completion menu appears (sleep past the 90ms debounce);
   accept with `Ctrl+L` → argument-hint panel shows.
4. Fill the arg, then demonstrate file completion: type an `@`/path token and `Ctrl+T`, accept a seeded file with
   `Ctrl+L`.
5. `Escape` (vim NORMAL), `g-` → second pane appears, border title reads `Prompt · 2 agents`; type a second short prompt
   in the new pane.
6. `Enter` → `PromptSubmitChoiceModal` (all vs current) — hold for a beat, then `Escape`.
7. `Ctrl+G` `Ctrl+C` to cancel all panes cleanly, then `q` to quit ACE (clean alt-screen exit).

Each beat gets `Sleep`s tuned for watchability (viewers read slower than users type). Optional beats if pacing allows
(cut first if the clip runs long): Jinja `{{ }}` highlighting, `%model` directive menu.

### 5. Add a `just demo-video` recipe

- Runs `vhs demos/tapes/sase_ace_prompt_input.tape` from the repo root.
- Keep post-processing minimal for now (vhs already emits both formats); note the research doc's ffmpeg/gifsicle
  compression pipeline in `demos/README.md` as future work since gifsicle isn't installed.

### 6. Generate and QA the outputs

- `just install` first (ephemeral workspace), then run the tape via `just demo-video`.
- Verify `demos/out/sase_ace_prompt_input.{gif,mp4}` exist; check the mp4 with `ffprobe` (duration, resolution) and
  inspect the poster PNG (and key gif frames extracted with ffmpeg) to confirm: agent rows visible, completion menu
  rendered, 2-agent stack title, submit modal, no wrapped/hidden panels, readable text.
- Iterate on sleeps/geometry as needed — xterm.js rendering and TUI settling are the expected sources of drift; prefer
  `Wait+Screen /regex/` over blind sleeps where possible.

### 7. Repo hygiene

- Run `just check` before finishing (file changes beyond `sdd/research/` are being made: `demos/`, `Justfile`).

## Verification

- vhs renders the tape end-to-end with exit code 0 (Require guards prove ttyd/ffmpeg/sase).
- `.gif` and `.mp4` exist in `demos/out/` with sane sizes/durations (ffprobe).
- Visual spot-check of poster PNG + extracted frames confirms every storyboard beat landed.
- Re-running the seeder + tape reproduces the clip (deterministic seed data, fixed timestamps).
- `just check` passes.

## Out of Scope

- The narrated OBS walkthrough and asciinema/agg lanes (research lanes 2-3).
- An env-gated `SASE_ACE_DEMO` product mode behind the backend/adapter boundary (worth a follow-up bead if demos become
  maintained release assets).
- gifsicle/ffmpeg compression pipeline and README embedding of the clip.
- Committing generated media.
