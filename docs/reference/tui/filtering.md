---
title: Filtering
description: Query filtering on the Agents, Patches, Commits, Beads, and Plans TUI panes.
---

# Filtering

This page lists how the sase TUI filters Agents, Patches, Commits, Beads, and Plans.

## Filtering Agent, Patches, Commits, Beads, and Plans

Patches keeps its canonical query visible in a persistent, read-only filter row at the
top of the detail column, so the active query is legible without opening anything. Press
`/` (or the local `f`) to start editing it. Typing re-filters the already-loaded Patch
snapshot on every keystroke, so previews are instant and never re-query the store.
`Enter` commits: it reloads Patches from the committed query, pushes the query you
replaced onto the `^` history stack, and returns focus to the list. `Escape` abandons
the edit, restoring the committed query, its result, and the row you had selected. A
parse error stays inline in the row and leaves the visible Patch list on the last valid
query. `Tab` accepts completions for keys, values, shorthand sigils, state predicates,
status shorthands, and — while the row is empty — saved-slot commands. Saved-query
commands such as `#3 status:Draft`, `# status:Ready`, and `#3` save, allocate, or delete
a slot without changing the active query or closing the editor.

Commits keeps its effective canonical query visible above the timeline. Press `/` or the
local `f` shortcut to focus that row for live editing; `Enter` commits the query and
returns focus to the timeline, while `Escape` restores the last committed query and
result. The row remains visible in either case. Beads, Plans, Files, and every document
provider pane keep the same persistent idle row, so the committed query stays visible
without opening an editor. The Beads default is `-status:closed limit:<page_size>`; that
query lives in the idle bar, not on the counts line. Tokens from different facets
combine with AND semantics; comma-separated and repeated values within one facet combine
with OR semantics. Free-text terms must all match. Press `Tab` to accept the highlighted
key or value completion.

