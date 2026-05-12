---
diagram: docs/images/sase-component-communication.png
embedding_docs:
  - docs/architecture.md
  - docs/index.md
critique_phase_bead: sase-2s.4
regen_phase_bead: sase-2s.14
pdf: false
---

# Critique: `sase-component-communication.png`

This diagram is the hero "how the pieces fit together" picture for `docs/architecture.md` and the home page
(`docs/index.md`, "How the pieces connect" section). It needs to read correctly on its own to a reader who has only
skimmed the home page, and it needs to be factually current with what `src/sase/` and `../sase-core/` actually ship
today.

There is no `.prompt.md` sidecar for this diagram. Intent is inferred from the architecture doc's System Boundary, State
Model, and Provider Boundaries tables, plus the home-page caption: _"Component boundaries keep TUI, daemon, workflow,
and provider concerns explicit."_

## What the diagram currently shows

- Left column: three stacked actor tiles — `User`, `Editor`, `CLI` — connected to the middle by an edge labeled
  "commands and UI actions".
- Top center: `Entry Points` box listing `ACE TUI`, `axe daemon`, `AXE daemon`, `commit` (puzzle-piece icons).
- Middle center: `Core Engine` box listing `ChangeSpecs`, `XPrompt`, `Workflows`, `Beads`, `Memory`.
- Lower center: `State & Artifacts` box listing `~/.sase`, `chats`, `logs`, `history`, `agent_meta.json`.
- Bottom center: `Plugin Packages` box listing `sase-github`, `sase-google`, `sase-telegram`, `sase-nvim`.
- Top right: `Agent Launcher` box with `prompts`, `hooks`, `mentors`, `retries`.
- Right edge: `LLM Providers` box (`Claude`, `Codex`, `Gemini`, `Jetski plugin`) and `Workspace + VCS Providers` box
  (`isolated workspaces`, `git / GitHub clone`, `submit / mail / diff`).
- Edge labels around the perimeter: "background automation", "input prompts and expand prompts", "launch or schedule
  work", "model calls and retries", "checkout, diff, submit", "persist status and transcripts", "VCS and workspace
  extensions", "provider extensions".

## Accuracy issues (graded against current code)

### A1. `Jetski plugin` is a retired provider — must be removed

The `LLM Providers` box lists `Jetski plugin` as one of four named providers. Jetski was the LLM provider shipped from
the now-retired Mercurial plugin (`sdd/research/202605/github_plugin_hook_gap_analysis.md:46`,
`sdd/epics/202605/remove_obsolete_plugin_repos.md:128`). The current set of real LLM provider modules in
`src/sase/llm_provider/` is `claude.py`, `codex.py`, `gemini.py`, `opencode.py`, `qwen.py`. Putting Jetski next to
Claude/Codex/Gemini implies it is a peer of the first-class providers, which is wrong.

### A2. `sase-google` is not a maintained plugin

The `Plugin Packages` row shows `sase-github`, `sase-google`, `sase-telegram`, `sase-nvim`. Per
`memory/long/external_repos.md`, the maintained sibling plugin repositories are `sase-github`, `sase-telegram`,
`sase-nvim` (plus `sase-core`, which is not a plugin but the Rust core). There is no `sase-google` repo, package, or
entry point in this codebase or in the listed external repos. This is either a placeholder that was never replaced or a
stale reference to a removed Google-specific helper that lived inside the retired Mercurial plugin
(`sdd/research/202605/public_release_process_and_install_research.md:178`).

### A3. The Rust core is invisible

`docs/architecture.md:83` calls out the **required** `sase_core_rs` extension as the backend boundary, and
`docs/rust_backend.md` enumerates the operations that cross it (ChangeSpec parsing/queries, status transitions, git
output parsing, notification reads and mutations, agent artifact scanning, agent launch preparation, and the entire bead
data layer). `memory/short/rust_core_backend_boundary.md` makes this a project-level litmus test: shared backend
behavior belongs in `../sase-core/crates/sase_core`, with Python calling through `sase_core_rs`. None of this appears in
the diagram. A reader would walk away believing the `Core Engine` (ChangeSpecs, Beads, etc.) is pure Python.

### A4. ACE and Axe are demoted to bullets, not named components

`docs/architecture.md:13–14` treats ACE (the TUI for ChangeSpecs/agents/notifications) and Axe (background
hook/mentor/workflow orchestrator) as first-class system areas with their own pages. In the diagram they are reduced to
bullet entries inside `Entry Points`. ACE in particular both reads (state, agents, notifications) and writes (user
actions, dispatched runs) — it is not just a doorway, and it does not belong in a row with `commit` script invocations.

