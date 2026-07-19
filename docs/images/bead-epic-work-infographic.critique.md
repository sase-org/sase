---
pdf: false
---

# Critique: `bead-epic-work-infographic.png`

This is a clarity-and-accuracy review of `docs/images/bead-epic-work-infographic.png`, the diagram embedded near the top
of `docs/beads.md`. The diagram is reviewed against:

- the existing prompt sidecar (`docs/images/bead-epic-work-infographic.prompt.md`)
- the embedding doc (`docs/beads.md`)
- the current code paths (`src/sase/bead/work.py`, status/dependency model, multi-workspace read/write rules)

## What the diagram currently shows

Three visual zones:

- **Top-left — "Bead model"**: a _Plan bead_ card with tier chips (`plan / epic`); below it three smaller cards
  (`Phase child` / `Depends on` / `Blocked phase`) with sub-labels `ready · blockers closed`, `ID: parent.N`, and
  `waiting on dependency`.
- **Bottom-left — "Multi-workspace reads"**: two folders (`sibling workspace`, `primary writes`) connecting to a SQLite
  cylinder labeled `SQLite cache` and a stack labeled `Rust mutations`.
- **Right — "Epic execution"**: a trigger box `sase bead work <epic>` flowing into three horizontal wave bands
  (`Kahn wave 1`, `Kahn wave 2`, `Kahn wave 3`) and a final `land` node labeled `waits on all phases`. The waves carry
  the captions `pre-claimed phase agents`, `dependency arrows`, and `one agent per phase`.

## Clarity issues a new user would hit

1. **The three wave captions read like sequential properties of the three waves, but they are properties of all waves.**
   A reader will parse this as "wave 1 is where pre-claiming happens; wave 2 is where dependency arrows happen; wave 3
   has one agent per phase," which is wrong. All phases are pre-claimed before any agent launches; every wave has one
   agent per phase; dependency arrows exist between every adjacent wave.
2. **The trigger → execution chain is visually flat.** The `sase bead work <epic>` box arrows directly into wave 1,
   hiding the three side-effects the command performs first: flip `is_ready_to_work`, pre-claim every phase bead, then
   dispatch the multi-prompt. A new reader cannot tell _when_ pre-claiming happens relative to launch.
3. **The bead-model panel only depicts two phase states (ready, blocked), not three.** `docs/beads.md` calls out
   `open ○`, `in_progress ◐`, and `closed ✓`. The infographic omits `in_progress` entirely, which is unfortunate because
   in-progress is exactly the state a phase enters during the pre-claim step depicted on the right.
4. **The storage zone does not show JSONL.** `docs/beads.md` is explicit that bead storage is _dual_: SQLite is the
   local cache; `issues.jsonl` is the git-portable, git-tracked file; the SQLite database is rebuilt from JSONL on fresh
   clones. The diagram shows only a SQLite cylinder and a `Rust mutations` stack — there is no recognizable
   `issues.jsonl` file element. The "git-portable JSONL" claim from the alt text is invisible in the image.
5. **"Multi-workspace reads" with only two folders understates the model.** The doc describes N-way merged reads across
   `myproject/`, `myproject_2/`, `myproject_3/`, etc. Showing one sibling workspace + one primary reads as "the
   multi-workspace story" risks looking like a two-host setup.
6. **`Rust mutations` is labeled but its direction is ambiguous.** The thick stack sits between the SQLite cylinder and
   the workspace folders; a reader cannot tell whether Rust _writes into_ SQLite or _reads from_ it (it does both, but
   the dominant write path is implicit).
7. **The bottom-left and top-left panels share a common edge with no gutter.** The zone boundary is weak; the eye flows
   from `Blocked phase` directly into `sibling workspace`, and the implicit grouping is lost.
8. **The land agent's "waits on all phases" arrow only visibly returns from wave 3.** The text claim is correct, but
   visually it looks like the land agent waits only on the final wave's nodes, contradicting the actual semantics
   encoded in `EpicWorkPlan.land_waits_on` (every launched phase agent name, not only leaves).

## Specific accuracy errors against current code

The accuracy bar is whether the diagram matches today's `src/sase/bead/work.py`, `docs/beads.md`, and the bead
status/dependency model.

1. **"pre-claimed phase agents" caption attached to wave 1 only — incorrect.** `sase bead work` pre-claims _every_ phase
   bead in the plan (`status=in_progress`, `assignee=<phase_bead_id>`) _before_ dispatching the multi-prompt; this is
   not a wave-1 property. The caption should describe a global pre-launch step, not a wave-band property.
2. **"one agent per phase" caption attached to wave 3 only — incorrect.** This is true of every wave. Each
   `PhaseAssignment` becomes one segment with `%id:!<phase_bead_id>` plus a `#work_phase_bead:<bead_id>` reference
   (`work.py:338`–`345`). It is not a wave-3-specific behavior.
3. **"dependency arrows" caption attached to wave 2 only — vacuous.** Dependency arrows are how the Kahn schedule is
   _built_; they are not a property of any one wave. The label adds nothing where it sits and would be better used to
   explain what an arrow between two waves represents (`%w:<phase>` blocker waits implemented via `done.json`).
