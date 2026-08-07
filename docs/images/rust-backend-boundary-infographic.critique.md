---
diagram: rust-backend-boundary-infographic.png
embedding_doc: docs/rust_backend.md
prompt_sidecar: docs/images/rust-backend-boundary-infographic.prompt.md
critique_date: 2026-05-10
pdf: false
---

# Critique: `rust-backend-boundary-infographic.png`

This critique reviews the infographic embedded at the start of the **Architecture** section of
`docs/rust_backend.md`. The image is a 1600×900 layered diagram with four horizontal layers (Python
host → `sase.core` facade → `sase_core_rs` PyO3 extension → `../sase-core` Rust workspace), an
"ownership" right-side panel, a small "Contract loop" bottom-right panel, and a set of left-side
annotation pills next to each layer.

The original prompt is preserved in `rust-backend-boundary-infographic.prompt.md`; deterministic
ImageMagick labels were composited on top of a no-text background. This critique is grounded in the
current `docs/rust_backend.md` text and in the Rust-backed binding inventory still present in
`src/sase/core/`.

## Summary

The diagram captures the headline shape of the boundary correctly — four stacked layers with a clear
"required Rust boundary, no Python fallback" connector — but it under-represents the _breadth_ of
the Rust-owned surface and over-loads the bottom layer with three box labels that conflate unrelated
domains. The biggest single gap is **bead data operations**, which are arguably the largest
Rust-owned category in the doc but appear only as a parenthetical "work DAG" inside a mashed-up box.
Several side annotations are visually cramped to the point of being unreadable at GitHub Markdown
width.

## Clarity issues a new user would hit

1. **Bottom-layer boxes mash unrelated domains together.** The `../sase-core` Rust workspace layer
   shows three boxes labeled roughly "parse + notifications", "status/launch + launch fanout + work
   DAG", and "git parsers". Project parsing and the notification JSONL store are separate concerns;
   status helpers, agent launch preparation, and the bead work-plan DAG are three independent
   migrations. Combining them suggests they're one cluster, which is misleading. A new reader cannot
   answer "where do beads live?" or "where does the agent artifact scanner live?" from this layer.
2. **Left-side annotations are dense and partially garbled.** The vertical column of left-side
   labels reads (top to bottom) "file-path APIs", "VCS / workspace plugins", "xprompt resolution",
   and a phrase that renders as "user prompts process,checkout/orchestration TUI + query → API". The
   last label is hard to parse — it appears to collide with a neighbouring annotation or wrap
   awkwardly, and the comma-without-space hints at a label-composition bug rather than an
   intentional phrase. A new user has no path from these annotations to the four host
   responsibilities the doc actually lists (subprocess orchestration, TUI rendering, plugin entry
   points, filesystem mutation outside the prepared prompt path).
3. **The "required Rust boundary: no Python fallback" connector is the single most important concept
   and is buried.** It sits as a thin centered pill between the facade and extension layers. A new
   reader's eye is pulled to the four horizontal bands and the two side panels; the "required, no
   fallback" callout — which is the entire reason the diagram exists — does not visually dominate.
   The "no Python fallback" framing is a load-bearing claim of the doc (no `SASE_CORE_BACKEND` env
   var, no in-process fallback) and deserves the most-prominent typographic weight.
4. **Two right-side panels overlap in meaning without clearly differentiating.** The upper-right
   "Rust owns" panel lists ownership groups (parser/query corpus, notification JSONL store, agent
   scan cleanup, bead reads mutations DAG); the lower-right "Contract loop" panel lists
   fixtures/tests/releases. Both are amber/right-side, both are the _same_ visual treatment, and
   both overlap with content already in the bottom layer. A reader can't tell whether the ownership
   panel is a legend, a duplicate summary, or an additional category.
5. **No flow direction.** The boundary is fundamentally one-directional at runtime: Python calls
   into Rust through a stable wire record, Rust returns wire records, Python re-hydrates them. The
   diagram has connectors between layers but no arrows, no "calls" verb, and no indication that data
   crosses as wire records (the "stable wire records" pill in the facade is a label, not a
   visualised flow). A new reader could plausibly read it as bidirectional or peer-to-peer.
6. **Contract loop is too generic.** The "Contract loop" panel says "fixtures, tests, releases" with
   stylised arrow marks. The doc's contract surface is much more specific: `sase core health` exit
   code is the runtime contract, the golden corpus under `tests/core_golden/` is the cross-language
   reference, and `../sase-core/.../tests/` parity tests gate any change. None of those names
   appear; a new user reading "fixtures, tests, releases" cannot derive the actual ops contract from
   the picture.
