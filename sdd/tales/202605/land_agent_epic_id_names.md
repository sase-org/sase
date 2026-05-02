---
create_time: 2026-05-01 21:09:21
status: done
prompt: sdd/prompts/202605/land_agent_epic_id_names.md
---
# Land epic agents named by epic bead ID

## Goal

Change `sase bead work <epic_bead_id>` so the final agent that lands the epic is named exactly `<epic_bead_id>` instead
of `<epic_bead_id>.land`.

For an epic `sase-1r`, the generated multi-prompt should move from:

- phase agents: `sase-1r.1`, `sase-1r.2`, ...
- land agent: `sase-1r.land`

to:

- phase agents: `sase-1r.1`, `sase-1r.2`, ...
- land agent: `sase-1r`

The prompt target should remain `#bd/land_epic:<epic_bead_id>`. This is only a launch-name change, not a new bead type
and not a change to which bead the land prompt operates on.

## Current Behavior And Relevant Code

The plan builder is the source of truth for the land agent name:

- Rust core: `../sase-core/crates/sase_core/src/bead/work.rs`
  - `land_agent_name(epic_id)` currently returns `format!("{epic_id}.land")`.
  - `build_epic_work_plan_from_issues()` serializes that value as `EpicWorkPlanWire.land_agent_name`.
- Python boundary: `src/sase/bead/work.py`
  - `build_epic_work_plan()` delegates to Rust for both filesystem-backed bead stores and in-memory issue lists.
  - `_plan_from_payload()` trusts the Rust `land_agent_name`.
  - `render_multi_prompt()` writes `%name:{plan.land_agent_name}` for the land segment.
- CLI launch: `src/sase/bead/cli_work.py`
  - summaries, live-name collision checks, and dry-run output all read `plan.land_agent_name`.
  - pre-claims are phase-only, so no bead assignee field currently needs to change for the land agent.
- TUI bead metadata: `src/sase/ace/tui/models/agent_bead.py`
  - phase names like `<epic_id>.<N>` map directly to phase bead IDs.
  - legacy land names ending in `.land` map back to `<epic_id>` for row badges and detail-panel `Bead:` metadata.

Because the name comes from Rust core, changing only Python rendering would leave tests and future core-backed callers
inconsistent. The primary behavior change should be in Rust.

## Design

1. Make the Rust epic-work planner return the epic ID as the land agent name.
   - Change `land_agent_name(epic_id)` to return `epic_id.to_string()`.
   - Keep `phase_agent_name(bead_id)` unchanged.
   - Keep `land_waits_on` unchanged; leaf phase waits still refer to phase agent names.
   - Keep the land prompt argument as the epic bead ID: `#bd/land_epic:<epic_id>`.

2. Keep Python as a thin consumer of the core value.
   - Do not duplicate land-name derivation in `src/sase/bead/work.py`.
   - Update prompt snapshots and summary/collision expectations to assert the new `%name:<epic_id>` value.

3. Preserve compatibility for already-created legacy `.land` agents.
   - Keep `derive_agent_bead_id()` support for `<epic_id>.land` so old completed/running agents still display
     `Bead: <epic_id>`.
   - Add support for the new land-agent name where the agent name is exactly the epic bead ID. The safest full-detail
     path is to look up the name as a plan bead before enriching the `Bead:` line.
   - For row badges, choose a conservative rule. Either:
     - return the normalized name when it syntactically matches the repo's top-level bead ID shape, accepting a small
       false-positive risk for arbitrary manual agent names; or
     - leave row badges limited to phase and legacy `.land` names, while the full detail panel shows the new land bead
       after lookup. The better product behavior is likely the first option, but implementation should keep the helper
       small and covered by tests because generic names such as `feature-1` can look bead-like.

4. Treat legacy live `.land` land agents as launch collisions during the transition.
   - `expected_agent_names(plan)` should include the new exact name.
   - `find_live_name_collisions(plan)` should also check the legacy alias `<epic_id>.land` for the land agent so
     rerunning `sase bead work <epic_id>` does not create a second land agent while an old-style one is still live.
   - Terminal done legacy agents should remain harmless because `get_live_agent_name_map()` already excludes terminal
     done agents.

5. Update documentation and memory that describe epic work automation.
   - `memory/short/glossary.md` currently says the final land agent is named `<epic_id>.land`; update it to `<epic_id>`.
   - Historical SDD/spec files can remain historical unless they are active user-facing docs, but tests and current docs
     should no longer encode `.land` as the expected new behavior.

## Implementation Steps

1. Rust core:
   - Edit `../sase-core/crates/sase_core/src/bead/work.rs`.
   - Change `land_agent_name()`.
   - Update Rust unit expectations from `e1.land` to `e1`.

2. Python tests and render expectations:
   - Update `tests/test_bead/test_work.py` snapshots and assertions:
     - `plan.land_agent_name == "e1"` / `"sase-r"`.
     - rendered land segment contains `%name:e1`.
     - VCS and ChangeSpec wrappers contain `%name:<epic_id>` for land.
   - Update `tests/test_bead/test_cli_work.py` dry-run and collision expectations:
     - dry-run output checks `%name:{epic_id}`.
     - land collision test uses the new name.
     - add a legacy collision test for `{epic_id}.land` if the transition alias check is implemented.

3. TUI bead metadata:
   - Update `src/sase/ace/tui/models/agent_bead.py`.
   - Keep existing `.land` compatibility tests.
   - Add tests for a new land agent named exactly `sase-x`:
     - full header displays `Bead: sase-x` and title fallback behavior for plan beads.
     - ordinary non-bead names still do not get bead metadata.
     - row badge behavior matches the chosen conservative rule.

4. Current documentation/memory:
   - Update `memory/short/glossary.md`.
   - If any current README/help text mentions `.land` as the active behavior, update that too. The initial search found
     most `.land` references in historical SDD/spec material, which should generally not be rewritten.

5. Verification:
   - From `sase_102`, run targeted Python tests first:

     ```bash
     pytest tests/test_bead/test_work.py tests/test_bead/test_cli_work.py tests/ace/tui/widgets/test_agent_display.py
     ```

   - From `../sase-core`, run the focused Rust bead work tests, or the closest crate-level test command available in
     that repo.
   - Because this repo's memory requires it after edits, run:

     ```bash
     just install
     just check
     ```

## Risks And Open Decisions

- The largest compatibility risk is TUI inference for the new land name. `<epic_id>` is also a plausible manual agent
  name, so a purely syntactic row-badge rule can create false positives. Full-detail metadata can verify by bead lookup;
  the row badge either needs a conservative syntactic rule or can intentionally wait for the full panel to show the
  bead.
- Existing live `.land` agents may still be waiting on phase agents when the new code is used. Checking the legacy alias
  as a live collision avoids launching duplicate land agents for the same epic.
- Historical docs and screenshots contain many `.land` examples. Updating all of them would create churn and blur
  history; only current behavior docs, memory, and executable expectations should change.
