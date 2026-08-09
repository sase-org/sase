---
diagram: docs/images/commit-workflow-infographic.png
embedded_in: docs/commit_workflows.md
phase: critique
pdf: false
---

# Critique: `commit-workflow-infographic.png`

## Summary

This is a historical critique of a diagram that predated the provider-neutral commit
finalizer. The committed PNG still shows the old left-to-right shape (xprompt inputs →
stop hook → commit skill → `sase commit` → `CommitWorkflow` → three output branches).
The current runtime behavior is xprompt inputs → commit finalizer → commit skill →
`sase commit` → `CommitWorkflow` → three output branches.

The main problems are with the central `CommitWorkflow` band: it omits two stages, drops
one of the canonical labels in favor of an off-spec synonym, and renders the stages in
the wrong relative order. The conflict-resume loop is also drawn ambiguously enough that
a new reader cannot tell which step it re-enters. These are accuracy issues a reader
checking the diagram against `docs/commit_workflows.md` or the code would notice
immediately.

## What's actually in the rendered PNG

Reading the committed `commit-workflow-infographic.png` directly:

- Title: **Shared Commit Workflow**
- Left input stack: `#commit`, `#propose`, `#pr` (rendered as map-pin icons).
- Linear path: **Agent changes → Stop hook → Commit skill → sase commit →
  CommitWorkflow** (large central band).
- `CommitWorkflow` band chips, in the order shown: **Precommit, Bead handling, Plan
  handling, PR tags, Parent detection, VCS dispatch, Tracking, Result marker**.
- Side loop, drawn under the band as a yellow warning chip with a curved arrow:
  **Conflict checkpoint + resume**.
- Right output branches (3 cards):
  - **Commit hash + STITCHES entry**
  - **Saved diff + STITCHES entry**
  - **PR URL + Patch**
- Bottom-right note card: **VCS providers: Git, GitHub, Mercurial**.

## Clarity issues a new user would hit

1. **xprompt inputs are not labeled as xprompts.** The three location-pin icons on the
   left are labeled only with `#commit` / `#propose` / `#pr`. A reader who has never
   seen an xprompt has no cue that these are xprompt triggers — they look like tags or
   hashtags. A small caption ("xprompts") above the stack would land the concept.
2. **Order inside the `CommitWorkflow` band is ambiguous.** The chips sit in a single
   horizontal row inside the band with no internal arrows or numbering. The eye reads
   them left-to-right, but several of them are not actually in left-to-right execution
   order (see accuracy section). A new user trying to follow "what runs first?" will get
   the wrong answer.
3. **The conflict loop's re-entry point is unclear.** The yellow chip sits below the
   band with a small curved arrow, but the arrow does not visibly target a specific
   stage. From `docs/commit_workflows.md` and `CommitWorkflow.resume()`, resume
   re-enters at provider `vcs_finalize_commit` (post-dispatch) and then replays the
   post-dispatch tracking steps. The diagram should show the loop landing between
   `VCS dispatch` and `Result marker` / `Tracking`, not floating under the whole band.
4. **"Tracking" is one chip but represents several discrete outputs.** A reader sees one
   chip and three output cards and has to guess which card each tracking step writes to.
   Splitting "Tracking" into the actual tracking artifacts (Patch, STITCHES entry,
   result marker) — or showing arrows from each tracking sub-step to its specific output
   card — would remove the ambiguity.