7. **Label hygiene at GitHub width.** Phase 7 QA notes in the prompt sidecar already record that
   overlapping layer, ownership, and contract-loop labels were tightened — but at the embedded width
   several labels (`required Rust boundary: no Python fallback`, `host-owned APIs`, the bottom-layer
   compound boxes, and the left-side garbled label) still feel cramped against their containers.
   There is no slack for users on a narrow theme or a smaller viewport.

## Accuracy errors against current code

These are checked against `docs/rust_backend.md` (the current state) and the Rust-backed binding
categories the doc enumerates.

1. **Bottom layer omits roughly half the Rust-owned categories.** The doc enumerates current
   Rust-backed operation groups (project parsing; project lifecycle helpers; query
   parsing/evaluation including the persistent query corpus; agent artifact scan/index; status
   helpers + planner; git query parsers; notification JSONL store; agent cleanup planning +
   mutations; agent launch preparation/spawn/fan-out/RUNNING-field claims; bead data operations).
   The bottom layer's three boxes ("parse + notifications", "status/launch + launch fanout + work
   DAG", "git parsers") fold those groups into three blended labels. **Project lifecycle**, **query
   corpus**, **agent artifact scan/index**, and **agent cleanup** are not surfaced as their own
   boxes — the side "Rust owns" panel partially recovers some of them, but the layered visual itself
   is wrong.
2. **Bead data operations are massively underweighted.** Beads are the most recently migrated and
   one of the largest surfaces (read queries, merged-workspace reads, mutations, JSONL codecs,
   sync-clean checks, deterministic epic work planning, and the early `sase bead` CLI fast path;
   tracked as its own epic `sdd/epics/202605/bead_rust_backend_migration.md`). The bottom layer
   reduces this to "work DAG" inside a compound box. The right-side ownership panel adds "bead reads
   mutations DAG" as a single line item. Neither treatment reflects that the entire `sase bead` data
   path (not just the work DAG) is Rust-owned.
3. **`host-owned APIs` pill in the facade layer is unanchored.** The doc names the specific
   Python-owned facade surfaces: `parse_project_file` (file-path API), `build_query_context` /
   `evaluate_query` / `evaluate_query_with_context`, `build_changespec_graph_index`, and
   `transition_changespec_status`, plus several host responsibilities for agent launch, agent
   cleanup, and beads. The diagram surfaces none of these by name. A reader cannot tell _which_
   facades stay on the host versus which call through Rust; the result is a generic "some stay in
   Python" gesture.
4. **`binding probes` pill in the extension layer is anonymous.** The doc names the actual probes
   (`parse_query`, `agent_launch_wire_schema_version`, `plan_agent_launch_fanout`,
   `bead_cli_execute(["show", ...])`) and names the command that exposes them (`sase core health`,
   with a `-j` JSON mode and exit-code contract). None of that appears; "binding probes" floats with
   no link to `sase core health`.
5. **Mobile gateway is invisible.** `../sase-core/` ships **two** consumer surfaces from the same
   workspace: the `sase_core_py` PyO3 extension and the `sase_gateway` standalone Rust HTTP server
   (`docs/rust_backend.md` §Mobile Gateway, plus `docs/mobile_gateway.md`). The diagram only depicts
   the PyO3 path, which is fine _if_ the title is scoped accordingly — but the bottom-layer label
   says "`../sase-core` Rust workspace owns deterministic cores", which is broader than the rendered
   content. Either narrow the layer's title to "PyO3 extension cores" or add a small adjacent box
   for the gateway.
6. **PyPI distribution / version pin is missing.** The doc opens by saying
   `sase-core-rs>=0.1.1,<0.2.0` is a hard runtime dep and is pulled from PyPI as a prebuilt wheel;
   the strict-loader / no-fallback story is enforced _because_ that wheel must be present. The
   diagram shows the extension as a layer but does not depict the PyPI/wheel handoff between
   `../sase-core` and `sase_core_rs`. For a "boundary and ownership model" infographic this is the
   user-facing edge of the boundary and should be visible.
7. **`stable wire records` is a single pill but the surface has ~10 modules.** The doc lists
   `wire.py`, `wire_conversion.py`, `notification_store_wire.py`, `agent_scan_wire.py`,
   `agent_cleanup_wire.py`, `agent_launch_wire.py`, `bead_wire.py`, `status_wire.py`,
   `status_wire_conversion.py`, `git_query_wire.py`. A single pill is acceptable shorthand, but at
   minimum the diagram should signal multiplicity (e.g., a stack of cards or "10+ wire schemas");
   the current single-pill rendering implies one record type.
8. **Contract loop names the wrong artifacts.** The bottom-right panel reads "fixtures, tests,
   releases" with a loop. The doc's contract surface is concrete: `sase core health` exit code,
   golden corpus (`tests/core_golden/myproj.sase`, `myproj-archive.sase`, `inline_snapshot` JSON),
   Rust parity tests in `../sase-core/.../tests/`, and the publish-workflow `install-smoke` job.
   "Releases" in particular is misleading — the contract is _not_ tied to release cadence; it is a
   per-PR golden-corpus + parity-test gate enforced on every change.
