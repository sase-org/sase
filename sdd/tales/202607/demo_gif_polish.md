---
create_time: 2026-07-07 00:49:18
status: done
prompt: sdd/prompts/202607/demo_gif_polish.md
---
# Demo GIF Polish: Fix Visible Defects and Dead Air in the ACE Demo Tapes

## Background

`demos/out/` contains four scripted VHS demo captures (GIF + MP4) of the ACE TUI:

- `sase_ace_prompt_input.{gif,mp4}` — prompt input, xprompt completion, multi-agent prompt stacks
- `sase_ace_agents_observability.{gif,mp4}` — agents tab navigation, files/tools views, zoom
- `sase_ace_prompt_history_stash.{gif,mp4}` — prompt history recall, search, stash, restore
- `sase_ace_prs_pipeline.{gif,mp4}` — PRs tab ChangeSpec lifecycle, navigation, grouping, folding

A frame-by-frame review of all four GIFs found the following objective defects (in rough order of severity):

1. **The prompt_input demo shows a real error toast.** ~8 seconds in, a notification appears: _"Could not find a `sase`
   executable to start axe."_ and lingers for several seconds. Root cause: `sase_ace_prompt_input.tape` is the only tape
   that launches `sase ace` without `-x/--no-axe`. Axe autostart always fails in the seeded demo environment (the fake
   `HOME` has no `~/.local/bin/sase`, and `src/sase/axe/_process_start.py` rejects ephemeral-workspace executables when
   resolving a canonical `sase` for the daemon), so the demo permanently records an error popup.

2. **The prompt_input demo has live auto-refresh churn.** The same tape also omits `--refresh-interval 0`, so the header
   renders a ticking "(auto-refresh in Ns)" countdown and an auto-refresh actually fires mid-recording — one captured
   frame shows the detail pane partially redrawn (missing Model/VCS lines) plus black smear artifacts near the
   scrollbar. The other three tapes explicitly disable auto-refresh for determinism.

3. **All four GIFs open and close with dead air.** After the launch command is typed, ~2–3 seconds of blank terminal
   (including one fully black frame) are recorded while the TUI starts. After the last content beat, teardown keystrokes
   are recorded: cancel toasts, a blank shell, and the word `exit` being typed (~1.5s in the observability/PRs tapes,
   ~5s in the prompt*input and history/stash tapes, which `Sleep 4s` before typing `exit`). Net effect: roughly 10–15%
   of every GIF is dead frames, and the _final* frame — what non-looping viewers display — is a blank terminal instead
   of the product.

4. **The PRs demo showcases "(no timestamp)" data.** The by-date grouping beat (`o` keypress) is an explicit feature
   showcase, but 3 of the 5 seeded ChangeSpecs (`nova_parser_edges`, `nova_cli_refresh`, `nova_release_notes`) have no
   TIMESTAMPS section, so the demo renders an "Earlier / (no timestamp) / 3 PRs" bucket — the feature being demoed looks
   like it has missing data. The seeder also writes the legacy unbracketed timestamp form (`260706_085500 STATUS ...`)
   instead of the canonical bracketed form (`[260706_085500] STATUS ...`) documented in `docs/change_spec.md`, and the
   TIMESTAMPS section is visible in the detail pane during the demo.

5. **Every header shows a dev-noise version.** All four GIFs render the title as
   `sase ace (v0.10.2+58.g13e2d4057.dirty)`. This is unavoidable today: the ACE title refines to a git-derived dev
   version for editable installs (`src/sase/ace/tui/util/app_version.py` → `sase.version.host_display_version()`), and
   `just demos` itself dirties `demos/out` between tapes, so even a fully committed tree renders tapes 2–4 as `.dirty`.
   Published demo media should show the clean release version.

6. **Minor: temp-dir handling is inconsistent across tapes.** The history/stash and PRs tapes pin a fixed seed directory
   (`/tmp/sase-ace-demo.Sx5eykRn`, `.jsaIeSv0`) with an `rm -rf` upfront, so on-screen artifact paths are deterministic
   across regens. The prompt_input and observability tapes use a random `mktemp` directory, so a different random path
   appears in the detail pane's artifact-path line every regen, and stale seed dirs accumulate in `/tmp`.

