---
create_time: 2026-07-06 19:35:55
status: done
prompt: sdd/prompts/202607/ace_prompt_input_demo.md
---
# ACE Prompt Input Demo Tape Plan

## Goal

Improve the `demos/tapes/sase_ace_prompt_input.tape` recording so it highlights the common prompt-input completion flows
in a natural order:

1. project completion from a leading `+`,
2. xprompt completion and argument hints,
3. file completion over a richer seeded workspace,
4. multi-agent prompt submission.

The demo should launch ACE with the plain `sase ace` command rather than showcasing specialized command-line flags.

## Current State

- The tape seeds a hermetic fake SASE home and fake `nova` workspace through `demos/scripts/seed_sase_ace_demo`.
- The tape currently launches `sase ace --refresh-interval 0 --tab agents -x`.
- The seeded workspace has only a small set of files:
  - `README.md`
  - `pyproject.toml`
  - `src/parser.py`
  - `src/cli.py`
  - `tests/test_parser.py`
  - `docs/prompt_input_notes.md`
- File completion is visible, but narrow: the scripted flow only completes around `src/parser.py`.
- Project metadata already includes `PROJECT_NAME: nova` and `PROJECT_ALIASES: nova-demo`, which should provide useful
  project completion candidates for the leading `+` demo.

## Proposed Changes

### 1. Expand Seeded Workspace Files

Update `demos/scripts/seed_sase_ace_demo` to create additional realistic files in the fake `nova` workspace. Keep them
small, deterministic, and clearly fictional.

Recommended additions:

- source files:
  - `src/nova/__init__.py`
  - `src/nova/parser.py`
  - `src/nova/cli.py`
  - `src/nova/config.py`
  - `src/nova/renderers/summary.py`
- tests:
  - `tests/test_cli.py`
  - `tests/test_config.py`
  - `tests/fixtures/commands.txt`
- docs:
  - `docs/architecture.md`
  - `docs/release_checklist.md`
- config/examples:
  - `examples/basic_command.txt`
  - `.github/workflows/ci.yml`

Keep existing file names that the tape already references unless deliberately changing the scripted completion path. If
moving the Python package layout to `src/nova/...`, update import examples and test imports consistently in the seed
data so the fake repo still looks coherent.

### 2. Make the Tape Launch Plain ACE

Change the VHS command from:

```text
sase ace --refresh-interval 0 --tab agents -x
```

to:

```text
sase ace
```

Then adjust the scripted waits/key presses only as needed for the default startup tab and default refresh behavior. The
goal is a user-facing demo of ordinary usage, not a CLI-options demo.

### 3. Demonstrate Project Completion First

Immediately after opening the prompt input, type a prompt fragment beginning with `+`, such as:

```text
+nov
```

Wait for project completion to show `nova` or `nova-demo`, accept the completion, and leave the completed project token
at the front of the prompt. Then continue the rest of the scripted prompt from there.

The desired first beat should read visually like an ordinary scoped SASE prompt, for example:

```text
+nova Add parser coverage with #add_tests ...
```

Use stable `Wait+Screen` patterns that match visible completion text rather than fragile full-line text.

### 4. Show Richer File Completion

After xprompt argument completion, demonstrate file completion against the richer seed data. Use at least two distinct
paths or a path prefix that visibly presents multiple candidates. A good sequence would be:

- complete or type the `#add_tests` path argument with a source file such as `src/nova/parser.py`;
- later type an inline file mention like `@docs/rel` or `@tests/fi`, trigger file completion, and accept the result.

This should make the expanded seed data visible without making the tape feel slow or cluttered.

### 5. Preserve the Existing Narrative Ending

Keep the multi-agent prompt-stack beat:

- create the second prompt segment with `g-`,
- wait for the UI to indicate two agents/prompts,
- submit,
- show the launch confirmation briefly,
- exit cleanly.

Do not make the recording actually run live external agents; keep the seeded, fake state pattern intact.

## Validation

1. Run the demo seed script directly once to confirm it creates the expanded fake workspace without errors.
2. Run `just demos -y` after editing the tape, per `demos/tapes/AGENTS.md`, to regenerate:
   - `demos/out/sase_ace_prompt_input.gif`
   - `demos/out/sase_ace_prompt_input.mp4`
   - `demos/out/last_generated_date.txt`
3. Because this changes repository files outside the documented exceptions, run:
   - `just install`
   - `just check`
4. Inspect the regenerated demo enough to confirm:
   - the visible command is `sase ace`,
   - leading `+` project completion appears before xprompt/file completion,
   - file completion has more than the original single obvious `src/parser.py` path,
   - the recording exits cleanly.

## Risks

- Default `sase ace` startup may land on a different tab or refresh timing than the current flags. Mitigation: use
  stable screen waits and, if needed, normal in-app navigation rather than reintroducing obscure CLI options.
- Completion popups can be sensitive to timing. Mitigation: keep typed prefixes short and unique enough for stable VHS
  waits, and prefer deterministic seeded candidates.
- `just demos -y` may be slow because it renders video. It is still required for tape edits by local instructions.
