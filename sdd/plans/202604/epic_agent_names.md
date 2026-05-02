---
create_time: 2026-04-25 19:06:59
status: done
prompt: sdd/prompts/202604/epic_agent_names.md
---
# Rename epic-launched agents to `<epic_id>.<N>` / `<epic_id>.land`

## Problem

`sase bead work <epic_id>` currently launches background agents with names like:

- Phase: `epic_sase_s_psase_s_3` (from `_phase_agent_name`)
- Land: `epic_sase_s_land` (from `_land_agent_name`)

These names are noisy and bury the real identifier. The user wants the same naming convention already used for repeat
batches and most TUI displays:

- Phase: `<epic_id>.<N>` → `sase-s.1`, `sase-s.2`, `sase-s.3`
- Land: `<epic_id>.land` → `sase-s.land`

In the snapshot the user shared, all four launched agents (3 phases + 1 land) currently show as `epic_sase_s_psase_s_*`
/ `epic_sase_s_land`. We want `sase-s.1`, `sase-s.2`, `sase-s.3`, `sase-s.land`.

## Why this is safe / valid

1. `%name:` directive accepts the character class `[a-zA-Z0-9_#/.()-]` (see `src/sase/agent/repeat_launcher.py:60-64`).
   Both `sase-s.3` and `sase-s.land` match.
2. Phase bead IDs are guaranteed to be of the form `<parent_id>.<N>` with N an integer (see `BeadProject._next_child_id`
   at `src/sase/bead/project.py:337`), and `build_epic_work_plan` only operates on `IssueType.PHASE` direct children of
   the epic. So the phase bead ID itself **is** `<epic_id>.<N>` — we don't need a separate "compute N" step.
3. The auto-name regex `_AUTO_CHILD_NAME_RE = ^([a-z]+)\.\d+$` (`src/sase/agent/names.py:30`) requires the base to be
   lowercase letters only; `sase-s` contains a hyphen, so phase agent names like `sase-s.3` will **not** be
   misclassified as auto-named children of an `[a-z]+` base. (And `sase-s.land` ends in non-digits.) No collision with
   the auto-name reservation system.

## Design

### `src/sase/bead/work.py`

Replace the two name builders. The dot-sanitization re becomes unnecessary for the phase path (we want to _preserve_ the
dot in the bead ID), but we still need to keep agent names within the `%name:` charset. Concretely:

```python
def _phase_agent_name(epic_id: str, bead_id: str) -> str:
    # Phase bead IDs are <epic_id>.<N> by construction; use as-is.
    return bead_id

def _land_agent_name(epic_id: str) -> str:
    return f"{epic_id}.land"
```

Drop `_AGENT_NAME_SANITIZE_RE` and `_sanitize` — they're only used by these two helpers. (If linting flags an unused
symbol elsewhere, the grep already confirms they aren't referenced outside `work.py`.)

A defensive sanitizer is **not** worth adding: epic IDs come from `_id_gen.next_id()` which produces
alphanumeric+hyphen; if a future ID generator emits something exotic, the `%name:` directive will reject it loudly at
launch time, which is the right failure mode (rather than silently mangling a name into something unrecognisable).

### `src/sase/bead/cli.py` (`handle_bead_work`)

No code change needed — it consumes `EpicWorkPlan` opaquely and writes `assignment.agent_name` straight into the
assignee field and rendered prompt. The new names flow through unchanged.

### Tests

Two test modules pin the old names and need updating; no other production code touches these strings.

1. **`tests/test_bead/test_work.py`** — update every assertion that hard-codes `epic_e1_p…` / `epic_e1_land` /
   `epic_sase_r_…`:
   - `waves[*].waits_on` tuples (lines ~95-99, 127-130, 207, 311)
   - `land_agent_name` (lines ~99, 312)
   - `land_waits_on` (lines ~98, 130, 182-184, 207)
   - The full multi-prompt rendering block (lines ~143-159) — `%name`, `%w`, and the order of segments stay the same,
     only the names change.
   - `agent_name` assertion (line 311) becomes `"sase-r.1"`.
   - `test_bead_id_with_dot_sanitised` (line 302) is now misnamed — rename to `test_phase_agent_name_uses_bead_id` (or
     similar) and assert `agent_name == "sase-r.1"`, `land_agent_name == "sase-r.land"`.

2. **`tests/test_bead/test_cli_work.py`** — line 95-104 currently asserts
   `phase.assignee == f"epic_{sanitised_epic}_p{sanitised_pid}"`. Replace with `phase.assignee == pid` (since the agent
   name == bead ID for phases). Drop the `re.sub`/`sanitised_*` locals — no longer needed. Remove the `import re` if it
   becomes unused.

### Memory / docs

Update `memory/short/glossary.md` (the **Epic work automation** entry) — it mentions `assignee=epic_<epic>_p<bead>`
which becomes `assignee=<phase_bead_id>` (i.e. `<epic_id>.<N>`).

`plans/202604/epic_work_automation.md` is a historical implementation plan for the already-shipped feature; leave it
alone (don't rewrite history).

## Out of scope

- Renaming the `epic_*` prefix elsewhere (there isn't any — `grep` confirms `work.py` is the only producer).
- Changing how `%w:` references are rendered (still comma-joined names; just the names are different now).
- Backfilling already-launched agents whose names are baked into existing artifact directories. The change only affects
  future `sase bead work` invocations.

## Validation

1. `just check` — covers `mypy`, `ruff`, and the updated tests.
2. Eyeball: in a scratch project, `sase bead work <epic_id> --dry-run` should emit segments whose `%name:` lines read
   `<epic_id>.1`, `<epic_id>.2`, …, `<epic_id>.land`, and whose `%w:` lines reference those same names.
