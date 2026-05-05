# Artifact Graph Navigation UI Research

Date: 2026-05-05

## Question

How should SASE improve navigation through the unified artifact graph in the ACE artifact panel?

The current panel is already a useful detail browser: `A` opens a Textual modal at `/`, a ChangeSpec, or an agent;
the left pane lists path, children, outbound links, and inbound links; the right pane renders a kind-specific preview;
and the modal supports local filtering, back/forward, parent/root, copy ID, edit file, and explicit graph
preview/export.

The weakness is not graph storage. It is orientation. A user landing on an agent, ChangeSpec, bead, or file can see
neighbors, but the panel does not yet help them answer the common navigation questions:

- Where am I in the ownership tree?
- Why is this artifact connected to this other one?
- Which relationship type should I follow next?
- What is the shortest useful route from a high-level object to the concrete file, plan, question, thought, or agent I
  care about?
- Which links are primary workflow structure versus incidental related material?

## Local Product Constraints

The artifact graph contract is intentionally small:

- Node kinds: `root`, `file`, `directory`, `project`, `changespec`, `commit`, `bead`, `agent`, `thought`, `unknown`.
- Link kinds: `parent`, `created`, `worker`, `related`.
- `parent` is directed child -> parent, so reverse parent edges are tree children.
- TUI entry points are context-specific: AXE -> `/`, CLs -> current ChangeSpec, Agents -> current agent.
- Normal row movement must not query or rebuild the graph. Expensive graph materialization is explicit.
- The UI is terminal-first and keyboard-first. Dense lists, predictable focus, and bounded queries matter more than a
  freeform canvas.