Explicitly ruled out after testing: **GIF byte-size compression.** An `ffmpeg` palette re-encode of the largest GIF
produced 0% savings (VHS output is already palette-optimized), and `gifsicle` is still not installed — `demos/README.md`
already records that as the gate for future compression work. (The dead-air trimming in this plan reduces frame count
and thus size anyway.)

## Goals

- No error toasts, refresh countdowns, or mid-recording refresh artifacts in any demo.
- No dead-air lead-in/tail; every GIF starts on the typed launch command, jump-cuts to the loaded TUI, and ends on a
  meaningful product frame.
- The by-date grouping beat shows real date buckets for all five seeded ChangeSpecs.
- Demo headers show the clean release version (`sase ace (v0.10.2)`), not a git dev suffix.
- All four tapes follow the same conventions (refresh disabled, axe disabled, pinned seed dir, hidden startup/teardown).
- Regenerated `demos/out/` artifacts verified frame-by-frame before finishing.

## Non-Goals

- GIF compression / geometry / theme / typing-speed changes (no `gifsicle`; current pacing and 1920x1080 geometry are
  deliberate per `demos/README.md`).
- Making the seeder fully relative-dated (computing seed timestamps from "now" so regens always show "Today"/"36m ago").
  Today's seeder is deliberately fixed-data; absolute dates drift gracefully into "Yesterday"/"This Week" buckets. Worth
  a follow-up discussion, not this change.
- Recording new demo scenarios or altering the demo storylines.

## Design

### 1. Fix the prompt_input tape's launch flags (defects 1 + 2)

In `demos/tapes/sase_ace_prompt_input.tape`, change the visible launch command from `sase ace` to:

```
sase ace --refresh-interval 0 -x
```

matching the other three tapes (`--tab agents` is the default and stays omitted). This removes the axe error toast (axe
autostart never runs), the "(auto-refresh in Ns)" countdown, the mid-recording refresh, and the associated redraw
artifacts; the axe badge renders a stable `STOPPED` instead of `STARTING`.

### 2. Trim dead air with Hide/Show in all four tapes (defect 3)

VHS `Hide`/`Show` stops/resumes frame capture while commands keep executing, and `Wait+Screen` still works while hidden.
Apply the same pattern to every tape:

- **Startup:** keep the launch command typing visible, then `Hide` before `Enter`, keep (and where thin, strengthen) the
  existing `Wait+Screen` guards so the UI is fully populated, then `Show` followed by the existing opening `Sleep`. The
  GIF jump-cuts from the typed command straight to the loaded TUI. The prompt_input tape currently only waits for
  `/Agents/` before its opening sleep; add row-level waits (e.g. `nova--review`, `nova--plan-1`) mirroring the
  observability tape so `Show` never captures a half-populated table.
- **Teardown:** after each tape's final content beat and its closing `Sleep`, insert `Hide` and leave the existing quit
  keystrokes (`Escape`/`Ctrl+C`/`q`/`exit`) to run unrecorded. In the prompt_input tape, the final content beat becomes
  the multi-agent prompt stack after the submit modal is dismissed — extend its post-`Escape` sleep (700ms → ~2s) so the
  closing frame lingers; the two `Ctrl+C` cancel toasts and the 4s dead wait become invisible teardown.

Every GIF then ends on a real product frame, and total duration drops by roughly 4–7 seconds per clip.

### 3. Seed TIMESTAMPS for all five ChangeSpecs (defect 4)

In `demos/scripts/seed_sase_ace_demo`, give every ChangeSpec at least one TIMESTAMPS entry and convert the two existing
entries to the canonical bracketed format from `docs/change_spec.md`. Keep story-time consistency with the existing seed
data (hooks ran 260706 09:00–09:15, agents ran 260706 13:00+):

- `nova_prompt_input` (Ready): `[260706_085500] STATUS  Draft -> Ready` (format conversion only)
- `nova_parser_edges` (Draft): `[260706_091500] STATUS  WIP -> Draft` (matches its hook run time)
- `nova_cli_refresh` (WIP): `[260706_101500] REWORD  Clarified CLI refresh scope` (WIP is the initial status, so a
  REWORD event is the natural first timestamp)
- `nova_release_notes` (Mailed): `[260705_153000] COMMIT  (1)` and `[260705_160500] STATUS  Ready -> Mailed`
- `nova_seed_cleanup` (Submitted): `[260705_170000] STATUS  Mailed -> Submitted` (format conversion only)