### A5. `Notifications` is missing as a state surface

`docs/architecture.md:59` lists notifications as one of seven durable state stores, with its own Rust-backed
read/mutation API. The diagram folds everything into `State & Artifacts` without showing the notification store. Since
one of the diagram's whole jobs is showing how ACE, axe, and the mobile gateway share state without a live chat,
omitting notifications is a meaningful gap.

### A6. SDD is missing

`docs/architecture.md:19` and `:55` make SDD (`sdd/` or `.sase/sdd/` for plans, epics, legends, myths, and research
notes) a top-level primitive alongside ChangeSpecs and beads. The Core Engine box names `ChangeSpecs`, `Beads`, `Memory`
but not `SDD`. The home page even links to it from "Durable work records". A reader of the diagram would not learn that
the durable plan/epic artifact lives next to ChangeSpecs and Beads.

### A7. Provider layer is under-drawn vs. the architecture table

`docs/architecture.md:69–75` enumerates **five** provider boundaries: LLM, VCS, Workspace, Resource plugins, and
Integration APIs. The diagram shows LLM as one box and collapses VCS+Workspace into a single box. Resource plugins and
the Integration API boundary (mobile gateway, editor JSON helpers, fixed bridge contracts) are not depicted at all, even
though `Plugin Packages` is one of the seven boxes on the page.

### A8. `sase run` and the CLI dispatch are not shown as an entry