Relevant local files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_state.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/`
- `src/sase/core/artifact_wire/models.py`
- `sdd/legends/202605/unified_artifacts.md`

## Prior Art

### Obsidian Graph View

Obsidian has both a global graph and a local graph. The local graph is the more relevant pattern: it centers the active
note and lets users tune depth, while the global graph stays useful for overview and discovery. Obsidian also exposes
filters, toggles for attachments/orphans/tags, groups with colors, link direction arrows, and force-layout controls.

Takeaway for SASE: local neighborhood views are more useful than whole-graph views for day-to-day navigation, but users
need aggressive filters and grouping or the graph becomes decorative noise. SASE should borrow the local-depth idea, not
the force-directed canvas as the primary UI.

Source: https://obsidian.md/help/plugins/graph

### Neo4j Bloom

Bloom is useful prior art because it is designed for large typed property graphs, not only note networks. Its key idea is
a "Perspective": a scoped business view that decides which categories and relationship types are visible, how they are
styled, and which search phrases/actions are exposed. Bloom is also search-first: the search bar suggests graph pattern
queries, saved search phrases, full-text search, and UI actions. The scene then supports expansion, dismissal, fit to
selection, and refresh actions.

Takeaway for SASE: typed relationship lenses should be first-class. A graph UI should not show all relationship types
with equal weight. SASE can implement this cheaply as relation-mode filters and task-oriented row groups: `Tree`,
`Created`, `Worker`, `Related`, and `All`, plus saved "question templates" later.

Sources:

- https://neo4j.com/docs/bloom-user-guide/current/bloom-perspectives/perspective-creation/
- https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/search-bar/

### IDE Call Hierarchy

JetBrains and Visual Studio both use tree panes for graph-shaped code relationships. They avoid drawing a general graph
for the primary workflow. Instead, they let the user choose a direction, expand levels, add a selected node as a new
root, and keep source/details synchronized with the selected tree row. Visual Studio also has an explicit scope control
such as solution/project/document.

Takeaway for SASE: for operational debugging, a tree projection with direction toggles is often better than a canvas.
SASE already has typed links; it can show `inbound` and `outbound` as caller/callee-style directions and let the user
re-root on any selected artifact.

Sources:

- https://www.jetbrains.com/help/idea/viewing-structure-and-hierarchy-of-the-source-code.html
- https://learn.microsoft.com/en-us/visualstudio/ide/call-hierarchy?view=vs-2022

### Datadog Service Map

Datadog's Service Map is a graph overview for microservice dependencies. The useful ideas are not the picture itself,
but the controls around it: grouping by team/application, facet filtering, fuzzy matching, incident/status filtering,
time scoping, and collapsing intermediate nodes when filters hide the middle of a path.

Takeaway for SASE: large graphs need domain facets and scope controls. SASE equivalents are artifact kind, link type,
source kind, provenance, diagnostics, and maybe workflow recency. The "collapsed intermediary" idea is valuable for
showing route summaries without flooding the left pane.

Source: https://docs.datadoghq.com/tracing/services/services_map/

### GitHub Network Graph And Forks List

GitHub's repository network graph is specialized: it visualizes branch history across forks and is bounded to recent
branches. It also pairs the graph with a list view for forks that can be filtered and sorted by useful operational
properties.

Takeaway for SASE: visual graph views work best when the layout matches one strong domain axis, such as time. For
SASE, a generic artifact graph canvas would not have one dominant axis, but a timeline/route view for agent runs,
questions, retries, and commits could be valuable.

Source: https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/understanding-connections-between-repositories

### TheBrain

TheBrain is long-running prior art for personal knowledge graphs. Its strongest relevant claim is scale: it is built
around associative mapping and advertises support for very large item counts. Its UI pattern is a constantly re-centered
local neighborhood rather than an exhaustive all-node display.

Takeaway for SASE: re-centering on the current artifact is the right default. Users should feel like they are walking
the graph one useful neighborhood at a time.

Source: https://www.thebrain.com/products/thebrain/

## Patterns Worth Copying

1. **Local-first neighborhood.** Start from the current artifact and show one or two bounded hops. Full graph export
   remains explicit.
2. **Relationship lenses.** Let users decide whether they are following ownership, production, work assignment, or loose
   related links.
3. **Direction toggles.** Inbound/outbound should be a visible mode, not only row group names.
4. **Re-rooting.** Opening a row should make it the new center. "Add as root" from IDE call hierarchy maps to SASE's
   existing `enter`.
5. **Search-first fallback.** When the current neighborhood is wrong, users should be able to search the graph by ID,
   kind, title, path, source, or text, then jump to a result.
6. **Facet filtering.** Kind, link type, provenance, diagnostics, and source kind should be lightweight controls.
7. **Route summaries.** For multi-hop navigation, display collapsed paths such as `ChangeSpec -> Agent -> file` rather
   than forcing users to step through every intermediate node blindly.
8. **Detail synchronization.** Highlighting a row should update low-cost context, while opening a row performs the
   narrow detail load. This matches the existing performance contract.

## Patterns To Avoid

1. **A force-directed canvas as the default.** It is hard to make keyboard-first, hard to test in Textual, and often
   becomes a screenshot feature rather than a navigation tool.
2. **Showing all links equally.** `parent`, `created`, `worker`, and `related` answer different questions. Flattening
   them makes the graph feel arbitrary.
3. **Global graph on open.** The artifact graph may contain historical projects, dismissed agents, archive ChangeSpecs,
   thoughts, files, and directories. Opening that whole graph would break orientation and performance.
4. **Filtering only by substring.** The current local text filter is useful but insufficient for graph navigation.
   Users need semantic filters.
5. **Replacing detail preview with graph preview.** The current `g/G` actions overwrite the detail pane. That is fine as
   an explicit export preview, but it should not become the main browse state.

## Alternative Solutions

### Option 1: Improve The Existing List/Detail Modal

Keep the current two-pane layout and add richer organization:

- Header shows current artifact kind, ID, breadcrumb path, and relation counts.
- Left pane gets relation lenses: `Tree`, `Created`, `Worker`, `Related`, `Inbound`, `Outbound`, `All`.
- Groups show counts and can be folded.
- Rows get better labels: kind icon/short code, title, relationship reason, source/provenance badge, and diagnostic
  marker.
- Local filter becomes facet-aware: `/ kind:file link:created text:plan`.
- Add search/jump action that calls `artifact_list` with bounded query options and re-roots on selected result.

Pros:

- Best fit for Textual and current tests.
- Preserves keyboard ergonomics.
- Minimal backend change if `artifact_show` already returns enough direct neighbors.
- Easy to ship incrementally.

Cons:

- Still requires stepping node by node for multi-hop questions.
- Does not give users an overview of routes unless route summaries are added.

### Option 2: Add A Local Mini-Graph View

Add a third mode or right-pane preview that renders a bounded local graph around the current artifact, probably as
Mermaid/DOT text or a simple ASCII adjacency view:

```text
changespec sase-23
  parent -> project ~/.sase/projects/sase/sase.gp
  related <- agent phase-5-review
  parent <- commit sase-23:4
  related <- bead sase-23.5