Agent uses the same persistent query row and the Boolean profile dialect shared with
[`sase agent search`](../cli/agent.md#sase-agent-search). It accepts `AND`, `OR`,
`NOT`, and parentheses, plus free text over agent names and metadata. Its fields cover
identity and lineage (`name`, `kind`, `session`, `clan`, `tribe`, `role`, `workflow`,
`parent`, `project`), execution (`state`, `status`, `provider`, `model`, `attempt`),
lifecycle booleans (`hidden`, `dismissed`, `revivable`, `attention`, `retry`), archive
links (`linked`, `relation`, `artifact`), start/finish bounds (`since`, `until`,
`after`, `before`), and runtime bounds (`min`, `max`). Date bounds accept `Nh` / `Nd` /
`Nw` / `Nm`, `today`, and `YYYY-MM-DD`, where `Nm` means months; runtime bounds accept
seconds or `Ns` / `Nm` / `Nh` / `Nd`, where `Nm` means minutes. There are no sigils or
macros. For example, `state:dismissed AND revivable:true`,
`provider:codex AND status:FAILED AND since:7d`, and `linked:true AND relation:read` are
valid queries.

The top-level Agents tab uses the same Boolean grammar through the live `agents-live`
profile, but keeps zero idle screen-space cost: when no query is active, no filter row
is visible; when a query is active, the detail column shows the canonical highlighted
query and match count. Press `/` or `f` to open the auto-hiding filter bar. Live Agent
fields include the shared identity and runtime fields (`name`, `session`, `clan`,
`project`, `kind`, `role`, `workflow`, `model`, `provider`, `status`, `attempt`,
`hidden`, `attention`, `retry`, `since`, `until`, `after`, `before`, `min`, `max`,
`text`) plus operational fields (`cl`, `machine`, `tribe`, `pinned`, `unread`, `needs`,
`source`). Archive-only catalog fields such as `state`, `dismissed`, `revivable`,
`linked`, `relation`, `artifact`, and `label` are not live-tab filters, and the live tab
does not accept an Artifacts `limit:` token.

The Agent catalog also derives three archive capabilities that describe what a dismissed
row's persisted archive can actually support, rather than whether a bundle file merely
exists:

| Field                   | True when                                                                 |
| ----------------------- | ------------------------------------------------------------------------- |
| `historically_viewable` | The archive holds enough data to inspect the run after the fact.          |
| `durably_revivable`     | The archive holds enough data to restore the run.                         |
| `restartable`           | The archive holds the prompt and model parameters needed to run it again. |

The query schema currently advertises those three field names, but the Agent query index
does not populate their values. Consequently, both `historically_viewable:true` and
`historically_viewable:false` (and the equivalent queries for the other two fields)
return no rows. Inspect the Archive Record Lifecycle card for these per-row
capabilities; use `revivable:true` when the goal is to find rows sase's TUI can restore.

`revivable:true` now means all of "dismissed", "backed by a readable top-level bundle",
and `durably_revivable`, so the saved query the `w` action seeds
(`state:dismissed AND revivable:true`) no longer lists rows whose archive cannot
actually be restored. The Archive Record Lifecycle card shows **Viewable**,
**Restorable**, and **Restartable** lines, plus a **Missing** line naming any unmet
requirement, and Archive restore of a row that lacks one is refused up front with
`This archive record is not revivable: missing …` instead of failing at the last step.

Stitches accepts singular `project:` plus `repo:`, `author:`, `origin:`, `type:`,
`sha:`, `since:`, `until:`, `sidecar:`, `merges:`, and `limit:` and free text matched
against the commit subject. `sha:` is the pane's identity field: it is repeatable,
comma-listable, and negatable, and it matches a **prefix** of the full commit id, so
`sha:a1b2c3` selects that commit the way a git short SHA does. `origin:` accepts
`stitch`, `auto`, and `manual`, and is repeatable, comma-listable, and negatable like
`repo:` and `author:`. `type:` is also repeatable, comma-listable, and negatable; it
accepts `manual`, `automatic` (`auto` alias), `stitch`, `merge`, `patch`, and observed
`SASE_TYPE` footer values. `merges:hide/show/only` controls merge-commit visibility
exactly like `sase stitch list`'s `--merges` flag (see
[VCS Provider Reference](../vcs/providers.md#sase-stitch-list)). `project:` is
not repeatable, comma-listable, or negatable because it selects the repository
constellation before commits are collected. With no `project:` token, collection spans
all projects. It accepts a configured project name, ProjectSpec directory key, or alias;
committed known values are rewritten to the configured project name. On first open, when
`ace.current_project.seed_filters` is on, the shared Artifacts project scope seeds from
the [current project](projects-tab.md#current-project) unless an explicit `project:` / `+name` term
already selected one. The project picker replaces that token while preserving every
other committed token; its **All projects** choice removes it. The compatibility `a`
action removes an active project token and restores the last automatic or picked project
on the next press.

The bundled initial query is `sidecar:false merges:hide since:24h`; sase's TUI injects
`limit:<ace.page_size>` (default `limit:100`) when that string has no `limit:` token. It
is configurable with `ace.artifacts.stitches.default_query`
(`ace.artifacts.commits.default_query` is a deprecated alias), and changes take effect
the next time sase's TUI starts. An explicit `project:` in sase's TUI query or in the
configured default query wins over the current-project seed. An empty parsed query
includes sidecar repositories; at sase's TUI startup the async Artifacts seed can add a
visible project token. Canonical rendering always includes either `sidecar:true` or
`sidecar:false`, and the configured `d` action rewrites that same visible token.
Selecting a sidecar with `repo:` therefore requires `sidecar:true`. For example,
`project:sase repo:sase author:Ada origin:stitch since:7d sidecar:false fix` shows
recent tracked SASE commits by Ada whose subjects contain `fix`,
`repo:plans sidecar:true` shows that sidecar across all projects, and `limit:40` caps a
deliberately broad search. Day-granular `until:` values (`today`, `yesterday`, and
`YYYY-MM-DD`) include the full named day; relative and minute-precise values remain
instant bounds. Relative windows such as `since:24h` re-anchor whenever the pane
refreshes.

The repository legend starts with `[P/N]`, where `P` is the selected commit's one-based
position and `N` is the number of matched entries currently displayed. Day headings do
not count as entries. A `+` on the denominator, as in `[1/40+]`, means the displayed
total is only a lower bound. The persistent filter row reports the corresponding
coverage state (`exact`, `preview`, or `capped`) without repeating the match count. Each
timeline row also has a fixed origin glyph immediately before the subject: `✦ stitch`
for commits created through `sase stitch create`, `↻ auto` for other SASE-created
commits, and `✎ manual` when the commit has no SASE provenance footer. The legend lists
only the origins present in the displayed commits, so a result containing only tracked
work shows only `✦ stitch`.

Every Artifacts pane accepts a host-owned `limit:N` token that caps how many matched
rows the list shows. It is not a row property: sase's TUI extracts it before dialect
parse / Rust eval, matches against the remainder, then slices. Startup writes
`limit:<ace.page_size>` into each pane's default query when no `limit:` is present; a
user-authored `limit:40` or `limit:all` is left alone, and deleting the token leaves
that pane uncapped. `Ctrl+J` raises the cap by `ace.page_size` and `Ctrl+K` lowers it,
never dropping below one page; unload of an unlimited query (`limit:all` or a deleted
token) introduces `limit:<ace.page_size>`. When the cap clips the result, the filter row
says `capped` and Stitches uses a lower-bound total such as `[1/40+]`. `limit:all` is
the unlimited synonym on every pane; `limit:0` is also accepted by the shared parser
(Stitches used that spelling first). Canonical query text omits both. Provider or
aggregate truncation metadata can still mark a count as capped without inventing an
active query limit.

Plans accepts `kind:`, `status:`, `tier:`, `project:`, `path:`, `since:`, `until:`, and
`limit:` plus free text matched across plan-document metadata and content. `path:` is
the pane's identity field — the document path or provider identity, matched by substring
so `path:<fragment>` finds a document by any part of its path, and still searched by
free text — and every other document-provider pane gains the same substring `path:` key
when its declaration does not already define one. `kind:` accepts `proposal`, `active`,
`archive`, and the document-sidecar roles present in the current scope, such as `plans`,
`research`, or `designs`. `kind:archive` matches committed documents that are not linked
from a live bead, while `kind:designs` narrows documents to that sidecar.

Beads accepts repeatable `id:`, `type:`, `task_type:`, `tier:`, `status:`, `size:`,
`due:`, `project:`, `assignee:`, `owner:`, `model:`, `has:`, `bug:`, `label:`, `since:`,
and `until:` terms, plus host-owned `limit:`. `id:` is the pane's identity field: it
matches a bead id exactly, and bead ids remain free-text searchable as well, so
`id:sase-w3.2` pins one row while a bare `sase-w3` still matches by substring.
`task_type:` accepts catalog slugs plus `untyped` for legacy beads. Status values
include the five stored states plus the derived `blocked`, `launched`, and `triage`
states. `due:` accepts `live`, `soon`, or `due` and matches
[flag beads](../work-units/bead-lifecycles.md#flag-bead-lifecycle) — the
dedicated feature-flag removal tasks — by how close they are to their removal
thresholds. Other bead types have no due state, so a positive `due:` term hides them.
`has:` accepts `+1`, `reopened`, `plan`, `bug`, `deps`, `notes`, and `triage`. `bug:`
matches issue state, reference, relation, or project, with completion for `none`,
`open`, `closed`, `stale`, `drift`, `mirrored`, and `referenced`; `label:` matches
cached provider labels. Free text also searches cached external issue title, body, URL,
and labels alongside the bead id, title, description, notes, design, references, and
ownership metadata.

A leading unquoted `-` excludes a match. Stitches can exclude repositories, authors,
origins, types, commit SHAs, and subject text. Plans can exclude `kind:`, `status:`,
`tier:`, `project:`, `path:`, and free text. Files and Beads can exclude every declared
filter facet and free text, including `since:` and `until:`. Exclusion wins when
positive and negative constraints overlap: `repo:sase,plans -repo:plans`,
`author:Ada -author:bot`, and `status:open -status:blocked` are all valid. A comma list
negates the whole token, so `-repo:plans,research` excludes either repository. Stitches
and Plans do not allow negated date bounds; Files does, but permits each date key only
once. Beads permits repeated and negated date bounds. `limit:` cannot be negated in any
pane. Stitches' `project:`, `sidecar:`, and `merges:` fields are singular and cannot be
negated; `sidecar:` accepts only `true` or `false`, and canonical queries always render
its explicit value. Quote the whole token to search for a literal leading minus
(`"-repo:plans"`); quote only the excluded value to keep negation active
(`-"generated rollout"`). Matching remains case-insensitive, and repository/project
aliases work for both inclusion and exclusion.

In the flat-token query grammar, a declared Boolean field also takes a bare shorthand:
an unquoted `key` token with no colon expands to `key:true`, and `-key` to `-key:true`.
Quoting opts out, so `"key"` stays free text. Because the shorthand is purely lexical
(it always canonicalizes to the long spelling), it costs no schema field and moves no
compiled profile's digest, so no saved query is invalidated. Stitches' `sidecar` field
is Boolean, so a bare `sidecar` filters to `sidecar:true` instead of searching for the
literal word in a commit subject; quote it (`"sidecar"`) to search for the word.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Tabs and panes](tabs-and-panes.md) — tab system and Artifacts panes.
- [Query system](query-system.md) — editing, saving, and recalling queries.
