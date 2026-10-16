---
title: Agent tribes
description: Look up how agents are grouped into persistent tribes.
---

# Agent tribes

This page describes tribe membership, panels, and navigation behavior.

<a id="agent-tribes-1"></a>

## Agent Tribes

An agent tribe is a user-facing label for related agents across clans and sessions.
Assign one at launch with the `tribe=` keyword on `%id`, or use `#tribe` when the agent
should be auto-named:

```text
%id(api-review, tribe=review) Review the API boundary.
---
#tribe:review Review another boundary with an automatic id.
```

sase's TUI displays tribes with an `@` prefix and splits the Agents tab into panels such
as `@review` and `@epic`. The clan's single declaration assigns one effective tribe to
the whole generation; joiner prompts omit `tribe=`. Older clan generations without any
`clan_tribe` value fall back to the distinct post-hoc member tribe assignments they
carry.

Press `N` in sase's TUI to set or clear the focused agent's tribe (or every marked
agent). On a clan row or any clan member, the modal targets `clan <name>` and sets the
whole clan generation's recorded tribe (see
[Launch-time clan summaries](agent-clans.md#launch-time-clan-summaries)). When the
focused or marked agent is the declaring clan member itself, sase's TUI also rewrites
its stored `%clan(<clan>, tribe=<tribe>)` and its `clan_tribe` metadata. For a joiner,
sase's TUI updates only the metadata and never invents a second `%clan` declaration.
Pressing `N` on the clan row itself writes only the clan record and leaves member
prompts alone. The CLI manages the per-agent assignment store for any named agent:

```bash
sase agent tribe set -n <agent> -t <tribe>
sase agent tribe unset -n <agent>
sase agent tribe list [-n <agent>]
```

Pass a bare tribe name to `set`, without the display-only `@` prefix. Names may contain
letters, digits, underscores, dots, and dashes. `set` exits with status `2` for an
invalid name, an unknown agent, or the reserved name `default`. The CLI updates only the
assignment store; it does not rewrite the agent's prompt or metadata. Per-agent
assignments are stored canonically in `~/.sase/agent_tribes.json` with a `tribe` field.
If that file does not exist, SASE reads the legacy `~/.sase/agent_tags.json` scalar
`tag` and list `tags` shapes. The first mutation writes all imported assignments to the
canonical store, which is authoritative from then on. Existing artifacts and saved
bundles can still be read when they use the legacy `tag` field, but rewritten metadata,
new bundles, CLI output, and editor projections use `tribe`. Clan-wide assignments use
the separate per-member `clan_tribe` metadata and are resolved across the generation.
For sase's TUI panel grouping, that explicit clan assignment takes precedence over
per-agent assignments.

sase's TUI derives the reserved `@default` panel for agents whose outer presentation
root has no effective tribe. This fallback is display-only: SASE does not write
`default` into agent metadata or the assignment store. An agent that nonetheless carries
a stored `default` tribe joins the same panel, and clearing any user-managed tribe
returns the agent there. Because the panel never resolves to a real entity,
`%wait:@default` and `#fork:@default` are rejected at launch.

### Moving agents between tabs

Press `N` in sase's TUI to open the Tribe & Tab modal: the second input moves the
focused agent (or every marked agent) to a named tab with tab completion, leaving the
tribe untouched when its input is empty. Typing `main` (or pressing `Ctrl+T`) moves back
to the default tab. The move is optimistic with rollback, shows a
`Moved 2 agents to blog` toast, and remote rows are skipped with the reason "tab moves
run on the owning machine". The same move is available from the CLI, which rewrites the
whole presentation root (session, clan generation, or workflow) and its stored `%tab`
directive:

```bash
sase agent tab set -n <agent> -t <tab>
sase agent tab unset -n <agent>
sase agent tab list [-n <agent>] [-j/--json]
```

A move writes `agent_tab` with `agent_tab_source: moved` to the root's metadata. `set`
exits with status `2` for an unknown agent or an invalid tab name (reserved
`local`/`all` are rejected with guidance, and `main` is redirected to `unset`).

### The built-in job tribe

Agents launched by [AXE jobs](../automation/scheduler.md) belong to the built-in `@job`
tribe, whose panel starts collapsed so routine background work stays quiet. For
compatibility, SASE stores that tribe under its historical name `chop`. Assigning `job`
through `%id(tribe=job)`, `#tribe:job`, `%clan(<clan>, tribe=job)`, the `N` modal, or
`sase agent tribe set -t job` persists `chop`, and `@job` in `%wait` or `#fork` targets
the same agents. A few surfaces show the stored name instead of the public one:
`sase agent tribe list` prints `chop`, and prompt completion and the panel's `W`/`F`
keys insert `@chop`, which targets the same tribe.

Two exceptions apply. If existing agent or clan records already use a literal `job`
tribe, `job` refers to that literal tribe instead of the built-in one. If your
configuration defines both `ace.tribes.chop` and `ace.tribes.job` with different
settings, assigning `job` fails with an error that names both keys, and nothing is
written.

### Tribe panel focus and folding

In the split layout, a tribe panel is also a selectable container. Repeated lowercase
`h` follows the validated workflow → session → clan → tribe ladder and selects the whole
expanded panel after the structural parent chain is exhausted; `h` on the selected panel
collapses it when another panel remains visible. Press `l` to expand a collapsed panel
while keeping container focus, then `l` again to return to the row sase's TUI remembered
for that panel. Uppercase `L` instead hints every visible agent-node, clan, and banner
fold in the focused tribe so one key toggles one fold; on a collapsed panel it warns
instead of expanding. Lowercase `h` on a collapsed panel selects the visually
bottom-most expanded panel without changing panel folds; `Ctrl+O` returns to the
collapsed origin. If every live panel is collapsed, `h` retains the existing
already-collapsed warning. While an expanded whole panel is selected, `j` / `k` cycle
across every panel, including collapsed ones, without descending, and `l` or `Esc`
returns to the remembered row. `J` / `K` skip collapsed panels and move to the first /
last selectable row of the next / previous expanded panel; they do nothing when no other
panel is expanded. Whole-panel focus is unavailable in the merged layout. Apostrophe
jump can select any split-panel title, including a lone expanded panel, but a lone panel
cannot be collapsed. Press `Z` with a whole tribe panel selected to zoom that tribe's
metadata document. Press `=` to isolate the focused panel by keeping it expanded and
collapsing every sibling without changing its remembered row. `=` works from whole-panel
focus and from a row selection inside a panel alike; from a row, it isolates the panel
that holds the cursor without changing the selected row. When isolation changes the
layout, sase's TUI remembers the prior collapsed-panel set for the session: `↺` title
markers and the `= restore panels` footer hint show that the next `=` will restore it. A
separate sibling-panel or layout mutation invalidates that one-step restore.

Press `-` to sweep every open agent node and clan — never a grouping banner such as
`Done` or `Running` — in the focused panel closed in one press. It resolves scope the
same way `=` does — from whole-panel focus, from a row or banner selection inside a
panel, and in merged layout, where it treats the merged roster as one scope — and it
never collapses the panel itself. When the focused panel has nothing left to collapse,
`-` reverses itself and re-expands exactly the folds its own last sweep in that panel
closed, restoring each structural fold to the level it held before. The restore is
filtered at press time to folds still live in that panel and still collapsed, so it
tolerates folds re-expanded by hand and never resurrects a fold that no longer exists.
Each panel remembers at most one sweep; a fresh sweep replaces that panel's record.
Armed panels mark each fold `-` would re-expand with a gold `▿` on the owner row and
`▿N` in the panel title, clearing the markers as soon as the next press would sweep
instead. The footer shows `- collapse folds` or `- restore folds` depending on which
direction the next press would take. A panel with only open grouping banners reports
nothing to collapse or restore.

Press `_` for `-`'s all-panels sibling: one press sweeps every open agent node and clan
fold in every eligible tribe panel at once, sharing `-`'s per-panel records so the two
compose freely. It skips any effectively collapsed panel in both directions and works
identically from any selection, including whole-panel focus on a collapsed panel. With
nothing left to sweep anywhere, it restores every panel's last sweep. The footer shows
`_ collapse all folds` / `_ restore all folds` once at least two panels are eligible.

Uppercase `H` on a selected expanded panel hints every currently expanded agent node,
clan, and top-level grouping banner in that panel — including owners hidden behind a
collapsed banner — using the same adaptive hint keys as `L`, restricted to folds that
are not already collapsed. Typing a hint fully collapses that one fold and leaves the
remembered row and every other fold untouched; `H` never expands and never collapses the
panel itself, which stays lowercase `h`'s job. A panel with nothing expanded warns
without arming hint mode; an already collapsed panel keeps the existing
already-collapsed warning. Whole-panel `H` is unavailable in merged layout, where the
existing row/group-scoped ladder remains in effect. Use `,H` to open the same collapse
hints from any row, or from a selected panel to hint every tribe. That row ladder first
retreats a selected open workflow or session one fold level, then remaining group-wide
agent nodes, then the selected open clan, then every remaining open canonical clan in
the next group; the grouping banner closes only after those structural rungs are
saturated. Custom keys bound to `hooks_or_collapse_all` receive the same contextual
behavior and footer labels.

Whole-panel focus replaces the ordinary agent detail with a `TRIBE` document. Its four
`zz` metadata detail levels are:

| Level | Name      | Tribe summary content                                                                                                                                                                  |
| ----- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Glance    | Header, compact numbered top-level roster (in the jump panel), attention previews, clan-summary and prompt headline indexes (up to 8 each), and headings/counts for non-empty sections |
| 2     | Triage    | Bounded previews for every represented section                                                                                                                                         |
| 3     | Inspect   | Nested roster detail and grouped full section bodies, still with protective bounds                                                                                                     |
| 4     | Forensics | Unbounded bodies, tracebacks, the richest member annotations, and all-time runtime statistics and percentiles                                                                          |

From levels 1-3, `zZ` opens every fold to level 4; at level 4, it closes every fold to
level 1. `za` and `zA` adjust the section, or the `CLAN SUMMARIES`/`PROMPTS` entry, at
the top of the metadata viewport. Reply, slow-call, prompt, and clan-summary presence
enrichment is requested off-thread at every tribe level so known-empty sections can
remain absent; all-time runtime statistics remain level-4-only. Unknown required
disk-backed content produces one dim `⋯ scanning member data…` document tail rather than
per-section placeholders. The compact roster and its fixed numeric jump targets remain
present at all four levels; the number keys jump to top-level clans, sessions,
workflows, or agents and expand only the required ancestors.

Use `z1`-`z3` to select the collapsed, expanded, or fully expanded view directly; `z4`
selects the exhaustive view, including unbounded roster annotations and runtime
statistics. Direct numeric fold chords remain inside fold mode and do not trigger
numbered member jumps. Outside fold mode, these fixed metadata-member numbers are
separate from ordinary apostrophe entry hints, whose adaptive keys may use two
characters in a large list.

The `,H` leader chord opens the same collapse-by-hint picker as whole-panel `H`, from
any selection. From a row or banner it hints every expanded agent node, clan, workflow,
session, and top-level grouping banner in the focused tribe. From a selected tribe panel
it hints those owners across every expanded tribe panel and adds a title chip on each
expanded panel so picking it collapses that panel. Typing a hint fully collapses that
one entry and exits; `Esc` cancels. The ordinary apostrophe jump mode includes both
expanded and collapsed split-panel titles as destinations and preserves `Ctrl+O`
jump-back history.

### Tribe wait and fork targets

Use an `@<tribe>` reference where `%wait` or `#fork` normally accepts an agent name:

```text
%wait:@review
#fork:@review
```

This is a next-entity target, not a request to wait for every historical member of the
tribe. `%wait:@review` selects the earliest successfully completed `@review` entity
launched after the waiting agent: either one standalone agent or one complete clan
generation. Older entities, the waiting agent itself, failed agents, and incomplete
clans do not satisfy the dependency. A tribe-assigned member of a clan enrolls the whole
generation, so that candidate becomes eligible only after every member required by the
normal clan wait succeeds.

`#fork:@review` implies the same wait, then resumes from the selected entity. A
standalone match contributes its full conversation. A clan match contributes one
launch-ordered clan summary containing each member's sanitized prompts, outcome/model
metadata, reply size, and transcript path; full member replies are deliberately omitted
so the child can open only the transcripts it needs. Tribe targets can be mixed with
explicit agent or clan parents in a multi-parent fork, and sase's TUI prompt completion
offers visible `@tribe` values for both `%wait` and `#fork`. When no `%id` is supplied,
tribe waits and forks use neutral auto-names rather than derived `.w*` or `.f*` names
because the eventual parent is unknown at launch planning time.

sase's TUI can insert these group references directly. Select a clan's synthetic
container row and press `F` for `#fork:<clan>`, or press `W` for `%wait:<clan>`. For a
tribe, give its named panel whole-panel focus—expanded or collapsed—and use the same
keys for `#fork:@<tribe>` or `%wait:@<tribe>`. The reserved `@default` panel and
grouping banners are not group targets, and marked rows take precedence over the focused
clan or tribe for `W`. For a selected clan or tribe, sase's TUI prefixes either prompt
with a VCS tag only when every real agent currently in that scope resolves to the same
workflow and ref. Otherwise it omits the VCS tag so you can add the intended `#git`,
`#gh`, or other workflow reference yourself. Marked waits instead take VCS context from
the selected marked row, or the first named mark when the selection is elsewhere. The
current rows determine only that optional VCS prefix; they do not pin the eventual clan
or tribe fork source. See
[Forking Agents and Groups](../tui/agents-tab.md#forking-agents-and-groups) for
selection and revalidation behavior.

## Related

- [Agents and workspaces](index.md) — the section hub.