5. **No visual distinction for proposal-skipped stages.** The doc explicitly calls out
   that bead lifecycle and plan handling are skipped for `create_proposal`, but every
   chip looks identical. A subtle styling cue on those two chips ("skipped for
   #propose") would match what the doc already documents and is one of the most
   user-asked questions.

## Accuracy issues vs. code and doc

Grounding against `src/sase/workflows/commit/workflow.py` (`run` method, lines 104–226)
and the stage list in `docs/commit_workflows.md` ("3. CommitWorkflow orchestrates"):

1. **Wrong relative order in the band.** The actual execution order from the code is:
   1. Bead lifecycle (`handle_beads`) — skipped for proposals
   2. Plan handling (`handle_sase_plan`) — skipped for proposals
   3. Before hook (`run_before_commit_hook`)
   4. PR name suffixing (`compute_suffixed_cl_name`) — PR only
   5. Parent detection (`detect_parent_changespec`) — PR only
   6. PR tags / body (`apply_project_pr_prefix`, `append_pr_tags`, `build_pr_body`) — PR
      only
   7. Diff capture (`capture_pre_commit_diff`)
   8. Checkpoint (`checkpoint_save`)
   9. VCS dispatch
   10. After hook (`run_after_commit_hook`) — commit/PR only
   11. Tracking (Patch for PR; result marker; STITCHES entry for commit/propose)

   The diagram puts the old `Precommit` stage first, then `Bead handling`, then
   `Plan handling`. That contradicts the prompt sidecar's corrected ordering and the
   code, which runs beads/plan before `commit_hooks.before` so plan files are staged
   when the configured before hook runs. It also omits the post-dispatch
   `commit_hooks.after` stage.

2. **Missing "Bead lifecycle" — replaced with "Bead handling".** The doc's canonical
   name (and the prompt's required label) is **Bead lifecycle**. The diagram shows
   **Bead handling**. Terminology drift; should match the doc and prompt.
3. **Missing "Diff capture" chip.** This is a real stage in the code
   (`capture_pre_commit_diff`, line 177 of `workflow.py`) and is in the prompt's
   required label list. Without it, a reader cannot tell where the
   `Saved diff + STITCHES entry` output branch's diff actually comes from.
4. **Missing "Checkpoint" chip.** The pre-dispatch checkpoint write
   (`checkpoint_save(cp)`, line 192 of `workflow.py`) is what the
   `Conflict checkpoint + resume` side loop is reading from. Omitting the chip leaves
   the conflict loop floating without a clear origin point.
5. **Missing PR-only "PR name suffixing" stage.** The doc lists this explicitly under
   PR-only stages, and the code computes `_<N>` suffixing in `run` (lines 124–140)
   before parent detection. Not in the prompt label list either, but worth flagging
   since it's a real PR-only stage that affects the output branch (`PR URL + Patch`).
6. **Legacy stop-hook label is now stale.** The current code runs the provider-neutral
   commit finalizer after a successful provider invocation inside a SASE agent session.
   The old `Stop hook` label should become `Commit finalizer`, with no provider-native
   stop-hook compatibility path implied.
7. **Output branches are correct but the proposal branch is mislabeled imprecisely.**
   "Saved diff + STITCHES entry" matches the doc and code (proposals append a COMMITS
   entry per workflow.py `_run_tracking_steps` and the doc's "Tracking: Appends a
   proposal STITCHES entry"). No change needed; flagging only that this was the chip
   most likely to drift.

## Concrete suggested changes for regeneration

For the next phase (`sase-2s.12 — Regenerate diagram: commit-workflow`):

1. **Use the canonical 11-stage chip list, in execution order**, inside the
   `CommitWorkflow` band, with internal left-to-right arrows or numeric prefixes so
   order is unambiguous:
   `Bead lifecycle → Plan handling → Before hook → PR tags → Parent detection → Diff capture → Checkpoint → VCS dispatch → After hook → Result marker → Tracking`.
   (This matches the prompt sidecar's "Exact visible labels" list verbatim.)
2. **Mark proposal-skipped chips visually** — a small "(skipped for #propose)" caption
   or a dashed border on `Bead lifecycle` and `Plan handling`.
3. **Mark PR-only chips visually** — a small "(PR only)" caption or accent on `PR tags`
   and `Parent detection`.
4. **Mark `After hook` commit/PR-only and post-push**, so the proposal branch clearly
   bypasses it.
5. **Anchor the conflict-resume loop to specific stages.** The arrow should leave
   `VCS dispatch` (on conflict) and re-enter at `Checkpoint` → `VCS dispatch` (after
   manual resolve), then continue through `Result marker` and `Tracking`. Drawing the
   loop as an explicit arc between those two chips, instead of a floating side card,
   makes the resume model legible.
6. **Label the input stack as `xprompts`** so `#commit` / `#propose` / `#pr` read as a
   category, not as floating tags.
7. **Keep** the right-side three-card output branches and the "VCS providers: Git,
   GitHub, Mercurial" note — both are accurate and readable as-is.
8. **Rename "Bead handling" → "Bead lifecycle"** to match the doc and prompt.
9. **Optional but helpful:** add a small label on the Commit finalizer → Commit skill
   arrow noting "checks dirty repos + selects skill" so the finalizer's role as a gate
   is visible at a glance.

These changes bring the diagram back into alignment with both `docs/commit_workflows.md`
and the actual `CommitWorkflow.run()` implementation, and address the highest-impact
clarity gaps.
