# Mentor Redesign: Review & Future Directions

## Overview

The mentor redesign (sase-7.1 through sase-7.5) transformed mentors from fire-and-forget proposal-creating agents into
structured, read-only code reviewers with first-class TUI integration. This document reviews what was accomplished,
identifies current gaps, and recommends next steps.

## What Changed

### Before: Proposal-Based Mentors

- Mentors ran against ChangeLists and created code proposals via `#propose` logic
- A mentor that created a proposal was paradoxically marked `FAILED` with an `entry_ref` pointing to the proposal
- Free-form `prompt` field in config referenced a monolithic xprompt for the entire persona
- Binary status model: RUNNING/PASSED/FAILED/DEAD/KILLED — no way to distinguish "found issues" from "crashed"
- No structured feedback: output was a text blob with no per-file/line references or severity levels
- Mentors claimed workspaces because they could modify files
- No inter-mentor coordination or memory

### After: Structured Review Mentors

- **Structured JSON output**: Mentors produce schema-validated JSON with typed `MentorComment` objects (focus_name,
  file_path, line_number, description, severity)
- **Read-only**: Mentors only read code and produce comments. No workspace claiming, no file modifications
- **Three-status model**: COMMENTED (produced review comments), PASSED (no issues), FAILED (error/invalid JSON)
- **Rubric-driven config**: `role` + `focus_areas` replace the old free-form `prompt` field
- **Tag-based xprompt resolution**: `mentor`, `commit`, `make_mentor_changes` tags allow user overrides
- **TUI review modal** (`,m`): Two-panel popup with mentor list, comment navigation, acceptance toggling
- **Apply agent flow**: Accepted comments are batched and sent to an agent that claims a workspace and applies changes

## Implementation by Phase

| Phase | Bead     | What It Did                                                                                                                   |
| ----- | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 1     | sase-7.1 | Config schema (`role` + `focus_areas`), `XPromptTag` enum, `MentorComment`/`MentorOutput` dataclasses, acceptance persistence |
| 2     | sase-7.2 | `mentor.yml` xprompt workflow, rewrote `MentorWorkflow`, removed `#propose` logic, added COMMENTED status with blue styling   |
| 3     | sase-7.3 | `MentorReviewModal` (475 lines), j/k/n/p/space navigation, `,m` leader key, 16 unit tests                                     |
| 4     | sase-7.4 | `make_mentor_changes.yml` xprompt, `<enter>` to launch apply agent with accepted comments                                     |
| 5     | sase-7.5 | Deprecation error for old `prompt`-based config format                                                                        |

Post-plan follow-ups: gotchas mentor profile (first real-world profile with 5 focus areas), removed `#pro` model forcing
from mentor xprompt, improved prompt scoping language.

## Known Issues & Rough Edges

### 1. `make_mentor_changes` Tag Is Bypassed

The apply flow in `_mentor_review.py` builds the prompt directly in Python instead of resolving the
`make_mentor_changes`-tagged xprompt via `get_by_tag_strict()`. The xprompt file exists and the tag is registered, but
the resolution mechanism is never called. This means users **cannot** override the apply workflow as the architecture
intended.

### 2. Kill From Review Modal Is Incomplete

`action_kill_mentor()` dismisses the modal and tells the user to use `,M` instead. The plan called for direct kill
functionality within the review popup, but the implementation defers to the old hint-based workflow.

### 3. No Stale Output Cleanup

When a new commit supersedes old mentors, stale JSON outputs in `~/.sase/mentors/` persist indefinitely. No garbage
collection mechanism exists.

### 4. Single Status Field Conflates Infrastructure and Review Outcomes

A mentor that produces invalid JSON is marked FAILED — the same status as a mentor that crashes. The v2 critique
recommended separating `execution_status` from `review_outcome`, but the implementation uses a single field.

### 5. Entry ID Matching Is Fragile

`load_mentor_outputs_for_commit()` matches by checking `entry_id in filename.stem`. Since filenames include timestamps,
profile names, and mentor names, short entry IDs (e.g., "1") could collide with other filename components.

### 6. Mentors Builder Fold Logic Bug

In `mentors_builder.py`, the COMMENTED counting branch appears to be at the wrong indentation level relative to its
sibling conditions, making it potentially unreachable in the `elif` chain.

## Future Directions

### Near-Term: Fix What's There

**Wire up `make_mentor_changes` tag resolution** — This is the most impactful fix. The architecture already supports
user-overridable apply workflows via xprompt tags, but the apply flow hardcodes its prompt in Python. Changing
`_launch_mentor_apply_agent()` to resolve and execute the tagged xprompt would unlock the customization path that was
already designed and partially built.

**Fix the fold logic bug in mentors_builder** — Small fix, improves correctness of the collapsed mentor summary display.

**Add output GC** — Clean up stale mentor output JSONs when they're no longer relevant (e.g., when the CL is closed or
the entry is superseded). Could be as simple as a TTL-based cleanup on startup.

### Medium-Term: Improve the Review Experience

**Severity-based policies** — The research docs proposed `error_if` and `warning_if` thresholds on focus areas (e.g.,
"if any comment is severity >= error, block the CL"). The current implementation has severity as a display-only field
with no machine-enforced behavior. Adding configurable policies would give mentors real teeth when warranted.

**Conflict detection** — When multiple mentors suggest contradictory changes to the same file region, there's no warning
before the apply agent is launched. A pre-apply conflict check would prevent the agent from receiving contradictory
instructions.

**Direct kill from review modal** — Wire up `K` in the review modal to actually kill the selected mentor's process
rather than punting to `,M`.

**Dual-status model** — Separate execution status (ran successfully / crashed / timed out) from review outcome (found
issues / clean / inconclusive). This would improve observability and make it easier to distinguish infrastructure
problems from review findings.

### Longer-Term: Expand Mentor Capabilities

**Tiered execution** — The research recommended fast (diff-only, smaller model) vs deep (workspace-aware, larger model)
tiers. Fast mentors could run on every save as lightweight lint-like checks, while deep mentors run on commit with full
codebase context. This would make mentors useful earlier in the development loop without the cost of full reviews.

**Episodic memory** — Cross-revision continuity so mentors can reference prior reviews ("In v1 you flagged X, in v2 the
author addressed Y but introduced Z"). This would reduce noise from repeated comments on unchanged code and enable
mentors to track whether their feedback was addressed.

**Iterative review loops** — Generate-then-critique pattern where a mentor's output is validated by a second pass (or
self-critique), with configurable max iterations. Would improve comment quality and reduce false positives.

**More mentor profiles** — The gotchas profile is the only real-world profile so far. Natural next profiles:

- **Security** — OWASP-focused review for web-facing code
- **Performance** — Hot path analysis, allocation patterns, query complexity
- **API contract** — Breaking change detection for public interfaces
- **Test coverage** — Gaps between changed code and test assertions

## Recommendation

**Start with wiring up `make_mentor_changes` tag resolution.** It's a small change that completes the originally
designed architecture and unblocks the customization story. Follow that with the fold logic bug fix and output GC — both
are low-effort, high-confidence improvements.

After that, **severity-based policies** is the highest-leverage medium-term feature. It moves mentors from "advisory
comments you might read" to "automated quality gates that integrate into the review workflow." Combined with more mentor
profiles, this would make the mentor system a genuine force multiplier rather than a nice-to-have.

The longer-term items (tiered execution, episodic memory, iterative loops) are individually valuable but each represents
a significant architectural investment. Among them, **tiered execution** has the best effort-to-impact ratio — it
multiplies the value of every existing and future mentor profile by making mentors useful at a second point in the
development loop (save-time vs commit-time).
