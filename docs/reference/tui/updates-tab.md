---
title: Updates tab
description: The Updates tab for SASE core, plugins, and agent CLI updates from the TUI.
---

# Updates tab

This page lists the Updates tab for SASE core, plugins, and agent CLI updates.

## Updates Tab {#updates-tab-1}

Open the SASE Admin Center with `#`, then press `8`. The Updates tab is one
master/detail inventory: every SASE core package, plugin, and registered agent CLI
appears as a row, grouped into **SASE**, **Plugins · Built-in**, **Plugins ·
Community**, and **Agent CLIs** sections. An always-visible header above the list shows
either the all-current banner or a digest of update counts, cache age, install mode, and
any failed source — it never claims everything is current while a source is unknown or
failed. The list always shows every row (installed or not), with updatable rows first in
each section. `'` jumps to any row via adaptive hints, across every section.

Opening the tab never refreshes from the network. The first open in an ACE session
builds the inventory from local caches the automatic update check maintains (plugin
catalog, latest-version caches, editable checkouts' last-fetched upstream refs), without
PyPI/GitHub/npm or `git fetch`. Later opens reuse the in-memory inventory instantly;
when the automatic check has published newer results, the open re-reads those caches
instead. `r` refreshes everything from the network, and `checked … ago` is the age of
the last network check.

Core rows show SASE package versions and incoming commits in their own per-package
detail. Plugin rows bring the full
[`sase plugin`](../integrations/plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)
experience: filter the catalog, inspect a plugin, and install (`i`), update (`U`),
uninstall (`x`), or switch install mode (`m`). Agent CLI rows are provider-colored,
showing installed → latest versions, exact update or manual commands, vendor docs links,
update marks, and durable update history. Missing agent CLIs that SASE can install show
`latest v…` with an `[npm]` or `[script]` badge and carry the same install verb as
plugins: `i` installs the highlighted CLI (or every install-marked row), and `Space` /
`I` marks it for a bulk install. On any markable row — an installable plugin or CLI, or
an updatable CLI — `*` marks every visible row in that section with the same action, or
unmarks them when all are already marked. Marked rows show `[✓]`. `Esc` first clears
every mark (including filter-hidden ones); with nothing marked, `Esc` closes the Admin
Center. A filter that matches nothing shows `Nothing matches the current filter.` Every
install opens a confirm preview first — the exact command, plus for an agent CLI its
target directory and PATH status and, for a script install, the script URL, size, and
full SHA-256 — then runs the previewed plan sequentially in one tracked proc, CLIs
before plugins when a marked set mixes both. CLIs SASE cannot install toast their manual
instructions instead. Providers that opt out of independent CLI management, including
the bundled internal Fakey provider, are omitted from the Agent CLIs section. The plain
substring filter (`/`) searches every row's own fields — name, owner/repo, description,
and topics for plugins; name, display name, binary, install method, route, package, and
`not installed` for agent CLIs; package name for SASE rows — across all sections at
once.

Every sase-managed agent-CLI update run from `,U`, `,E`, `A`, or `sase agent-cli update`
— and every install run from the Updates tab — is appended to
`~/.sase/logs/agent_cli_updates.jsonl`. Runs where no command reaches a terminal outcome
are not recorded. Install runs show a green `↓` with `installed <version>` and carry the
`i` badge; update runs keep their existing glyphs and badges. Highlighting an Agent CLI
row renders that journal below its details; `H` toggles between this CLI's executed
install/update rows and a run-grouped timeline across all CLIs. Configure the panel with
`ace.updates.agent_cli_history` and `agent_cli_history_max_rows`.

Automatic checks publish one composite snapshot after first paint. Ten-minute session
ticks only revalidate cached SASE/plugin rows and provider names already known outdated;
full discovery waits for the longer configured recompute cadence, and provider registry
lookups retain their own cache. The top bar renders the `updates:` group as its only
dark chip (lime `⬆ N` SASE and sage `CLI ⬆ N` segments with separate counts, plus a lime
`core` tag for a sase-core rebuild, plus a green `⚙` gear inset at the left edge while
SASE is updating, a yellow `⚙` gear inset while a tracked restart waits for TUI-local
tasks and installation changes, or a red `⚙` gear inset while the most recent update
attempt failed). Independent commands keep running. Durable operations started from this
TUI still finish their result handling first, within the same 60-second wait.

A red gear means the last update or update-planning attempt settled with an error, or
ACE exited before it finished (an interrupted attempt, whose install may be incomplete).
Clicking the red gear opens the failure report: the failed attempt's label, error, and
last output, with `u` opening the Update panel, `d` dismissing the recorded failure, `y`
copying the report, and `q`/`Esc` closing. The report expands automatically to fit its
content and terminal: a small failure stays compact, a long command widens it, and a
long transcript grows it taller up to nearly the whole terminal. Resizing the terminal
reflows the report without losing focus or scroll position. When the report still
overflows, only the report scrolls (`Ctrl+U`/`Ctrl+D` half-page, `g`/`G` top/bottom);
the title and actions stay pinned. `d` dismisses the recorded failure (clearing the
gear), while `q`/`Esc` only closes the report and keeps it recorded. A later attempt
that starts after the failure clears the gear on success, as does dismissing it. The
record lives in `~/.sase/update_attempts.json`, so it survives ACE restarts and every
ACE instance on the machine converges on it at startup and on the ten-minute
update-check tick.

For editable host, core, and plugin checkouts, the running TUI also remembers the Git
HEAD imported by the process and cheaply checks whether the checkout has moved on disk.
It warns once for each new on-disk generation. While any imported root is stale, the
global Update panel (`,U`) adds **Restart ACE** as its first row; press `x` or `X` to
restart after the same TUI-task and installation-change drain used by post-update
restarts. Independent commands keep running. Durable operations started from this TUI
still finish their result handling first, within the same 60-second wait. This reloads
the already-updated code and does not fetch or modify a checkout.

Every mutation still plans before it runs, and `Ctrl+D` / `Ctrl+U` scroll long preview
panes. When commit previews are enabled and a comparable range is available, core and
installed-plugin **update** confirmations load incoming commits by repository in the
background; install confirmations do not. The global `,U` chord opens the **Update
panel** from already-fetched SASE and provider snapshots — no Admin Center, no live
inventory load. `e` / `s` / `p` (or `⏎` on the highlighted row) choose Everything, SASE,
or providers and then show the same `y`/`n` confirmation sase's TUI uses elsewhere,
containing only the selected legs. `E` / `S` / `P` plan those same scopes and skip only
that final confirmation after a runnable preview succeeds; failed or already-current
previews still do not mutate. `,E` is the global direct alias for `,U` then capital `E`:
it uses the same cached snapshots, preview planning, no-op handling, and error reporting
without mounting the panel. The providers row lists each captured provider with its
installed-to-latest version transition and marks manual-only providers by name, and the
Everything row summarizes both legs on one line. While a recorded update failure exists,
the panel adds **Last update failed** (or **Last update interrupted**) as its first row,
above **Restart ACE**, with an `✗ failed` chip and the failure's label and error; `f` /
`F` opens the failure report and `d` dismisses the failure in place without closing the
panel, and the open panel refreshes when the journal view changes. `r` re-checks in
place; `q` / `Esc` cancel. An Everything confirmation groups SASE and Agent CLI work
into labeled sections with update/current/skipped glyphs, counts, and commands. The
tracked proc runs Agent CLI commands first and the SASE/core/plugin leg second. A
failure in one leg is reported alongside the independent earlier results. After a
changed core/plugin update restarts sase's TUI, the one-shot result toast can show
applied commits grouped by repository as well as file/line statistics. Configure the
toast with `ace.updates.post_update_toast_commits`, `post_update_toast_max_commits`, and
`post_update_toast_diffstat`.

The providers leg still captures the agent-CLI candidates from the latest completed
automatic result, revalidates exactly those names, and never broadens the captured set
from an Updates-pane load. Manual-only providers remain in the preview with their
suggested command or docs. A real SASE/core/plugin code change restarts sase's TUI and
its service controller only after provider work finishes, while provider-only updates
refresh in place and report per-provider results (versions, failures, and manual
commands) in the completion toast instead of restarting. Before that restart, sase's TUI
waits up to 60 seconds for TUI-local tasks, in-flight submissions, and installation
changes to finish (a toast reports the queued restart) and then restarts anyway with a
warning naming whatever is still active. Independent work — agent tool runs, ordinary
durable commands, oneshots, monitor turns, and service daemons — keeps running. Durable
operations started from this TUI still finish their result handling first, within the
same 60-second wait.

`u` remains pane-wide and updates SASE core plus installed plugins. `A` is the separate
pane-wide agent-CLI action: it updates marked agent CLIs from anywhere in the pane, and
with no marks it targets every safely updatable installed CLI. `i` installs
`Space`/`I`-marked plugins and agent CLIs together — agent CLIs first, then plugins, in
one tracked proc — or the highlighted row when nothing is marked. See the
[Updates tab reference](admin-center.md#updates-tab) for the full keymap
and behavior, [Plugins](../integrations/plugins.md) for the equivalent
`sase plugin` CLI, and
[Agent providers](../providers/agent-clis.md#inventory-and-updates) for the
equivalent `sase agent-cli` CLI.

The Updates pane still binds `a` to a tracked agents-sidecar publication sync. That
action publishes and reconciles agent hoods for every enabled project; it is not part of
the comprehensive update. See [Agent Hood Synchronization](../agents/index.md)
for privacy, publication, status, and recovery behavior.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [SASE Admin Center](admin-center.md) — Config, Logs, Machines, Procs.
- [Plugins](../integrations/plugins.md) — plugin CLI and updates.
