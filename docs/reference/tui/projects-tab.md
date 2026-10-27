---
title: Projects tab
description: The Projects tab, adding and initializing projects, and the current-project indicator.
---

# Projects tab

This page lists the Projects tab, add and initialize flows, and the current project.

## Projects Tab {#projects-tab-1}

Open the SASE Admin Center with `#` and switch to the **Projects** tab with `5`, `Tab` /
`Shift+Tab`, or the main tab strip. The tab contains a second clickable strip:
**Projects · Repos · Workspaces**. `[` / `]` cycle these sub-tabs while `Tab` /
`Shift+Tab` continue switching the main Admin Center tabs.

The **Projects** sub-tab lists true, non-system projects only, with enabled projects
first and disabled projects still visible. Here, "true project" means a project backed
by its own main ProjectSpec, rather than an internal linked-repo backing record; a true
project can be enabled or disabled. Rows show a `CUR` marker, the display/canonical
name, VCS kind (`git` or `gh`), lifecycle state, active claims, workspace/repo counts,
and warnings. Telemetry-only directories and linked-repo backing records cannot appear.

| Key       | Action                                                                 |
| --------- | ---------------------------------------------------------------------- |
| `j` / `k` | Move selection                                                         |
| `'`       | Jump to a row via adaptive hints, within the active sub-tab only       |
| `/`       | Filter the current sub-tab                                             |
| `n`       | Open the New Project wizard (Projects sub-tab; inactive in the filter) |
| `?`       | Open Projects help                                                     |
| `s`       | Show a project the wizard just added when the filter hides it          |
| `[` / `]` | Cycle Projects, Repos, and Workspaces sub-tabs                         |
| `r` / `w` | Show repos or workspaces pre-filtered to the highlighted project       |
| `Enter`   | Run the highlighted project's default lifecycle action                 |
| `i`       | Initialize the marked set, or the highlighted project if unmarked      |
| `I`       | Initialize every enabled project (`sase init --all`)                   |
| `m` / `u` | Toggle one mark / clear all marks                                      |
| `e` / `A` | Edit the ProjectSpec / aliases                                         |
| `a` / `d` | Enable / disable the highlighted project or marked set                 |
| `c`       | Make the highlighted project current                                   |
| `Ctrl+D`  | Delete the highlighted SASE project directory or marked directories    |
| `F`       | Force the last blocked disable after confirming live-work checks       |
| `R`       | Reload records or the current inventory                                |
| `p`       | Open the shared project picker on the Repos or Workspaces sub-tab      |
| `Esc`     | Clear an inventory project filter; otherwise close the Admin Center    |
| `q`       | Close the SASE Admin Center                                            |