4. **The land node is rendered as if it waits only on wave 3.** The current behavior — and the audit note already in the
   prompt sidecar — is that the land agent waits on **every** launched phase agent, not just the leaf wave. The prompt
   sidecar correctly labels this `waits on all phases`, but the visual arrow geometry should match: the land node needs
   incoming wait edges from at least one node in each of waves 1, 2, and 3, not just wave 3.
5. **`is_ready_to_work` is missing from the trigger flow.** `sase bead work` flips `is_ready_to_work=True` on the epic
   plan bead before launching (`work.py` handler logic, documented at `docs/beads.md:263`). The diagram has no element
   representing this state transition on the plan bead.
6. **No representation of the dual SQLite/JSONL storage.** `issues.jsonl` is the git-tracked file that survives fresh
   clones; SQLite is the gitignored cache. The diagram shows only the cache and a `Rust mutations` stack, omitting the
   JSONL artifact and the export/rebuild edges that connect them. This is the central storage-architecture claim of
   `docs/beads.md` and the diagram silently drops it.
7. **The status set is incomplete.** Phases have three statuses; the diagram models two. The `in_progress` (`◐`) state
   is _exactly_ the state pre-claiming sets the phase to before its agent launches — so showing it would also tighten
   the link between the bead model and the epic execution panels.
8. **Tier chips order is fine but tier semantics are not visualized.** The chips (`plan / epic`) are rendered as
   peer-equivalent options on a single Plan bead. The doc describes meaningful asymmetry: only `epic`-tier plans accept
   `sase bead work`, while `plan` records do not launch the work DAG. The current diagram does not hint at this — a new
   reader will think any tier flows into the epic-execution panel, which is wrong.
9. **"primary writes" framing is mildly misleading.** Reads are merged across all workspaces; writes go to the _primary_
   workspace only. The diagram does show this, but the `primary writes` label is on a _folder_ rather than on the _write
   arrow_, which makes it ambiguous whether the folder itself is the "primary" or whether the arrow into SQLite is the
   write path. Moving the label onto the write edge would remove the ambiguity.

## Concrete suggested changes for the regenerated image

These are scoped so the regen agent can act on them directly without rewriting the prompt sidecar from scratch.

1. **Lift the three wave captions out of the wave bands and consolidate them into a single header strip above all three
   bands**, e.g.
   `All phases pre-claimed (status=in_progress) before launch · one agent per phase · dependency arrows = %w blocker waits`.
   Replace the per-band captions with neutral wave indices only (`Wave 1`, `Wave 2`, `Wave 3`).
2. **Redraw the land-agent edges so it has at least one incoming wait arrow from each wave**, not only from wave 3. This
   visually matches `land_waits_on` carrying every launched phase agent name. Keep the existing `waits on all phases`
   raster label.
3. **Add a small staged-trigger ribbon between the `sase bead work <epic>` box and Wave 1** with three numbered chips:
   `1. flip is_ready_to_work`, `2. pre-claim phase beads`, `3. dispatch multi-prompt`. This makes the command's actual
   side-effect order legible.
4. **Replace the storage panel** so it shows two distinct artifacts: a SQLite cylinder labeled
   `beads.db (cache, gitignored)` and a JSONL document stack labeled `issues.jsonl (git-tracked)`, with a one-way
   `Rust mutations` arrow from a Rust core glyph into SQLite, a one-way `JSONL export` arrow from SQLite into the JSONL
   stack, and a one-way `rebuild on stale/fresh-clone` arrow back from JSONL into SQLite. This is the dual-storage claim
   from `docs/beads.md` made visible.
5. **Add an `in_progress ◐` status pip alongside the existing `ready` and `blocked` indicators** in the bead-model panel
   so all three statuses are represented; ideally place an `◐` near a phase card in the epic-execution panel as well to
   visually connect the pre-claim step to the data model.
6. **Show three workspace folders, not two**, to convey N-way merging more accurately, and **move the `primary writes`
   label off the folder onto the write arrow itself**. The merged-read lens stays the same.
7. **Differentiate the tier chips on the Plan bead.** Either color-code the `epic` chip and add a thin arrow from it to
   the `sase bead work <epic>` trigger box, or add a tiny caption under the chips like
   `epic -> bead work · plan -> planning record`. This corrects the false impression that both tiers feed the same
   execution flow.
8. **Tighten the gutter** between the bead-model zone and the storage/multi-workspace zone with a faint divider or
   background tint shift, so the three zones read as three.
9. **Keep the existing 16:9 layout, neutral palette, no-text-in-base-render policy, and DejaVu-Sans deterministic
   labels.** Style consistency with peer infographics under `docs/images/` should be preserved per
   `docs/images/infographic-style-brief.md` (referenced by the regen-phase pattern in
   `sdd/epics/202605/diagram_review.md`).

## Out-of-scope (do not change in this critique phase)

Per the epic plan, this phase only writes the critique. The PNG, the prompt sidecar
(`docs/images/bead-epic-work-infographic.prompt.md`), and the embedding doc (`docs/beads.md`) are unchanged. The regen
phase (`sase-2s.11`) is responsible for applying the suggestions above.
