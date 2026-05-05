# Unified Artifact Graph — Prompt Review & Implementation Research

Refines the earlier prompt review of the "unified artifact tracking" proposal. Builds on
[`202604/artifacts_panel.md`](../202604/artifacts_panel.md) (which is TUI-focused) by extending the
analysis to the data model, the Rust-core boundary, beads, the new `sase artifact` CLI, and the
`/sase_artifact` skill.

The earlier file remains the authoritative reference for the TUI panel surface, file-panel /
thinking-panel obsolescence, and current artifact discovery layers. This file does not duplicate
that material; it focuses on the parts of the new prompt that were either ambiguous or out of scope
in 202604.

---

## 1. What the new prompt added beyond 202604

The 202604 file scopes **a unified Artifacts Panel inside the TUI**. The current prompt is
substantially broader and adds:

- A **typed artifact graph** spanning Project, ChangeSpec, Commit, Directory, Bead, Agent, and
  Agent-Thoughts — not just Agent-produced files.
- A **root directory artifact** at `/` and a graph-wide invariant ("every artifact must connect to
  the root").
- A **Rust-core requirement** ("use sase-core as much as possible and appropriate").
- A new **`sase artifact` CLI** with `add / remove / list / show / graph` subcommands.
- A **`/sase_artifact` skill** modeled on `/sase_agents_status`.
- A **TUI launch contract** keyed off the active tab (AXE → root, CLs → current ChangeSpec, Agents
  → current agent).

Most of the open questions in §9 of 202604 (tab-vs-panel, retry-chain handling, URI scheme, live
preview vs modal, prompt-panel ownership, deep watcher cadence, structured marker rendering)
remain open here and are not re-litigated below.

---

## 2. Identity model — the biggest gap

The prompt says "for file artifacts, this will be the file path; for string artifacts, this will be
the string itself." The codebase shows that this collapses several distinct namespaces into one
key, and at least four of those namespaces collide in real workloads.

### 2.1 Identity sources that exist today

| Entity        | Real identity in the repo                                              | Source |
|---------------|-----------------------------------------------------------------------|--------|
| Agent         | `(agent_type, cl_name, raw_suffix)` tuple — `agent_name` is mutable   | `src/sase/ace/tui/models/agent.py:406-408` |
| Project       | Directory name under `~/.sase/projects/`                              | filesystem |
| ChangeSpec    | `cl_name` inside a project's `.gp`                                    | `<project>.gp`, `<project>-archive.gp` |
| Commit        | Position inside a ChangeSpec's COMMITS drawer (an ordinal `\| N: …`)  | ChangeSpec wire — `parser.rs` |
| Bead          | `{prefix}-{base36}` globally, plus `{parent}.{N}` for phase children  | `bead/ids.py:45-83` |
| Artifact dir  | `(project, workflow, timestamp)` triple                               | `agent_artifacts.py` (per 202604 §3.2) |
| Chat          | `~/.sase/chats/<cl_name>[-mentor_<profile>]-<timestamp>.md` file path | `agent_meta.json["chat_path"]` |

Two non-obvious facts:

1. **`agent_name` is not a stable ID.** It is set via the `%name` directive or TUI rename and can
   collide. The canonical identity is the 3-tuple above.
2. **Commit "ID `3`" is ordinal-scoped.** It only makes sense inside a single ChangeSpec's COMMITS
   drawer; reordering commits silently mutates the ID. The prompt's "use the COMMITS entry number"
   inherits both problems.

### 2.2 Recommended typed-ID scheme

To preserve uniqueness without forcing the rest of the design to encode tuples in strings, give
artifacts a typed ID with a scheme prefix and an opaque body:

```
file:/abs/path
dir:/abs/path
project:<project_name>
changespec:<project>/<cl_name>
commit:<changespec_id>/<ordinal>          # or commit:<sha> if stored
bead:<bead_id>                            # already globally unique
agent:<project>/<workflow>/<timestamp>    # the canonical 3-tuple
chat:<abs_path>                           # file artifact, but worth a distinct kind
```

`agent_name` becomes a display label, not the ID. This also makes `sase artifact show -i <id>`
unambiguous, which matters once the CLI exists.

---

## 3. Persistence vs derived — the second-biggest gap

The prompt mixes structurally-derivable facts (a project file is a parent of every ChangeSpec it
contains) with manually-asserted facts (`sase artifact add` must persist *something*). The repo
already has a clear separation that the design should reuse, not fight:

- **Derived from `.gp`** (Rust): project ↔ ChangeSpec ↔ commit ↔ comments ↔ deltas — already
  parsed by `../sase-core/crates/sase_core/src/parser.rs` and exposed via
  `src/sase/core/parser_facade.py`.
- **Derived from artifact dirs** (Rust): agent ↔ project ↔ workflow ↔ chat / diff / plan / pdfs /
  images — already parsed by the agent-scan facade
  (`src/sase/core/agent_scan_facade.py`, `agent_scan_wire.py`).
- **Derived from beads SQLite** (Rust): bead ↔ parent_id ↔ dependencies — already in
  `../sase-core/crates/sase_core/src/bead/{schema,read,mutation}.rs`.
- **Manually asserted**: anything `sase artifact add` writes plus any cross-cutting links the user
  wants to record (e.g., "this chat is a follow-up of that chat").

Recommendation: a single `ArtifactGraph` view that is **derived from existing stores by default**,
with a small **manual-link store** layered on top. The manual store should live next to the rest of
SASE state (e.g., `~/.sase/artifacts/links.jsonl` — append-only is enough for v1) so the TUI inotify
watcher can pick it up without a new pulse mechanism.

`sase artifact add/remove` then maps to "append/tombstone in the manual-link store"; `list/show/
graph` always merge derived + manual.

---

## 4. Edge model and tree projection

The prompt names a single edge type `parent` and several others (`created`, `worker`) but never
states the canonical direction. The repo's existing graph indexes pick one direction consistently:

- `changespec_graph_index.py` builds `children_by_parent: dict[parent_name, list[child_name]]`
  from each ChangeSpec's `parent_name` field — i.e., **child stores the link, but the index keys
  by parent**. The TUI navigates parent → children via the index.
- Beads use `parent_id` on the child (`bead/model.py:41`) and `Dependency(issue_id, depends_on_id)`
  records (`bead/model.py:27-31`) — again, the child holds the upward pointer.

Recommendation: codify this. Edges are directed `child -> parent` for `parent` type; rendering
flips them when drawing the tree downward. Document the convention in the wire schema and stick to
it for every edge type.

For the **tree projection** the panel uses, the only sane rule is: `parent` edges form the spanning
tree; everything else (`created`, `worker`, `references`, manual `related`) renders as a "Linked
artifacts" affordance off the currently-focused node. Otherwise multi-parent and cyclic structures
(e.g., a coder agent linked both to its planner and to its ChangeSpec) make the tree non-unique.

---

## 5. Per-type clarifications grounded in the code

### 5.1 Project artifact
- ID: `project:<name>` where `<name>` is the directory name under `~/.sase/projects/`.
- The prompt says "link to the root directory artifact with link type parent" — but the project
  spec file (`.gp`) actually lives at `~/.sase/projects/<name>/<name>.gp`, so the natural parent is
  `dir:~/.sase/projects/<name>`, not `dir:/`. Choose whether to flatten to root or to materialise
  the intermediate dirs (see §6).

### 5.2 ChangeSpec artifact
- ID: `changespec:<project>/<cl_name>`. Unqualified `cl_name` is **not** unique across projects.
- Active vs archived ChangeSpecs live in different `.gp` files but share the same name space within
  a project; the artifact graph must merge them under the same ID.
- "Link to the project spec file" — confirm whether the parent is the project artifact
  (`project:<name>`) or the `.gp` file artifact (`file:~/.sase/projects/<name>/<name>.gp`). The
  former is more useful for navigation; the latter is closer to what the prompt literally says.

### 5.3 Commit artifact
- The prompt's "use the COMMITS entry number" produces unstable IDs. At minimum, scope the ID
  inside the ChangeSpec: `commit:<changespec_id>/<ordinal>`. Better, store the SHA when known and
  use `commit:<sha>` (parser already extracts COMMITS records as `CommitWire`).
- Edge type from commit → ChangeSpec is missing in the prompt; should be `parent`.
- Consider edges from commit → touched file artifacts; this is achievable from `git_query/` Rust
  module without re-parsing diffs.

### 5.4 Directory artifact
- The prompt classifies directories as **string artifacts**, but directories are also where the
  root artifact lives. Treat directories as their own kind (`dir:<path>`) rather than overloading
  "string artifact".
- The "longest-parent" rule is sensible but expensive to compute over every artifact insertion. In
  practice, only materialise directory artifacts that are reachable via SASE-relevant artifacts
  (project dir, beads dir, chats dir, `~/.sase/projects/<p>/artifacts/...`). Otherwise the graph
  fills up with thousands of irrelevant `dir:` nodes.

### 5.5 Bead artifact
- ID: `bead:<bead_id>` — already globally unique (`bead/ids.py`).
- "Direct parent bead" maps cleanly to `parent_id` for phase children of an epic/legend.
- "Agent corresponding to the agent created by our epic integration" is **not stored** anywhere.
  It is inferred at `sase bead work <epic_id>` time via `EpicWorkPlan.PhaseAssignment.agent_name`
  (`src/sase/bead/work.py:24-51`), and that assignment only lives inside the ephemeral multi-prompt
  execution. To make this a graph edge, one of:
  1. Persist the `(bead_id, agent_name, raw_suffix)` mapping at launch time inside the epic-work
     handler.
  2. Treat it as a manual link the launcher writes into the manual-link store.
  3. Reverse-infer from agent metadata — risky; depends on `%name` discipline.
  Option 1 is the only robust one and is a small change to `handle_bead_work` in
  `src/sase/bead/cli.py`.
- "Link to the sdd/beads/ directory artifact" — note that `sdd/beads/` is the VC-mode default but
  non-VC mode uses `.sase/sdd/beads/` and multiple workspace dirs are scanned
  (`bead/workspace.py:158-191`). The directory link should use the resolved absolute path of the
  bead's own file, not a single hard-coded location.
- Dependencies (`Dependency.depends_on_id`) are a separate edge type; do not collapse them into
  `parent`.

### 5.6 Agent artifact
- ID: `agent:<project>/<workflow>/<timestamp>` (the existing canonical 3-tuple). `agent_name` is a
  display field, not the ID.
- Edges to derive (all already discoverable):
  - `created` → chat: `chat:<agent_meta.json["chat_path"]>`
  - `created` → diff: `file:<done.json["diff_path"]>` when non-null
  - `created` → plan: `file:<done.json["plan_path"]>` when present
  - `created` → questions log: `file:<artifacts_dir>/qa_log.jsonl` (single JSONL — there is no
    per-question file; the prompt's "one or more question file artifacts" is incorrect)
- Planner/coder relationship is via `parent_timestamp` + `role_suffix` (`.plan`, `.code`, `.q`,
  `.2…`) — see `_agent_status_overrides.py:218-228`. These deserve their own edge type
  (`followup` or `child`), not `created`.
- Retry chain (`retry_of_timestamp`, `retried_as_timestamp`, `retry_chain_root_timestamp`) — same
  treatment, separate edge type.

### 5.7 Agent Thoughts — recommend deferring v1
The prompt says "I'm not sure how this will work… make sure it looks beautiful" and explicitly
asks for a design lead. Concretely the available data sources are:

- Codex sidecar `codex_thinking.jsonl` (already parsed by `read_codex_thinking()`).
- Claude/Anthropic inline `thinking` blocks (parsed by `parse_thinking_blocks_multi()`).
- Gemini `read_gemini_log()`.

These are not stable artifact records — they are streamed reasoning fragments with model-specific
shapes. Treating each thought as an addressable node would balloon the graph (a single agent
produces hundreds of thoughts) and forces design decisions about persistence that nothing else in
the codebase has solved yet.

Recommendation: in v1, expose **one synthetic artifact per agent** of kind `thoughts:<agent_id>`
that the panel renders by re-parsing on demand using the existing thinking helpers. Defer
"individual thought artifacts" until there is a concrete navigation use case.

---

## 6. Root-anchoring is a footgun

"Every artifact must link to the root" + "root is the `/` directory artifact" produces an
uncomfortable graph. A bead at `~/projects/github/sase-org/sase_100/sdd/beads/foo.json` would need
a chain of seven `dir:` parents up to `/` to satisfy the invariant — none of which the user wants
to navigate.

Two viable interpretations:

1. **Real-filesystem ancestors materialised on demand**: only create intermediate `dir:` nodes that
   are themselves the parent of at least one non-directory artifact. Most chains collapse to one or
   two hops.
2. **Logical anchor instead of `/`**: define the root as `dir:~/.sase` (or two roots: SASE state +
   the active repo), and treat anything outside as opaque. Closer to user mental model.

Either is fine; pick one before implementation. The current wording leans toward (1) but the rest
of the prompt assumes (2).

---

## 7. Rust-core fit

`../sase-core/crates/sase_core/src/` already owns the analogous concepts for every other domain in
SASE (agent scan, ChangeSpec parser, bead store, notifications, git query, status transitions).
Adding a `graph/` module sibling to those is the natural fit. There is **no graph library in
either tree today** (no `petgraph`, no `networkx`, no `graphviz`, no `pygraphviz`); the only
existing graph-shaped code is:

- `src/sase/xprompt/graph.py` — emits Mermaid `graph TD` text from xprompt workflows.
- `src/sase/ace/tui/models/changespec_graph_index.py` — in-memory index over ChangeSpec
  parent/children for the AncestorsChildrenPanel.

Recommendation:

- Add `sase_core::artifact_graph` with: `ArtifactId` (typed enum), `Edge` (typed `EdgeKind`),
  `ArtifactGraph::build_from_state(...)` that fans out to the existing `parser`, `agent_scan`, and
  `bead::read` modules and merges their outputs, plus `traverse(id, direction)` and
  `tree_projection(root_id)`.
- Pull in `petgraph` for the in-memory representation. It is lightweight, well-supported under
  abi3, and saves a lot of bespoke adjacency code.
- Python side: `src/sase/core/artifact_graph_facade.py` + `artifact_graph_wire.py` mirroring the
  pattern in `parser_facade.py` and `agent_scan_facade.py`.
- For the manual-link store, write the JSONL in Python (small, append-only, no need for Rust
  here), pass the records into the Rust builder as an additional input.
- For `sase artifact graph`, emit Mermaid by default (matches the `xprompt graph` precedent in
  `src/sase/xprompt/graph.py`); offer `-f json` and `-f dot` as alternatives. No need to render
  images in-process.

This keeps the Python-side TUI panel as a thin consumer: it asks the Rust facade for a sub-tree,
renders it with existing widgets, and writes manual links via `sase artifact` (or via a TUI hook
that calls the same handler).

---

## 8. CLI / skill conventions to match

The existing pattern (`/sase_agents_status` + `sase agents status`) is the right blueprint. Key
constraints from the codebase:

- **Argparse-based**, registered via a `parser_<topic>.py` module under `src/sase/main/` and
  dispatched by `<topic>_handler.py`. Per-subcommand handlers live under `src/sase/<topic>/`.
- **Every option must have a short flag** (project memory, also enforced by repo convention).
- `-j / --json` for stable-shape machine output; default is rich-rendered human output.
- **Skill source**: single `src/sase/xprompts/skills/sase_artifact.md` with frontmatter
  (`name`, `description`, `skill: true`), body documents the `-j` JSON schema verbatim, run
  `sase init-skills --force` then `chezmoi apply` (per the dynamic memory).
- The skill must not be added to runtimes that don't support it; `/sase_agents_status` is on every
  runtime today, so `/sase_artifact` should follow the same matrix.

Concrete CLI surface to scope explicitly before implementation:

| Subcommand              | Purpose                          | Decisions outstanding |
|-------------------------|----------------------------------|-----------------------|
| `sase artifact list`    | Enumerate artifacts              | Filter by kind, by parent, by recency? Pagination? |
| `sase artifact show`    | Render a single artifact         | Kind-specific renderers — reuse file-panel renderers? |
| `sase artifact graph`   | Emit graph                       | Default Mermaid; root selector flag; depth limit. |
| `sase artifact add`     | Add a manual artifact or link    | "Add an artifact" implies a kind+id+metadata trio; "add a link" is a separate verb in spirit. Consider `sase artifact link add` instead of overloading `add`. |
| `sase artifact remove`  | Tombstone manual data            | Refuse to remove derived artifacts/links — return a clear error. |

The `add` / `remove` ambiguity (artifact vs link) is worth resolving before writing the parser.

---

## 9. TUI launch contract — concrete requirements

The prompt is unambiguous on the per-tab launch state, but two cases are missing:

- **AXE tab launch**: open the root artifact. This is fine but, per §6, "root" needs a definition.
- **CLs tab launch with no current ChangeSpec selected**: undefined. Fall back to the project
  artifact? Refuse? Open the root?
- **Agents tab launch with no current agent**: same question.
- **Notifications-modal context**: the existing notification helpers can deep-link to agents and
  CLs. Should `A` from a notification context follow the focused entity?

Also, the existing `A` keymap on the CLs tab triggers `AgentRunLogModal`. The prompt says the new
panel "obsoletes" this, but the actual replacement plan should cover at least:

- ChangeSpec → linked agents (already covered by today's modal).
- ChangeSpec → linked beads (new — derivable from bead `assignee`/work-plan provenance, see §5.5).
- ChangeSpec → linked commits, comments, hooks, mentors, deltas (already in `ChangeSpecWire`;
  re-using them as artifacts costs nothing).
- Agent → planner/coder/retry siblings (today's `followup_agents` + retry chain).

If the new panel doesn't cover all of these on day one, the obsoleted modal needs to stay until it
does — partial replacement will regress muscle-memory workflows.

---

## 10. Suggested v1 scope (revised)

Tightening the v1 sketch from the prior review with what the research surfaced:

1. Rust `sase_core::artifact_graph` with typed `ArtifactId` / `EdgeKind`, `petgraph` backing,
   builders that pull from `parser`, `agent_scan`, `bead::read`, and a manual-link JSONL.
2. Python facade + wire (`src/sase/core/artifact_graph_{facade,wire}.py`).
3. Manual-link store at `~/.sase/artifacts/links.jsonl` (append-only, tombstone records for
   removal).
4. Persisted `(bead_id → agent identity)` provenance written by `handle_bead_work` so the
   bead→agent edge is real, not inferred.
5. Artifact kinds in v1: `dir`, `file`, `project`, `changespec`, `commit`, `bead`, `agent`,
   `chat`. Defer `agent_thoughts` (synthetic per-agent only) and any CRS / mentor / hook artifacts
   until kind-by-kind requirements exist.
6. Tree projection uses `parent` edges only; `created`, `worker`, `followup`, `retry`, `dependency`,
   `manual` render as "Linked artifacts" off the focused node.
7. CLI: `list`, `show`, `graph` (Mermaid default; `-f json|dot`). Defer `add`/`remove` if the
   manual-link store isn't ready.
8. Skill: `src/sase/xprompts/skills/sase_artifact.md` mirroring `sase_agents_status`. Document the
   `-j` JSON schema verbatim.
9. TUI panel: defines its own `DetailPanelMode.ARTIFACTS` state; `A` keymap launches per the
   prompt; falls back to project artifact when no current entity is selected; old
   `AgentRunLogModal` stays until §9's coverage is complete.

---

## 11. Decisions still needed from the user

1. **Root anchor**: real-filesystem `/` with on-demand intermediate `dir:` nodes, or logical
   `~/.sase` root? (See §6.)
2. **Commit identity**: ordinal-scoped, SHA-keyed, or both? (See §5.3.)
3. **Bead → agent provenance**: write at `sase bead work` launch time (recommended), or live with
   inferred edges? (See §5.5.)
4. **`sase artifact add` semantics**: artifacts only, links only, or both? Consider a `link`
   subverb. (See §8.)
5. **CLs/Agents tab launch with no current selection**: fallback target?
6. **Old `AgentRunLogModal` retirement**: hard cut on v1, or coexist until the new panel covers
   ChangeSpec → linked beads + commits + agents?
7. **Manual-link store format**: append-only JSONL is the smallest workable choice; SQLite would
   match the bead store. v1 default?
8. **Agent Thoughts in v1**: synthetic-per-agent (recommended), or implement individual-thought
   nodes upfront?
9. **Cross-workspace beads**: a bead lives in one repo's `sdd/beads/`, but `bead/workspace.py`
   scans sibling workspaces. Should the artifact graph union all of them, or scope to the active
   repo?
10. **Provider matrix for `/sase_artifact`**: same as `/sase_agents_status` (all runtimes), or
    different?

---

## References

- Prior research: [`sdd/research/202604/artifacts_panel.md`](../202604/artifacts_panel.md) — TUI
  surface, file/thinking/log-modal obsolescence, current artifact discovery layers.
- Identity: `src/sase/ace/tui/models/agent.py:406-408` (Agent.identity tuple).
- Beads: `src/sase/bead/ids.py:45-83`, `src/sase/bead/model.py:9-51`,
  `src/sase/bead/work.py:24-51`, `src/sase/bead/workspace.py:158-191`.
- Rust core layout: `../sase-core/crates/sase_core/src/{parser.rs,agent_scan/,bead/,notifications/,
  git_query/,status/,query/}`.
- Python facades: `src/sase/core/{parser_facade,agent_scan_facade,bead_read_facade,
  notification_store_facade,query_facade,graph_index_facade}.py`,
  `src/sase/core/wire_conversion.py`, `src/sase/core/rust.py`.
- Existing graph-shaped code: `src/sase/xprompt/graph.py` (Mermaid),
  `src/sase/ace/tui/models/changespec_graph_index.py` (in-memory index).
- Skill/CLI blueprint: `src/sase/xprompts/skills/sase_agents_status.md`,
  `src/sase/agents/cli_status.py`, `src/sase/main/parser_agents.py`,
  `src/sase/main/init_skills_handler.py`.
- Agent → artifact derivations: `src/sase/ace/tui/models/agent_artifacts.py`,
  `src/sase/ace/tui/models/_loaders/_meta_enrichment.py:79`,
  `src/sase/ace/tui/models/_loaders/_done_loaders.py:127-141`,
  `src/sase/ace/tui/models/_loaders/_agent_status_overrides.py:218-228`.