`c` requires the highlighted project to be enabled and launchable; pressing it on a
project that is already current, disabled, or not launchable reports why in the status
line instead of starting a write. `n` and `s` are inactive while the project filter is
focused, and `s` stays inactive until a filter is hiding a project the wizard just
added. `p` and `Esc`-to-clear-project apply on the Repos and Workspaces sub-tabs;
lifecycle keys such as `a`, `d`, `c`, `i`, and `n` do not. All of these keys are
configurable under
[`ace.keymaps.projects`](../config/ace-keymap-configuration.md#acekeymaps).

### Add or create a project

Press `n` from the list on the **Projects** sub-tab, or choose **Projects: New
project…** from the command palette. **Add** registers an existing repository;
**Create** makes a repository before registering it. The wizard prefers your last-used
provider, then the current project's provider, then the first available provider. Create
similarly prefers the last-used owner, then the current project's owner, the signed-in
account, and the first available owner.

1. **Source.** Select a repository and press `Enter` to add it, or press `n` from the
   list to choose the pinned Create row. `j` / `k` move, `[` / `]` switch providers, `/`
   focuses the filter, `f` toggles hidden forks, `.` toggles all hidden rows, and `R`
   refreshes discovery. If no Create row is available, `n` explains why. When a provider
   remedy is offered, `t` runs it in a terminal and refreshes afterward. In the filter,
   use arrow keys to move and `Enter` to choose; `Esc` returns focus to the list.
2. **Configure.** Set the project name, aliases, SASE setup, and whether to make it
   current. `Tab` moves through controls; `Space` toggles the focused checkbox. Create
   also offers provider-specific repository settings and checks validity and name
   availability before enabling Review. Activate the **Review** button to continue. For
   Add, `Ctrl+S` works only when that button is focused. The Back button or `b` outside
   a text field returns to Source; `Esc` first leaves a focused input, then returns to
   Source.
3. **Review.** Inspect the exact command, settings, warnings, and blockers. Press `y` to
   apply when the plan allows it. `b` or `Esc` returns to Configure with the draft
   intact.
4. **Progress.** The operation runs as a durable background process (a proc). `Space`
   toggles its raw log. `Esc` closes the wizard while the operation continues in Procs.
   If onboarding offers `sase init`, its separate initialization preview requires
   confirmation before applying.
5. **Ready.** `Enter` shows the project in Projects. `+` or `=` opens a prompt on its
   `+tag`; submit that prompt to launch an agent. `c` makes it current when it is
   launchable. If initialization was cancelled or failed, `i` offers initialization
   again. `Esc` closes and returns the result to Projects.
6. **Failed.** `r` returns to Review and checks the plan again; press `y` there to retry
   applying. `b` returns to Review with the last plan. `t` runs the apply command in a
   terminal, then checks the plan again. If repository creation succeeded before later
   setup failed, the repository is kept and retry resumes setup.

A partial add or create stops at **Failed**, even if a project record or repository
already exists. The failure view shows the setup error and any recovery command; it
does not offer initialization until setup succeeds. Empty repositories can receive a
first commit containing `sase/sase.yml` during setup; see
[Project registration and setup](../agents/initialization.md#project-registration-and-setup).

Source uses the discovery groups from `sase project suggest`: RESUME, ON THIS MACHINE,
SUGGESTED, LINKED TO YOUR PROJECTS, and DISABLED PROJECTS. Choosing a running RESUME
entry opens its existing proc in Procs; an interrupted entry opens a resume plan in
Review. A filter can reveal hidden matches, including enabled projects: choosing one
shows that project instead of adding it again. Pasting a supported repository ref offers
an Add row when that repository is not already among the candidates. With no known
owners, the detail card explains how to paste a ref or, for GitHub, configure
`github_orgs`. On terminals shorter than 30 rows, Source details collapse to one line.

When a filter hides the added project, the Projects pane keeps the filter and offers
**Show new project** (`s`), which clears the filter and selects the project. Completion
reloads the project list and refreshes the current-project launch context and `+tag`
catalog. Closing during Progress does not cancel the durable operation; successful
completion still refreshes Projects if that pane is mounted and records the provider and
owner preferences.

### Initialize from the Projects tab

`i` initializes the marked set, or the highlighted project when nothing is marked.
Disabled and system-managed rows in the mark set are dropped with a status message; if
nothing remains, sase's TUI warns and submits nothing. `I` always means the canonical
`sase init --all` inventory: marks, filter, and highlight are ignored.

Either key sets a status line immediately, then plans off-thread with
`sase init … --check --json`. When every target is already current, sase's TUI toasts
that and does not open a modal. Otherwise an initialization-plan preview shows the exact
apply argv, per-planner rows with the CLI's glyph vocabulary, and warnings and blockers
verbatim. The memory step may commit and push generated project memory; that warning is
shown with the same prominence as the CLI prompt. Confirm runs exactly one
`sase init … --yes` proc into the Procs tab and refreshes the pane in place. If the plan
has TTY-only blockers, `t` suspends sase's TUI into interactive `sase init` for the
blocked subset. `Enter` still means enable; initialization is never implicit.

The preview's own keys are listed on its border: `y` runs the plan, `d` toggles full
file diffs on and off, `t` hands the run to a real terminal when the plan has TTY-only
blockers (the row and key appear only then), and `Esc`, `q`, or `n` cancels. `Ctrl+D` /
`Ctrl+U` scroll a long preview. The run button is disabled outright when no project in
scope has a changed, runnable planner, and a plan whose runnable planners would
overwrite or delete a file is styled as a danger confirmation rather than a neutral one.

The current project — the same one the status-row `project: +<name>` chip names — is
marked on three surfaces at once, all in that project's accent color: a `+` in the row
table's `CUR` column plus its name rendered in that accent, a `current:+<name>` segment
appended to the summary line, and a `+CURRENT` badge on the detail panel's header line.
The detail panel also carries a dedicated `Current project:` line for the highlighted
row, whether or not it is current — stating the fact for a current row (and, when it
arrived via a Patch, which one) or the exact reason and fix for one that is not (enable
it first, it has no launchable ProjectSpec, or press `c`). This display always resolves
live and ignores `ace.current_project.indicator`, which only hides the status-row
cluster's project group; see [Current project](#current-project).

When one or more projects are marked, `a`, `d`, and `Ctrl+D` target the marked set
instead of only the highlighted row. Successful lifecycle changes clear the affected
marks; blocked or failed rows stay marked so you can inspect or retry them. Disabling
uses the same locked mutation path as `sase project disable`; live `RUNNING` claims or
artifact markers block it unless the `F` force retry is intentional.

The **Repos** sub-tab inventories every known primary, sidecar, linked, and opened
external repo for enabled projects by default. Rows show owning project, checkout
presence, and path; details include source, description, `auto_clone`, environment name,
and SDD storage mode. The **Workspaces** sub-tab joins every registry entry with its
claim, PID liveness, pin, last-used time, TTL staleness, and checkout presence. Missing
checkouts point to `sase workspace repair`, and dead claims are warning-styled. Both
sub-tabs load off-thread and show cached rows during refresh.

On first open, Repos and Workspaces seed their project filter from the
[current project](#current-project) when `ace.current_project.seed_filters` is on. Press
`p` on either inventory to choose all projects, an enabled project (`●`), or a disabled
project (`○`). Explicitly selecting a disabled project is how its repos/workspaces
become visible. `/` then filters within that project scope; `Esc` clears the scope and
the cleared filter sticks for the rest of the session. The picker is filterable by
display name, canonical key, or state and shows repo/workspace counts for each project.

`e` suspends sase's TUI, opens the selected ProjectSpec in `$EDITOR` (falling back to
`nvim`), holds the ProjectSpec edit lock for the editor session, then reloads project
records. In this panel, `Ctrl+D` asks for confirmation before deleting the entire SASE
project directory: ProjectSpecs, project-local config, artifacts, and related state
under `~/.sase/projects/<project>/`. Deletion is refused while the project still has
`RUNNING` claims or live artifact markers. It does not delete workspace checkouts, and
system-managed projects such as `home` are excluded from the panel.

## Current project

sase's TUI has one **current project**: the head of the VCS macro MRU store. Launching
an agent on a project — or on a Patch owned by that project — promotes it to that head.
`sase project set-current <project>` and the Projects tab's `c` key (see
[Projects Tab](#projects-tab-1)) move it the same way, by promoting the project to the MRU
head, without a launch. Click the status-row `project: +<name>` chip to open the `+`
launch picker, which is the surface that actually records a launch.

Because setting the current project and launching an agent both promote the same MRU
entry, making a project current also moves it to the head of the prompt bar's `<ctrl+p>`
VCS-prefix cycle — the same coupling a launch already produces.

The chip is the project half of the launch-context cluster at the far right of every
tab's status row, which reads `model: <launch default> · project: +<name>`. The dim
`model:` label reads `override` while a `default model` override is active, and when the
row is too narrow both labels drop, leaving `<launch default> · +<name>`. The
`· project:` group disappears when no current project resolves or the indicator is
disabled. On the Agents tab, the
[cap chip](agents-tab-grouping.md#grouping-modes) sits just
before the cluster. The chip's color is unique among currently enabled projects.
Hovering names the project, the MRU ref it came from, and (when the head was a Patch)
the Patch; the tooltip also names the two ways to make a project current: launch an
agent on it, or press `c` on the Projects tab. Hide the chip with
`ace.current_project.indicator: false`.

When `ace.current_project.seed_filters` is on (the default), first-open surfaces that
can filter by project seed from the current project instead of starting at all projects:

- the shared Artifacts project scope (Agent, Stitches, Beads, Plans, Files, Patches)
- the Statistics project filter
- the Repos / Workspaces inventory filters
- the Memory panel's scope ring
- the highlight in the `+` launch picker

The seed never overrides an explicit `project:` / `+name` term, a pick you already made
this session, or a surface that is already open. A mid-session launch or set moves the
chip live but does not re-scope those surfaces. Turn seeding off with
`ace.current_project.seed_filters: false`.

The Agents-tab search query is **not** seeded by default
(`ace.current_project.seed_agents_query: false`) because that query also drives unread
jumps and prospective clans, not just the visible list. When enabled, the seed is used
only if there is no remembered Agents query; a remembered empty query restores the
unfiltered view and suppresses the seed. One line of config turns seeding on.

Inspect the resolved project from the CLI with `sase project current`. See
[`ace.current_project`](../config/ace-behavior.md#acecurrentproject) for the
three fields.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [SASE Admin Center](admin-center.md) — Config, Logs, Machines, Procs.
- [Machines, statistics, and tools](machines-and-tools.md) — Machines, Statistics, Tools.
- [TUI keymaps](keymaps.md) — generated keymap defaults.