```

Pros:

- Gives users a fast mental model of the neighborhood.
- Can reuse `artifact_graph(root_id=current, max_depth=1|2, limit=...)`.
- Works in terminal without implementing a canvas.

Cons:

- Text diagrams are worse than lists for precise selection.
- If it becomes interactive, it duplicates the left-pane navigation model.
- Mermaid/DOT export is more useful outside the TUI than inside it.

### Option 3: Search-First Graph Navigator

Make graph search the primary interaction. The panel opens with a command/search input, supports query phrases like
`agents for <changespec>`, `files created by <agent>`, `beads related to <changespec>`, and shows results as rows.

Pros:

- Directly answers task questions.
- Scales better than browsing when the graph is large.
- Aligns with Neo4j Bloom's search-first model.

Cons:

- Requires query grammar, suggestions, and likely new facade helpers.
- Higher implementation risk.
- Less discoverable for users who do not know what to search for.

### Option 4: Workflow Route Views

Add curated route views for SASE's main workflows:

- ChangeSpec route: ChangeSpec -> commits -> agents -> created files/questions/plans/thoughts.
- Agent route: parent/follow-up/retry chain -> created artifacts -> related ChangeSpecs/beads.
- Bead route: epic/phase tree -> worker agents -> outputs.
- File route: directory path -> creating agent -> related ChangeSpec/bead.

Pros:

- Strong task fit.
- Lets the UI name relationships in SASE language instead of generic graph language.
- Avoids showing irrelevant graph structure.

Cons:

- More product design per artifact kind.
- Easy to over-specialize and drift from the simple graph contract.
- Needs careful tests to avoid hiding valid but uncommon links.

### Option 5: Full Canvas Graph

Build an interactive graph visualization with pan/zoom/select, likely outside pure Textual or as a separate web view.

Pros:

- Best visual overview.
- Useful for demos, docs, and occasional map-making.

Cons:

- Weak terminal fit.
- High implementation and test cost.
- Hard to keep accessible and keyboard-first.
- Likely to underperform on large historical graphs unless heavily filtered.

## Recommended Approach

Use **Option 1 as the primary path**, plus a small part of **Option 4**. Do not make a canvas graph the default.

The right model for SASE is a **relationship-lens navigator**: a dense, keyboard-first, re-rooting artifact browser that
keeps the current artifact centered, uses typed links to organize the left pane, and adds curated route summaries for
the highest-value SASE workflows.

### Recommended V1 Changes

1. **Add a compact orientation header.**
   Show current kind/title/ID, breadcrumb path, and counts for `children`, `created`, `worker`, `related`, inbound, and
   diagnostics. This gives users confidence before they move.

2. **Replace static row groups with lenses.**
   Add a mode selector over the left pane:

   ```text
   Lens: Tree | Created | Worker | Related | Inbound | Outbound | All
   ```

   Each lens controls which rows are visible and how they are labeled. `All` can preserve today's full grouped view.

3. **Make row labels explain the relationship.**
   Today labels often expose IDs more than meaning. Prefer:

   ```text
   created file      plan.md                    /abs/path/plan.md
   related agent     coder for sase-23.5        agent:sase:...
   worker bead       sase-23.5.2                phase worker
   parent project    sase.gp                    ~/.sase/projects/...
   ```

4. **Add facet-aware filtering.**
   Keep substring filtering, but parse simple tokens:

   - `kind:file`
   - `link:created`
   - `dir:sdd`
   - `source:agent_artifact`
   - `diag:error`
   - quoted/free text for title/path/search text

   This can start as local filtering over the already-loaded detail rows.

5. **Add graph search as a jump action, not the default.**
   A separate action such as `s` can open a search input backed by `artifact_list`. Selecting a result re-roots the
   modal. This covers "I know roughly what I want" without replacing neighborhood browsing.

6. **Add curated route sections in detail renderers.**
   For common artifact kinds, show route summaries before raw link counts:

   - ChangeSpec: related agents, commits, beads, created plans/questions/diffs.
   - Agent: parent/retry/follow-up chain, related ChangeSpecs/beads, created files/thoughts.
   - Bead: parent/children/dependencies/workers.
   - File: owning directory, creating agent, related ChangeSpec/bead if known.

7. **Keep graph preview/export explicit.**
   `g/G` should remain bounded export/preview actions. Improve the preview to include relation counts and the current
   lens/depth, but do not make it the primary interaction.

### Recommended Later Work

After V1 proves useful, add a **route finder**:

```text
Route to: [artifact id/search]
```

It should return one or a few shortest typed paths from the current artifact, with link types shown between nodes. This
would directly answer "how did this file relate to this ChangeSpec?" without requiring a visual canvas.

Also consider saved lenses or named query phrases later, inspired by Bloom Perspectives:

- `outputs for this ChangeSpec`
- `agent chain`
- `bead workers`
- `diagnostics nearby`

## Implementation Notes

- Most V1 work can live in `artifact_panel_state.py` and `artifact_panel_modal.py`.
- Keep row construction pure and heavily unit-tested. The existing `build_artifact_panel_rows` function is the right
  seam for adding lenses, group folding, and facet filtering.
- Do not query Rust on highlight. Maintain the current pattern: local row movement updates selection; `enter` does the
  narrow `artifact_show`.
- If `artifact_show` lacks enough target node titles for link rows, add a bounded neighbor-summary field in the Rust
  detail response rather than making the TUI perform N extra `show` calls.
- Favor stable textual controls over new visual widgets. This panel will be used inside a terminal while someone is
  debugging real SASE state.

## Bottom Line

SASE should treat the artifact graph like an IDE hierarchy and workflow investigator, not like a general-purpose graph
visualization product. The best next step is to enrich the existing artifact panel into a relationship-lens navigator:
local-first, typed, searchable, re-rootable, and explicit about why each neighbor matters.