The CLI tile on the left says "CLI" but `Entry Points` does not contain `sase run`, which is the canonical agent-launch
entry point per `docs/architecture.md:31` ("Most agent work enters through `sase run`, ACE, axe agent chops, bead epic
execution, or mobile/editor helper bridges"). `commit` is shown but `sase run` — the more common path — is not.

### A9. `Entry Points` appears to list the axe daemon twice

The current rendering reads `ACE TUI · axe daemon · AXE daemon · commit`. Either this is two casing variants of the same
component or one of them was meant to be something else (e.g. `sase run` per A8, or `mobile gateway`). Either way it is
confusing as shipped.

### A10. The `Memory` node is ambiguous

"Memory" inside Core Engine could mean (a) the memory xprompt mechanism that injects tier‑2 dynamic memory into prompts,
(b) the agent-side conversational memory persisted in `chats/`, or (c) the per-project memory directory under `memory/`.
These are different things. A regen should label this precisely (e.g. `Memory xprompts`) or drop the node.

### A11. Workspace claim/running-field state is not shown

`memory/short/workspaces.md` and `docs/architecture.md:60` describe ephemeral `sase_<N>` workspace clones managed via
the running-field workspace claim protocol — this is what the "Workspace + VCS Providers" box quietly depends on for
`isolated workspaces`. The diagram labels it but does not show that the claim state is itself durable shared state
(transferred across retry-spawn, locked across parallel agents). For a "component communication" picture, the claim
handoff is one of the more distinctive flows and should at least be hinted at by an arrow back into State.

## Clarity issues (would a new user understand this?)

### C1. The actor column is muddled

`User`, `Editor`, `CLI` are stacked as if they were three peer actors. CLI is a _channel_ the user uses, not a separate
actor. New readers ask "is the CLI a person?" The intended grouping is `User → (via Editor or CLI) → SASE`. The current
layout invites the wrong reading.

### C2. No legend for the puzzle-piece icon

Puzzle-piece glyphs appear inside `Entry Points`, `Agent Launcher`, `LLM Providers`, and `Plugin Packages`. They
presumably mean "pluggable / replaceable". Without a tiny legend in a corner, a new reader has to guess.

### C3. Color semantics are unexplained

Boxes use distinct hues (green, teal, blue, dark navy). It is not clear whether color encodes a category (Python host vs
Rust core, sync vs async, internal vs external) or is purely aesthetic. If it is meaningful, document it; if not,
flatten to one or two colors so the reader does not look for a key that does not exist.

### C4. Arrow labels are small and crowded

The perimeter labels ("background automation", "launch or schedule work", "checkout, diff, submit", "persist status and
transcripts", "VCS and workspace extensions", "provider extensions") are small and several overlap routing paths. At
thumbnail size on the home page they are unreadable.

### C5. Direction of `Plugin Packages` edges is unclear

`Plugin Packages` is shown at the bottom with edges fanning up. A new reader cannot tell which package extends which
provider — does `sase-github` plug into VCS? Workspace? Both? Does `sase-telegram` plug into LLM, notifications, or
workflows? (It actually plugs into axe chops and notifications.) The current single edge labeled "VCS and workspace
extensions" plus "provider extensions" elides this.

### C6. No read vs write distinction on State & Artifacts

ACE is primarily a _reader_ of agent metadata and a _writer_ of ChangeSpec edits and launch dispatch. Axe writes
notifications and ChangeSpec hook results. Agent Launcher writes prompts, chat transcripts, and `agent_meta.json`. All
of these are drawn as identical undirected/lightly-directed lines into one box. A reader cannot reconstruct the
dataflow.

### C7. The Agent Launcher node is overloaded

`prompts · hooks · mentors · retries` are all stuffed inside one box. Hooks and mentors are _axe_ concerns
(`docs/axe.md`), not launcher mechanics; `retries` is an LLM-provider concept (`ProviderRetryConfig`). Combining them in
the launcher box makes it look monolithic. A regen should either split these or label the box as "Launch + lifecycle"
and put hooks/mentors with axe.

### C8. No timeline or ordering cue for the launch flow

`docs/architecture.md:31–42` describes a numbered 9-step launch flow. A reader staring at this diagram cannot see the
order of operations. A small numbered overlay along the launch edges (`1` parse, `2` resolve workspace, `3` expand
xprompts, `4` invoke LLM, `5` persist) would dramatically aid comprehension without changing the topology.

## Concrete suggestions for the regenerated diagram

The regen phase (`sase-2s.14`, `codex/gpt-5.5`) should:

1. **Rebuild `LLM Providers`** as `Claude`, `Codex`, `Gemini`, `OpenCode`, `Qwen`, plus a generic `Plugin LLM` slot
   showing extensibility. Drop `Jetski plugin`.
2. **Rebuild `Plugin Packages`** as `sase-github` (VCS + Workspace), `sase-telegram` (axe chops + notifications),
   `sase-nvim` (editor integration). Show `sase-core` as a separate, labeled Rust core component, **not** as a sibling
   plugin. Drop `sase-google`.
3. **Add a Rust core layer** beneath/within `Core Engine`, labeled `sase_core_rs (Rust core)`, with a short list of
   crossing ops (parsing, beads, notifications, agent scan, launch prep). Make it visually distinct (different fill /
   "Rust" tag) so a reader sees the language boundary.
4. **Surface `Notifications`** as its own state node alongside `State & Artifacts`, or inside it but visibly separate,
   with an arrow back to ACE / mobile gateway.
5. **Add `SDD`** as a peer to `ChangeSpecs` and `Beads` inside the durable-record group; consider renaming `Core Engine`
   into two stacked groupings: `Work Records (ChangeSpecs · Beads · SDD)` and
   `Engine (XPrompt · Workflows · Memory xprompts)`.
6. **Promote `ACE` and `Axe`** to first-class boxes (top-left and top-right respectively, or stacked). Move `commit` and
   `sase run` into a clearly-labeled `CLI commands` cluster. Resolve the duplicate `axe daemon / AXE daemon` row.
7. **Re-stack the actor column** so `User` is on top and `Editor`/`CLI` are children underneath, captioned "user
   interacts via either", to break the three-peer misreading.
8. **Add a legend** explaining (a) the puzzle-piece icon ("= pluggable provider / extension point") and (b) the
   color/fill convention ("Python host" vs "Rust core" vs "External plugin" vs "Durable state on disk").
9. **Disambiguate plugin edges**: route each plugin package to the specific provider(s) it extends (e.g.
   `sase-github → VCS provider + Workspace provider`, `sase-telegram → axe chops + Notifications`,
   `sase-nvim → Integration API`).
10. **Number the launch flow** along the edges ACE/axe/CLI → Agent Launcher → LLM Provider → Workspace/VCS → State &
    Artifacts using small circled digits matching the 9-step list in `docs/architecture.md:31–42` (or a condensed 5-step
    version).
11. **Use larger, higher-contrast edge labels** so the diagram remains readable as a home-page thumbnail.
12. **Reference `docs/images/infographic-style-brief.md`** in the regen prompt to keep visual style aligned with the
    rest of the docs diagram set.

A regen that addresses A1–A4 and C1–C2 alone would already remove the most embarrassing inaccuracies; the remaining
items are quality-of-life improvements.
