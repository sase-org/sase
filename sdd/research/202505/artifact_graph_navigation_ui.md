# CHATGPT DEEP RESEARCH

## Context from the current Sase implementation

Sase’s artifact graph is not just a file tree. The plan describes a unified graph over project specs, ChangeSpecs,
commits, directories, beads, agents, agent-created files, questions, plans, diffs, transcripts, thoughts, and related
workflow outputs, with directed typed edges such as `parent`, `created`, `worker`, and `related`.

The current artifact panel is already a sensible **two-pane graph browser**: a left navigation list, a right detail
preview, and keybindings for open, back/forward history, parent/root, local filter, copy ID, edit file, and graph
preview/export. The left pane is built from the current node’s immediate graph neighborhood: path-to-root, children,
outbound links grouped by link type, and inbound links grouped by link type, capped at 100 selectable rows. The modal
styling confirms the product shape: a large centered modal, 34% left navigation column, and a flexible right detail
column.

The main gap is that the panel is currently **adjacency-list navigation**, not yet a strong graph-navigation experience.
The `/` filter only narrows the rows already loaded for the current artifact, link rows mostly show link type plus raw
artifact ID, and `g`/`G` produce a non-interactive preview or Mermaid export rather than an explorable local graph.

## Prior art: how other graph-navigation UIs solve this

### 1. Git commit graph UIs: graph-as-list, not graph-as-canvas

Git history tools are probably the closest precedent for a terminal-first artifact graph. GitHub’s repository network
graph presents branch history as a timeline of recent commits and branches, supports keyboard navigation, and bounds the
view to the most recently pushed branches. ([GitHub Docs][1]) GitLens/GitKraken-style commit graphs go further: they
keep a scrollable row model, show graph rails/branches beside commit metadata, add rich search, filtering, column
resizing, context menus, hidden refs, and a minimap/scroll markers for long histories. ([GitKraken Help Center][2])

**Lesson for Sase:** do not make the primary UI a force-directed graph. For keyboard-heavy workflows, a stable row model
with graph cues is often better than a canvas. Sase can borrow “graph rails” as a compact local context strip: parent
path above, current node centered, outgoing/incoming edge groups below.

### 2. Obsidian and knowledge graphs: global graph for orientation, local graph for work

Obsidian exposes both a global graph and a local graph. The graph view visualizes notes as nodes and internal links as
edges, supports hover highlighting, click-to-open, zoom/pan, filters, groups, arrows, and display/force settings; the
local graph shows notes connected to the active note and lets the user control depth. ([Obsidian Help][3])

**Lesson for Sase:** a global graph is useful for “what does my workspace look like?” but a **local graph around the
active artifact** is better for day-to-day navigation. This maps directly to Sase’s existing
`artifact_graph(root_id=current_id, depth=N, limit=...)` model.

### 3. Neo4j Bloom: search-first graph exploration

Neo4j Bloom frames graph exploration as search-first. Its search bar supports search phrases, graph patterns, full-text
search, and UI actions; it offers suggestions and lets users run graph queries from near-natural-language or
pattern-like input. It also has scene actions such as fit-to-selection, expand selection, dismiss, dismiss others,
refresh, undo, and redo. ([Graph Database & Analytics][4]) Bloom’s main workspace is a “scene” containing the graph
subset found through search or exploration, paired with overlays like a legend, search bar, and card list for
node/relationship details. ([Graph Database & Analytics][5])

**Lesson for Sase:** add a **global artifact jump/search mode** separate from the local row filter. Local filtering
answers “which visible neighbor do I want?” Global search answers “where is the artifact I’m thinking of?” Those are
different jobs.

### 4. Airflow, Dagster, and Kedro-Viz: DAG/lineage UIs use slicing, filters, details, and status

Airflow’s graph view shows the logical structure of a DAG, with task nodes, dependency edges, and run-specific task
state; its UI pairs graph views with grid, runs, tasks, events, code, and details tabs. Airflow also has asset graph
views for upstream producers and downstream consumers. ([Apache Airflow][6]) Dagster’s UI combines an asset catalog,
asset details, and global asset lineage; its lineage page supports filters and asset-selection syntax, and asset detail
pages include a lineage tab. ([Dagster Docs][7]) Kedro-Viz advertises complete pipeline visualization, scalability to
hundreds of nodes, search/filter, focus mode for modular pipeline visualization, and a rich metadata side panel. ([Kedro
Docs][8])

**Lesson for Sase:** graph UIs become usable when they are **scoped before rendered**. Sase should make depth,
direction, link type, kind, and text filters first-class, then render the small useful subgraph. Status badges also
matter: agents, beads, ChangeSpecs, commits, and diagnostics should carry visible state in the navigator.

### 5. Classic visualization guidance: overview + detail, focus + context, history

The classic information-visualization mantra is “overview first, zoom and filter, then details-on-demand.” ([InfoVis
Wiki][9]) Later HCI reviews group these approaches into overview+detail, zooming, focus+context, and cue-based
techniques. ([Microsoft][10]) Sase’s current two-pane panel is already an overview+detail UI; what it needs is better
focus+context: keep the current artifact in detail while showing enough surrounding graph structure to avoid getting
lost.