9. **"`sase.core` facade" middle layer omits `health.py`.** Among the listed facade modules in the
   doc table is `health.py`. The diagram omits any reference to the facade's own health surface —
   which is the user-visible front of the contract loop and would tie the bottom-right panel to a
   real entry point.
10. **"agent scan cleanup" in the right-side ownership panel runs two domains together.** Agent
    artifact scan (`scan_agent_artifacts`, `rebuild_agent_artifact_index`,
    `query_agent_artifact_index`) and agent cleanup planning
    - mutations (dismissed index/bundle writes, artifact-marker deletion, workspace-release
      rewrites, kill marking) are independently scoped in the doc. The compound label flattens them
      into one item.

## Concrete suggested changes for the regenerated image

These are change requests the regen agent should pass into its GPT image prompt and/or its
post-processing label script, scoped to the diagram only.

1. **Re-bin the bottom layer to one box per Rust-owned category, with consistent grain.** Use the
   doc's current groups directly: project parsing, project lifecycle helpers, query parse + corpus,
   agent artifact scan/index, status helpers/planner, git query parsers, notification JSONL store,
   agent cleanup, agent launch + RUNNING claims, and **bead data ops** (reads, mutations, work-plan
   DAG, CLI fast path). Use a grid or grouped chips with enough padding at 1600×900.
2. **Promote "required Rust boundary — no Python fallback" to a heavyweight horizontal divider**
   between facade and extension layers, not a thin centered pill. Use the amber accent and a
   noticeably larger type weight than any other annotation, so it reads as the load-bearing claim of
   the diagram.
3. **Add a single `Python → Rust` arrow** crossing that divider (one direction), with "wire records"
   as the arrow label. This visually cements that data crosses as serialised records, not direct
   object references, and that the call direction is one-way at runtime.
4. **Replace the left-side annotation column with a concise legend block** listing the four host
   responsibilities the doc actually names: subprocess orchestration; TUI rendering; plugin entry
   points; filesystem mutation outside the prepared prompt/output path. Drop the garbled "user
   prompts process,checkout/orchestration TUI + query → API" label entirely.
5. **Rename the `host-owned APIs` pill to `Python-owned facades`** and ground it with three example
   names from the doc: `parse_project_file`, `evaluate_query` / `evaluate_query_with_context`,
   `transition_changespec_status`.
6. **Rename the `binding probes` pill to `sase core health probes`** and list the four probes
   inline: `parse_query`, `agent_launch_wire_schema_version`, `plan_agent_launch_fanout`,
   `bead_cli_execute`.
7. **Rework the bottom-right "Contract loop" panel** to name the three contract artifacts the doc
   actually uses: _`sase core health` exit code_ (runtime), _`tests/core_golden/` corpus_
   (cross-language reference), _Rust parity tests in `../sase-core/.../tests/`_ (per-PR gate). Drop
   "releases" — the contract is not release-cadence-bound.
8. **Add a small "PyPI wheel" badge** between the `sase_core_rs` layer and the `../sase-core` layer,
   captioned `sase-core-rs>=0.1.1,<0.2.0`. This makes the user-visible edge of the boundary
   explicit.
9. **Either narrow the bottom-layer title to "PyO3 extension cores" or add a small `sase_gateway`
   sidecar box** adjacent to (not inside) the `../sase-core` layer, so the diagram's framing is
   honest about what the workspace ships.
10. **Indicate multiplicity on the `stable wire records` pill** — a stack-of-cards icon, or a count
    like "10+ wire schemas: parser, query, status, scan, notif, cleanup, launch, bead, git, …" — so
    the surface area reads as a family rather than a single record type.
11. **Drop the upper-right "Rust owns" ownership panel** once the bottom layer is re-binned per (1).
    It currently duplicates content; once each Rust-owned category has its own box, the side panel
    is redundant clutter.
12. **Tighten the visual hierarchy** so the order of attention is: (a) the four labelled layers, (b)
    the boundary divider, (c) the wire-record arrow, (d) the contract-loop panel — in that order.
    Pull every other annotation back a notch (smaller type, lower contrast) so the load-bearing
    concepts dominate.

## Out of scope for this critique

- The PNG, the prompt sidecar, and `docs/rust_backend.md` itself are unchanged by this phase per the
  epic plan in `sdd/epics/202605/diagram_review.md`. Phase 13 (`sase-2s.13`) owns the regenerated
  image, the updated prompt sidecar if needed, and any related label-composition tooling.
- Style consistency across all ten infographics in the diagram-review epic is the regen phase's
  concern; this critique only addresses what the rust-backend-boundary diagram alone gets right and
  wrong against its embedding doc.
