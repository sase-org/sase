---
create_time: 2026-05-10 11:23:49
status: done
prompt: sdd/prompts/202605/finish_sase_2n.md
bead_id: sase-2q
tier: epic
---
# Plan: Finish sase-2n Epic — Validate, E2E Test, and Apply Lumberjack Audit Chops

## Goal

Complete the remaining work for the `sase-2n` epic (Add Commit-Threshold Bug and Improvement Lumberjack Chops) so all
five phase beads can be closed. The epic adds two scheduled Athena lumberjack chops — `sase_recent_bug_audit` and
`sase_recent_improvement_audit` — gated by a 50-commit threshold that mirrors `refresh_docs`.

## Current State (verified before planning)

- **Phase 1 (Config Workflows) — DONE.** `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` defines both
  `audit_recent_bugs` and `audit_recent_improvements` workflows with `threshold=50` defaults, marker counting that
  mirrors `refresh_docs` (SHA → timestamp → forced-first-run fallback), and launched prompts that embed `#pr(...)`.
- **Phase 2 (Lumberjack Wiring) — DONE.** A `code_quality` lumberjack is wired with both chops (`sase_recent_bug_audit`,
  `sase_recent_improvement_audit`) using `run_every: 60m`. Existing `refresh_docs` chops are unchanged.
- **Chezmoi tree is committed and clean.** Both phases shipped in chezmoi commit `cfe7d7a3` (feat: Commit
  bug/improvements audit chops + other bulk changes). `chezmoi apply` has already been run —
  `~/.config/sase/sase_athena.yml` is byte-identical to the managed file.
- **Marker files already exist** (`~/.sase/projects/sase/recent_bug_audit_marker`, `recent_improvement_audit_marker`),
  meaning the chops have actually fired in the wild — additional care needed in Phase 2 (E2E testing) to never touch
  real markers.
- **Beads `sase-2n.1`–`sase-2n.5` are all `open`.** No phase agents have been formally run; the implementation work was
  bundled into a manual user commit. The remaining phases are therefore **validation and sign-off work**, not
  re-implementation.

## Remaining Work

The original epic plan's Phase 1 and Phase 2 are functionally complete — we will close `sase-2n.1` and `sase-2n.2`
without spawning agents for them as part of the wrap-up in this plan's final phase. The remaining substantive work is
the original epic's Phase 3, Phase 4, and Phase 5, which map cleanly to three distinct agents.

### Phase 1 — Static & Merged-Config Validation

Single agent. Validates that the committed config is well-formed and visible to SASE. Read-only with respect to product
code; no chezmoi or repo edits expected.

Tasks:

- Parse `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` with PyYAML to confirm YAML validity.
- Run `sase xprompt explain audit_recent_bugs` and `sase xprompt explain audit_recent_improvements`; confirm both
  resolve and that the rendered launch step contains `#pr(`, the expected commit-range fields, and bug-only vs.
  objective-improvement-only language.
- Inspect the merged axe config (e.g. `sase axe config` or equivalent dump) to confirm:
  - `code_quality` lumberjack is present with `interval: 60`;
  - both chops are attached with `run_every: 60m`;
  - chop names, workflow names, and marker filenames are all distinct from each other and from `refresh_docs`.
- Confirm the chezmoi working tree is clean and that no unrelated user edits would be disturbed.
- If a defect is found, fix it directly in the chezmoi config (and only there) before closing.

Acceptance:

- Both workflows explain cleanly and the `#pr` xprompt is visible in their resolved prompts.
- The merged axe config exposes the new lumberjack and chops.
- Chezmoi git status remains clean (or the only diff is a defect fix made in this phase).
- `sase-2n.3` is closed.

### Phase 2 — End-to-End Threshold & Marker Testing

Single agent, expected to use Sonnet for any spawned validation agent. The objective is behavior-level confidence, not
just static parsing. The agent must scrupulously avoid touching real markers under `~/.sase/projects/sase/` — all marker
writes must occur inside a temporary `HOME` or test-scoped path.

Tasks:

- Build a disposable git repository with enough synthetic commits to cross the 50-commit threshold.
- Override `HOME` (or otherwise redirect the marker path) so the test cannot mutate
  `~/.sase/projects/sase/recent_bug_audit_marker` or `recent_improvement_audit_marker`.
- Exercise each of the following scenarios for both workflows:
  - First-run (no marker) → forced launch.
  - Below threshold (< 50 commits since marker) → early abort, no agent launch, marker untouched.
  - Exactly at threshold (= 50 commits) → launch, marker advanced to current HEAD.
  - Stale-SHA fallback (marker SHA garbage-collected, timestamp present) → counts via `--after=<timestamp>`.
  - Independent markers (running the bug audit must not advance the improvement marker, and vice versa).
  - Prompt-content checks: each launched prompt contains `#pr(...)`, the commit-range/HEAD fields, and the right
    review-scope language (bug-only vs. objective-improvement-only).
  - Marker advance after launch prevents an immediate second launch in the same window.
- Stub or mock `launch_agent_from_cwd` so no real daemon agents spawn; capture the prompt argument for assertions.
- Capture artifacts/logs from the run for the wrap-up phase to reference.

Acceptance:

- Evidence (logs, captured prompts, or saved artifacts) demonstrates each scenario above.
- Real user marker files under `~/.sase/projects/sase/` are byte-identical before and after the run.
- `sase-2n.4` is closed.

### Phase 3 — Apply, Checks, and Epic Wrap-Up

Single agent. Confirms the system end-state and closes out the remaining beads. This phase also handles the
"already-done" beads (`sase-2n.1`, `sase-2n.2`) since closing them is part of finalizing the epic.

Tasks:

- Re-confirm `~/.config/sase/sase_athena.yml` matches the managed chezmoi file. Run `chezmoi apply --force` only if a
  drift is detected (the pre-plan check showed no drift, so this should be a no-op).
- Run `just check` in `~/.local/share/chezmoi`. **Pre-existing failures in `tests/bash/pyvision_test.sh` due to a
  missing `tomllib` module are unrelated to this epic** — record them as known and unrelated rather than blocking the
  epic. All other test groups must pass.
- Skip `just install` / `just check` in the SASE repo: no SASE-repo files were changed by this epic. Confirm by checking
  `git status` in `/home/bryan/projects/github/sase-org/sase_103` is clean of audit-chop-related edits.
- Produce a short summary covering: changed files (chezmoi only), commands executed, any residual risk, and any defects
  fixed across the three phases.
- Close beads in order: `sase-2n.1`, `sase-2n.2`, `sase-2n.3` (if not already closed by Phase 1 agent), `sase-2n.4` (if
  not already closed by Phase 2 agent), `sase-2n.5`, then the epic bead `sase-2n` itself.

Acceptance:

- Chezmoi `just check` is green except for the documented pre-existing pyvision failures.
- Applied config matches managed config.
- All five phase beads and the `sase-2n` epic bead are closed.
- A wrap-up summary is recorded (in the agent's chat or as a SASE artifact).

## Risks and Notes

- **Real-world markers exist and are recent.** Phase 2's E2E agent must redirect `HOME` or the marker path; a careless
  test that writes to `~/.sase/projects/sase/recent_*_audit_marker` would silently delay the next real audit by up to 50
  commits.
- **Pre-existing chezmoi test failures.** `just check` in `~/.local/share/chezmoi` currently fails 11 pyvision tests due
  to a missing `tomllib` import (Python interpreter issue, not config-related). The Phase 3 agent should treat these as
  known unrelated failures, not as a blocker.
- **No new product code is expected.** This is a config-only epic. If validation in Phase 1 or Phase 2 surfaces a defect
  that requires Python product code changes in `sase_103`, that should be flagged for a separate follow-up rather than
  expanded inside the wrap-up phase.
- **Phase 1 and Phase 2 beads are closed in Phase 3** rather than spun up as their own agents because the underlying
  work is already committed and applied; spawning agents for closed work would just be ceremony.