The by-date beat then shows only real buckets/windows (which buckets — Today vs Yesterday vs This Week — depends on the
regen date, but "(no timestamp)" can never appear). The PRs tape's `Wait+Screen` patterns only key on group-mode labels,
status headers, and spec names, so no tape edits are needed for this; the tape's `j`-navigation order is file order and
is unaffected.

### 4. Stable release version in the ACE header (defect 5)

Add a small presentation-layer escape hatch in `src/sase/ace/tui/util/app_version.py`: `resolved_app_version()` returns
`None` early when the env var `SASE_ACE_RELEASE_VERSION_TITLE` is set to a truthy value. Returning `None` means the
existing refinement step in `src/sase/ace/tui/actions/_startup_mount.py` keeps the initial title, which is already the
clean release string from `sase.__version__` — so the header reads `sase ace (v0.10.2)` and tracks future releases
automatically. This is TUI-presentation logic only (no Rust core boundary concerns, no CLI flag, no keymap).

Each tape exports `SASE_ACE_RELEASE_VERSION_TITLE=1` in its hidden setup block. Add a unit test covering the env-gated
early return (both set and unset paths), and mention the variable in `demos/README.md`'s determinism notes.

### 5. Pin seed directories in the two remaining tapes (defect 6)

Give `sase_ace_prompt_input.tape` and `sase_ace_agents_observability.tape` fixed seed directories with an upfront
`rm -rf`, exactly like the history/stash and PRs tapes (two new fixed 8-character suffixes, e.g.
`/tmp/sase-ace-demo.pIn4Qw2c` and `/tmp/sase-ace-demo.aObs7Kd1`). On-screen artifact paths become identical across
regens and stale mktemp dirs stop accumulating.

### 6. Regenerate and verify

- `just install`, then `just demos -y` (required by `demos/tapes/CLAUDE.md` after any tape edit; the recipe renders all
  four tapes, stamps `demos/out/last_generated_date.txt`, and commits the refreshed `demos/out/` artifacts itself).
- Verify the regenerated GIFs the same way the defects were found — extract ~1fps frames with `ffmpeg` and inspect: no
  error toast, no refresh countdown, no black smears, no blank lead-in or tail frames, final frame shows the TUI, clean
  `sase ace (v0.10.2)` header, no "(no timestamp)" bucket in the by-date beat, and durations/file sizes reduced.
- Update `demos/README.md`: fold the new conventions (axe disabled + refresh disabled in every tape, hidden
  startup/teardown, pinned seed dirs, `SASE_ACE_RELEASE_VERSION_TITLE`) into the existing "keep future demos on the same
  pattern" guidance.
- `just check` (required — this change touches `src/`).

## Files Expected to Change

- `demos/tapes/sase_ace_prompt_input.tape` — launch flags, Hide/Show trim, pinned seed dir, stronger load waits, longer
  closing beat, env export
- `demos/tapes/sase_ace_agents_observability.tape` — Hide/Show trim, pinned seed dir, env export
- `demos/tapes/sase_ace_prompt_history_stash.tape` — Hide/Show trim, env export
- `demos/tapes/sase_ace_prs_pipeline.tape` — Hide/Show trim, env export
- `demos/scripts/seed_sase_ace_demo` — TIMESTAMPS entries for all five ChangeSpecs (canonical bracketed format)
- `src/sase/ace/tui/util/app_version.py` — env-gated early return in `resolved_app_version()`
- New unit test for the env-gated version behavior (alongside existing ACE TUI util tests)
- `demos/README.md` — document the new tape conventions
- `demos/out/*` — regenerated artifacts (committed by the `just demos -y` recipe)

## Risks

- **VHS timing sensitivity.** Hide/Show changes shift when capture starts/stops; a too-thin `Wait+Screen` guard before
  `Show` could capture a half-drawn UI. Mitigated by strengthening the waits and by frame-extraction verification of
  every regenerated GIF.
- **Render-date drift.** Seeded absolute dates mean the exact by-date bucket labels (Today/Yesterday/This Week) depend
  on the regen date. The tape only waits on `group: by date`, so regens can never fail on this — the composition just
  varies. Documented as a non-goal (relative-date seeding is a possible follow-up).
- **Environment prerequisites.** `just demos` needs `vhs`, `ttyd`, `ffmpeg`, and a `sase` on the outer PATH plus the
  Fira Code font; all were present for the most recent regen on this host.