## Design alternatives

| Alternative                              | What it would look like                                                                                                                                                                                                   | Pros                                                            | Cons                                                                          | Fit for Sase                                          |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| **A. Polish the current adjacency list** | Keep current left grouped list + right detail, but improve labels, counts, collapse/expand, paging, and breadcrumbs.                                                                                                      | Low risk, TUI-native, fast, preserves current code.             | Still feels like “neighbors list,” not a graph.                               | Best first step.                                      |
| **B. Tree-first explorer**               | Use a true expandable tree for `parent` hierarchy, with separate sections for non-tree edges. Textual’s `Tree` supports expandable/selectable nodes and keyboard navigation. ([Textual Documentation][11])                | Great for directories/projects/ChangeSpecs/commits.             | Underplays `created`, `worker`, and `related` edges; Sase is not only a tree. | Good as one section, not the whole UI.                |
| **C. Data-table relationship browser**   | Replace `OptionList` with rows/columns: direction, link type, kind, title, ID, status, updated. Textual’s `DataTable` supports keyboard row/cell navigation, events, and efficient display. ([Textual Documentation][12]) | Much more scannable than raw strings; sortable/filterable.      | Less “graphy”; more implementation churn than improving `OptionList`.         | Strong if artifact nodes often have high degree.      |
| **D. Interactive local graph view**      | Press `g` to toggle a local graph around the current node: depth 1/2, inbound/outbound toggles, link-type filters, selectable nodes.                                                                                      | Best mental model for typed graph relationships.                | Hard to render well in a terminal; can become cluttered quickly.              | Useful as a secondary mode, not default.              |
| **E. External rich graph viewer**        | Keep TUI as browser; export/open Mermaid/DOT/web visualization for global overview.                                                                                                                                       | Best visual graph fidelity; uses existing export path.          | Context switch; not great for fast keyboard navigation.                       | Good for debugging/reporting, not primary navigation. |
| **F. Search-first command palette**      | Add `S` or `ctrl+p` global artifact search, query by text/kind/link type, jump to result.                                                                                                                                 | High leverage; solves “I know what I want, not where it lives.” | Needs good ranking and previews.                                              | Should be added early.                                |

## Recommended approach: a “focal graph browser”

I’d recommend **keeping the current two-pane panel as the primary interface**, but evolving it into a **focal graph
browser**: the current artifact is the focus; the left pane is a structured, filterable, keyboard-first neighborhood;
the right pane is detail plus a compact local graph context; full graph visualization remains on demand.

This fits Sase better than a default canvas because Sase’s graph is heterogeneous, potentially high-degree, and
terminal-oriented. Agents can create many files/thoughts; ChangeSpecs can connect to commits, beads, plans, questions,
transcripts, diffs, and agents; raw visual graphs will get noisy. The existing docs already emphasize bounded graph
output and treating `truncated: true` as partial, which is exactly the right design constraint for UI navigation.

### What I’d build

**1. Upgrade the left pane from “list of links” to “relationship navigator.”**

Keep the current grouped sections, but make each group navigable, collapsible, counted, and more semantic:

```text
Path
  /  ›  project.gp  ›  changespec:sase-23  ›  agent:planner-20260505

Children  14
  [file] docs/artifacts.md                         updated 2h ago
  [commit] sase-23:4                               merged
  ... show 10 more

Created → 37
  [plan] plan.md                                   agent output
  [diff] changes.patch                             412 lines
  [thought] “Need to preserve legacy index…”       09:41

Worker → 1
  [agent] planner-20260505                         done

Related ↔ 8
  [bead] sase-23.4                                 TUI panel
  [agent] coder-20260505                           retry
```

The important change is to show **display title, kind, status/subtitle, and a dim ID**, not just raw IDs. The current
`_row_label` for inbound/outbound rows mainly prints link type plus artifact ID, which is functional but low-signal.

**2. Add a persistent “where am I?” header.**

The top line should always answer:

```text
[agent] planner-20260505
Path: / › project.gp › sase-23 › planner-20260505
Edges: children 0 · created 37 · related 8 · worker 0 · inbound 3
```

The right detail renderer already appends payload, link, and diagnostic summaries, so this is mostly a
presentation/ranking problem rather than a new data model.

**3. Split local filtering and global search.**

Keep `/` for “filter visible rows.” Add `S` or `ctrl+p` for “search the whole artifact graph.” Global search should call
the existing artifact list/search path, because the CLI already supports text filters, kind filters, link-type filters,
provenance filters, root filters, and limits.

Suggested behavior:

```text
/     filter current neighborhood
S     global artifact search
L     filter by link type
K     filter by artifact kind
I/O   toggle inbound/outbound visibility
```

**4. Make `g` an interactive local map, not just a preview.**

Today `g` runs `artifact_graph` with `root_id=current_id` and `limit=100`, then renders a textual preview of root, node
count, link count, truncated state, and the first 10 nodes. I’d turn this into a transient local-graph mode:

```text
Local graph: depth=1  inbound=on  outbound=on  link_types=all  limit=100

                     [project.gp]
                          ↑ parent
[/] ← parent ← [sase-23] ← related → [sase-23.4]
                          ↓ worker
                  [agent:planner-20260505]
                          ↓ created
        [plan.md] [questions.md] [diff.patch] [+34 more]
```

Navigation should still be row-based: every visible node in the map appears in a selectable list underneath or beside
the diagram. The map is for orientation; the list is for action.

**5. Add group paging and “show more.”**

The current row cap is global: once selectable rows exceed 100, extra rows are dropped and a notice asks the user to
filter. That is safe, but for high-degree nodes it can hide useful groups. Prefer per-group caps:

```text
Created → 37
  first 15 rows...
  ... 22 more; press ] to page group, or / to filter
```

This matches the repo’s performance intent: keep Rust queries narrow, fetch selected-node detail, children pages, links
pages, and optional detail preview only.

**6. Preserve exports for full graph thinking.**

Keep `G` as Mermaid export and consider adding `O` to open/export externally later. The TUI should remain optimized for
“move through the graph”; Mermaid/DOT should be for documentation, debugging, or sharing.

## Concrete implementation sequence

**Phase 1: High-signal row model, minimal architecture change**

Extend `ArtifactPanelRow` with optional `kind`, `display_title`, `subtitle`, `edge_direction`, `edge_count`,
`diagnostic_badge`, and `truncated_count`. Keep `OptionList` for now. Render labels as cards/rows with badges. Add group
counts and collapse state to `ArtifactPanelNavigationState`.

**Phase 2: Global jump/search**

Add `action_global_search`, probably bound to `S` or `ctrl+p`. Use the existing artifact list query path with
text/kind/link filters. Results open the selected artifact through the same `_navigate_to` path, so browser history
still works. This brings Sase closer to Bloom’s search-first interaction without abandoning the current TUI. ([Graph
Database & Analytics][4])

**Phase 3: Interactive local graph mode**

Replace `_graph_preview_text` with a navigable local graph screen/pane. Start with a simple textual “hub and spokes”
layout rather than a full graph layout algorithm. Add depth and link-type toggles only after depth-1 works well.

**Phase 4: Optional Tree/DataTable experiments**

Use `Tree` for the `parent` hierarchy if users frequently traverse directories/projects/ChangeSpecs. Use `DataTable` if
high-degree agent or ChangeSpec nodes need columns, sorting, and better scanning. This can be prototyped behind a config
flag because both are larger UI shifts.

## Final recommendation

Build **a hybrid focal graph browser**:

1. **Default view:** keep the current two-pane layout.
2. **Left pane:** relationship navigator with breadcrumbs, children, inbound/outbound groups, counts, collapse, paging,
   and richer row labels.
3. **Right pane:** artifact detail plus a compact “where am I in the graph?” context strip.
4. **Search:** keep `/` local; add global artifact search/jump.
5. **Graph mode:** make `g` an interactive depth-limited local graph; keep `G` for Mermaid export.
6. **Non-goal:** do not make a full force-directed graph the default TUI navigation surface.

This approach preserves what Sase already does well—fast bounded detail browsing, keyboard navigation, history,
parent/root jumps, and file editing—while adding the missing graph-navigation affordances: context, search, slicing, and
a local map.

[1]:
  https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/understanding-connections-between-repositories?utm_source=chatgpt.com
  "Understanding connections between repositories - GitHub Docs"
[2]: https://help.gitkraken.com/gitlens/gl-commit-graph/?utm_source=chatgpt.com "GitLens Commit Graph"
[3]: https://help.obsidian.md/plugins/graph?utm_source=chatgpt.com "Graph view - Obsidian Help"
[4]: https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/search-bar/ "Search bar - Neo4j Bloom"
[5]: https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-overview/ "Overview - Neo4j Bloom"
[6]:
  https://airflow.apache.org/docs/apache-airflow/stable/ui.html?utm_source=chatgpt.com
  "UI Overview — Airflow 3.2.0 Documentation"
[7]: https://master.dagster.dagster-docs.io/concepts/webserver/ui "Dagster UI | Dagster"
[8]:
  https://docs.kedro.org/projects/kedro-viz/en/v11.0.2/?utm_source=chatgpt.com
  "Welcome to Kedro-Viz documentation! — kedro-viz 11.0.2 documentation"
[9]:
  https://infovis-wiki.net/wiki/Visual_Information-Seeking_Mantra?utm_source=chatgpt.com
  "Visual Information-Seeking Mantra - InfoVis:Wiki"
[10]:
  https://www.microsoft.com/en-us/research/publication/a-review-of-overviewdetail-zooming-and-focuscontext-interfaces/
  "A Review of Overview+Detail, Zooming, and Focus+Context Interfaces - Microsoft Research"
[11]: https://textual.textualize.io/widgets/tree/?utm_source=chatgpt.com "Tree - Textual"
[12]: https://textual.textualize.io/widgets/data_table/?utm_source=chatgpt.com "DataTable - Textual"
