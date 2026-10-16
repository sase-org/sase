# sase's TUI User Guide

## Overview

sase's TUI is the primary TUI for the SASE toolkit. It provides an interactive interface
for navigating, managing, and operating on Patches, agents, and machine services.

## Launching

```bash
sase tui [QUERY] [options]
```

Run `sase tui` from an interactive terminal. It opens on the Agents tab and starts the
service host (pass `-x` to skip that). Press `?` on any tab for the keymap and a short
guide, `:` for the [Command Line](#command-line), `;` for the
[Command Palette](#command-palette), and `q` to quit. The command was previously
`sase ace`, which no longer exists; the TUI's settings still live under the `ace:`
section of `sase.yml` (for example `ace.keymaps` and `ace.page_size`).

If no Patches query is provided, sase's TUI loads the last used Patches query, then the
first saved Patches query, then falls back to `!!!` for error suffixes. The top-level
Agents tab restores its own last submitted Agents query after startup.

### CLI Options

| Option                                     | Description                                                                                                                                                  |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `QUERY` (positional)                       | Query string for filtering Patches                                                                                                                           |
| `-m`, `--model-tier`                       | Override model tier for all LLM providers (`large` or `small`)                                                                                               |
| `-M`, `--model-size`                       | Deprecated alias for `--model-tier` (`big` or `little`)                                                                                                      |
| `-p`, `--profile [PATH]`                   | Profile the TUI session with pyinstrument; optional output path                                                                                              |
| `-r`, `--refresh-interval`                 | Auto-refresh interval in seconds (default: 10, 0 to disable)                                                                                                 |
| `-s`, `--sanity-refresh-interval`          | Full sanity-refresh interval in seconds (default: 300); see [Auto-Refresh](#auto-refresh)                                                                    |
| `-x`, `--no-service`, `--no-axe`           | Disable auto-starting the service host on startup                                                                                                            |
| `-v`, `--vcs-provider`                     | Override VCS provider (`git`, `hg`, or `auto`)                                                                                                               |
| `-R`, `--restart-service`, `--restart-axe` | Restart an already-running service host on startup (no-op if it is not running)                                                                              |
| `-t`, `--tab`                              | Tab to focus on startup (`agents` by default, `artifacts`, or `services`; `axe` is a compatibility alias, and `changespecs` and `patches` alias `artifacts`) |
| `-T`, `--tmux`                             | Launch sase's TUI in a new tmux window and print the target for external control                                                                             |

When profiling is enabled, sase's TUI writes text output to `PATH`. If `PATH` is
omitted, it uses the managed temp tree:
`$SASE_TMPDIR/ace-profiles/ace_profile_<timestamp>.txt` when `SASE_TMPDIR` is set, or
`$SASE_HOME/tmp/ace-profiles/ace_profile_<timestamp>.txt` otherwise (`SASE_HOME`
defaults to `~/.sase`). On exit, sase's TUI prints the shortened path and copies it when
a clipboard tool is available.

### Examples

```bash
sase tui                              # Last query, first saved query, or "!!!"
sase tui '"feature" AND "Drafted"'    # Filter by name and status
sase tui '+myproject'                 # Filter by project
sase tui -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

When `--profile` is enabled, sase's TUI prints a shortened profile-output path after the
TUI exits and tries to copy that shortened path to the system clipboard (`pbcopy`,
`wl-copy`, `xclip`, or `xsel` when available).

### Agent Screenshots

Use `sase screenshot` when you need a PNG of the real TUI state an agent would see. The
command starts `sase tui` in the detached `sase_ace_agents` tmux session at `120x40`,
waits for the screen to paint, sends optional tmux keys, asks the live app to export
SVG, then rasterizes that SVG with the same bundled-font renderer used by the golden PNG
suite.

```bash
sase screenshot -o /tmp/sase.png
sase screenshot -p j -p j -w 'Ready' -o /tmp/sase.png
sase screenshot -p / -w INSERT --type 'machine:apollo' -w 'machine:apollo' -p enter -o /tmp/sase.png
sase screenshot --host apollo -o /tmp/sase-remote.png
sase screenshot --keep -- -t services
sase screenshot --window sase_ace_agents:sase_tmux_1 -o /tmp/sase-again.png
```

Repeatable `-p/--press`, `-T/--type`, and `-w/--wait-for` form one argv-ordered input
script, so a query filter can be typed and submitted without a second `--window`
capture. `--type` sends literal TUI text (`tmux send-keys -l`). Send the query key as a
literal `-p /`: tmux has no `slash` key name, so `-p slash` types the letters `slash`.
Wait for the input to open (`-w INSERT`) before typing, and wait for the typed text
before `-p enter`.

By default, the tmux window is killed after capture. Pass `--keep` to leave it running,
drive it manually with `tmux send-keys`, and recapture it later with `--window`. The
command pins TUI animations off and uses truecolor terminal defaults, but it still shows
live machine state and timestamps by design. If capture times out, the error includes
the final `tmux capture-pane` text so you can see what the TUI was showing.

Pass `--host` to run the live TUI and SVG export on an enrolled machine alias or any raw
SSH destination, then fetch the SVG and rasterize it locally. Enrollment only supplies a
convenient `ssh_target`; SSH itself is full shell access and uses your normal SSH trust
boundary, not gateway-scoped credentials. Remote screenshots show that machine's
installed `sase` and state, not your local working tree. The remote `sase` commands run
through the account's noninteractive login shell so tools installed under login-profile
paths such as `~/.local/bin` can be found without allocating a terminal. Check the
printed `remote_sase_version=sase <version>` line when comparing results; it is read
from `sase version --json` on the remote host. A remote host needs `sase`, `tmux`, and
SSH access, but it does not need the local visual rasterizer dependencies.

### Clipboard Transports

Every copy inside sase's TUI runs in the background and tries both a verifiable system
transport and OSC 52 for the client terminal. Inside tmux, sase's TUI tries
`tmux load-buffer -w -` first; otherwise the system candidates are `pbcopy`, `wl-copy`,
`xclip`, and `xsel` as appropriate for the platform and display environment. A plain
`Copied …` toast means a subprocess transport confirmed success, while
`Copied … (OSC 52)` means sase's TUI emitted the terminal escape sequence without a
verifiable subprocess result. OSC 52 payloads above the terminal-safe size limit are
skipped. If neither transport works, sase's TUI opens the generated text in a read-only
fallback view so it can still be selected and recovered.

## Tab System

sase's TUI has three tabs, cycled with `Tab` and `Shift+Tab`:

While a prompt input bar is open, `Tab`/`Shift+Tab` belong to the prompt (snippet
expansion, tabstops, list indent) and never switch tabs.

| Tab           | Description                                                                                                                                                                                                                                                                                                                                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agents**    | View running and completed agents, their files and prompts                                                                                                                                                                                                                                                                                                                               |
| **Artifacts** | Browse Commits, Patches, Beads, configured document providers, and Files. Agent history lives in the Agents tab Archive (`,a`); the Artifacts ▸ Agent sub-tab is retired (restore it with `sase flag disable artifacts_agent_pane_retired`). See the [Artifacts pane contract](contribute/artifacts-pane-contract.md) and [visual grammar](contribute/artifacts-pane-visual-grammar.md). |
| **Services**  | Monitor the service host, configured service procs, scheduler work, and background commands                                                                                                                                                                                                                                                                                              |

Agents is the first tab and the startup default. Each tab has contextual help: press `?`
to open the Help modal on its **Keymaps** view, then `]` to switch to the tab's
**Guide** view. While Help is open, the configured tab-switch keys still switch sase's
TUI tabs and refresh both views in place. By default those keys are `Tab` and
`Shift+Tab`; if you remap them, the modal follows the configured keys.

Press `/` in the Keymaps view to open a live filter bar. Typing splits the query into
whitespace-separated tokens that must **all** match — each token is checked against a
row's section name, key display, or description, so a token that matches a section name
(e.g. `beads`) pulls in every keymap in that section. Matched text is highlighted and a
counter shows how many keymaps and sections matched. The filter follows you across
sase's TUI tab switches while Help stays open, but resets whenever the panel is closed
and reopened. `Esc` clears an active filter before it closes the Help modal.

On first use, empty tabs render onboarding states instead of blank panels: the Patches
view shows a getting-started card when no Patches or saved queries exist yet, and the
Agents tab walks through launching a first agent — the project/Patch launch hint appears
only when a launchable target exists — and can recommend installing plugins from the
Admin Center when no third-party plugins are installed. Onboarding cards carry "learn
more" links into the published docs. An empty Beads pane points agents to
`/sase_new_task`, calls out sized draft tasks, and explains how ready tasks enter
TaskTriage.

Within Artifacts, number keys follow the visible left-to-right order of the strip:
Commits, Patches, and Beads are always **1**, **2**, **3**; configured document-provider
tabs such as Plans and Research take the next digits; and Files, which always renders
last, carries the highest digit — **4** with no provider tabs configured, **6** with
two. Digits stop at `9`, and the Files pane keeps `9` when the runtime strip grows past
nine panes; middle overflow panes may then have no digit. Use `[` / `]` to cycle through
the complete runtime strip. As horizontal space tightens, the strip chooses the widest
tier that fits from a full → compact → micro ladder and re-renders only when the tier
changes. Compact removes outer padding; micro also tightens the separators and hides
inactive labels, leaving their digits and icons visible. If even micro is wider than the
available space, micro remains selected. Every Artifacts tab has an icon, including
provider tabs whose missing or invalid `ref.icon` falls back to the generic `◆`, so the
micro tier never leaves an inactive tab unidentified. Hovering a tab shows that pane's
one-sentence description. These keys act only while Artifacts is visible. Press `p` on
any Artifacts pane to change the shared project scope — first-open seeds from the
[current project](#current-project) — or use the command palette to jump directly to a
top-level view. Patches remains query-scoped: choosing a project there rewrites the
Patches query's `project:` token. The strip order does not change the entry point:
opening Artifacts still selects Commits by default.

### Contextual Artifact Links

sase's TUI owns one link rail across the three top-level tabs. It appears when the
current selection has artifact links: an Artifacts-pane entry, a named agent or session
turn, or an AXE job. Synthetic clan containers, routines, and background-command rows do
not provide a link subject. The rail includes a breadcrumb while a link-follow trail is
active.

Press `$` to arm the rail. Then press `$` again to follow its first entry, `1`-`9` for a
numbered entry, or `0` to open the complete links panel. The rail always advertises
`$0 all` or `$0 +N more`, so links beyond the first nine remain discoverable. Several
projected links produced by the same rule may collapse into one entry; following that
entry opens the panel already scoped to the group.

In the panel, `a`-`z` follow the first 26 entries directly, Enter follows the
highlighted entry, arrows or `Ctrl+N`/`Ctrl+P` move, and Esc closes it. `-` removes a
writable durable link and `+` creates a link from marked rows where that action is
available. Projected links are read-only. Rows show relation direction, rationale,
provenance, and missing targets; the panel shows a separate notice when the aggregate is
stale. Two glyphs pre-flag a row before you follow it, using the same resolution the
follow path itself uses: `⊘` means the ref is dangling — no pane resolves it at all —
and `↻` means the target exists but is not selectable in place, so following it will
rewrite the destination pane's query. A destination pane that is still loading is not
flagged, because "not in the result set yet" there is a loading artifact rather than a
real reveal need. The `?` help modal lists both glyphs beside the link-follow keys.

Link follows can cross tabs and keep a bounded 32-hop trail. `Ctrl+O` walks backward and
`Ctrl+Shift+O` walks forward, restoring the tab, pane, project scope, query, selection,
and supported AXE fold state. If no link-trail hop is available, those keys retain the
current pane's normal jump-stack behavior. Ordinary navigation clears the link trail.
See [Artifact Links](reference/artifact-links.md#browsing-links-in-sases-tui) for
relation and projection details.

#### Link Jumps

Following a link whose target is outside the destination pane's current result set does
not fail. Every jump — the `$` link rail, the `$0` links panel, and relation jumps
outside Patches — runs one engine: it plans a single verified rewrite, then commits it
once. The query bar always truthfully describes what is shown, and query history records
exactly one `^` entry, which restores the original query and selection. While the
destination pane is still loading, the jump waits for it rather than reporting a miss.
Starting a new jump cancels one still in flight.

| Step          | When                                          | What happens                                                                                                                                  |
| ------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Resolve       | Always                                        | Find the target through the destination pane's own row identity, re-resolved once the pane has loaded.                                        |
| Scope         | The current project scope excludes the target | Switch to the target's project, or to All projects if its project is unknown and the current scope cannot resolve it. Never narrows from All. |
| Select        | The target is visible                         | Select it. No toast.                                                                                                                          |
| Fold          | A collapsed fold hides it                     | Expand the minimum fold, then select. No query change, no toast.                                                                              |
| Acquire       | The row is not in the pane's loaded inventory | Fetch it directly from its source in the background, then continue.                                                                           |
| Context       | The query or limit hides it                   | Rewrite to the context query below, verified against the target's row before committing.                                                      |
| Identity      | No context, or the context still misses       | Rewrite to the tightest query that names the row (`id:`, `sha:`, …), keeping the limit.                                                       |
| Neutral       | Still missing, where allowed (never Stitches) | Replace the query with a blunt `limit:all`.                                                                                                   |
| Honest report | Everything missed                             | Say so: a dangling ref, a load failure, an unconfigured provider pane, or "not in `<Pane>`".                                                  |

The rewrite lands the target inside its natural session — never an isolated row — and
keeps the current `limit:`, raising it only when the session would not fit:

| Target                              | The query becomes                                                                                  | Lens label                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Bead phase `sase-16n.7`             | `id:sase-16n.*`                                                                                    | `epic sase-16n`                        |
| Bead epic `sase-16n`                | `id:sase-16n id:sase-16n.*`, epic fold expands                                                     | `epic sase-16n`                        |
| Bead task or flag `sase-abc`        | `id:sase-abc`                                                                                      | `bead sase-abc`                        |
| Agent hood member `sase-16n.7`      | `name:sase-16n.*`, or `(name:sase-16n OR name:sase-16n.*)` when the root exists                    | `sase-16n hood`                        |
| Lone agent `x`                      | `name:x`                                                                                           | `agent x`                              |
| Agent session turn `x--y`           | `session:x`                                                                                        | `session x`                            |
| File                                | `agent:<creating agent>`, else `id:<file>`                                                         | `files from <agent>`, else `file <id>` |
| Plan or provider doc                | `path:<doc path>`                                                                                  | `plan <name>` or `<provider> <name>`   |
| Stitch `repo@sha`                   | `repo:<repo> since:<day> until:<day>`, plus `project:`, `sidecar:true`, or `merges:show` as needed | `<repo> · <day>`                       |
| Patch in a stack                    | `ancestor:<stack root>`                                                                            | `stack <root>`                         |
| Submitted, reverted, archived patch | `name:<patch>`                                                                                     | `patch <name>`                         |

The `*` above is the [wildcard filter](reference/query-language.md#wildcards):
`id:sase-16n.*` matches every phase of epic `sase-16n` but not the epic itself.

An `agent:` link climbs a four-step ladder, stopping at the first step that holds.
Loaded on the Agents tab, it reveals in place, switching agent tabs and opening any
collapsed fold, group banner, or tribe panel around it. Hidden only by the Inbox filter,
the filter is rewritten to an exact `name:"…"` query, with the old query waiting on `^`.
Dismissed from the Inbox, it opens read-only in Agents ▸ Archive with
`in:archive name:"…"`, selecting the row and recording one `Ctrl+O` hop. With no record
on this machine, a toast says so and nothing changes: the current tab, query, selection,
and pages stay exactly as they were. A `job:` link lands on the Services tab and expands
the job's routine fold.

Each rewrite explains itself in one toast naming the new query, what hid the target, any
scope change, and the real keys that restore (`^`) and walk back (`Ctrl+O`):

```text
↪ Bead sase-16n.7
query  id:sase-16n.* limit:100
was    -status:closed limit:100 · hidden by -status:closed
epic sase-16n · ^ restore · Ctrl+O back
```

Extra lines appear only when they apply: `scope  <old> → <new>` (project display names,
or `All projects`) and `fetched  outside the loaded rows` after an Acquire. The agent
ladder reports in its own words instead:
`The inbox filter hid it — showing name:"…" · ^ restores your filter` after a filter
rewrite, `<source> — dismissed … · ⏎ restore · ctrl+o back` on an Archive arrival, and
`agent:… has no record on this machine` when nothing changes. The `was` line names the
terms that hid the target (`hidden by your query` in a Boolean-dialect pane, or
`hidden by the project scope`), or `past limit:N` when only the limit did. The key names
follow the live keymap, and the toast stays for about 8 seconds. Selecting,
fold-expanding, switching scope, or fetching without a rewrite shows no toast.

While a rewrite is live, the pane's info header shows a reversible **lens chip** —
`↩ sase-16n.7 · epic sase-16n` in the pane's accent color, followed by a dim
`^ to return` naming the configured `prev_query` key rather than introducing a new
binding. The lens is derived from the live query rather than stored as a flag: it is
active only while the pane's canonical query is still exactly the query the reveal wrote
and the pane's dialect has not changed. Editing the query yourself, walking query
history with `^` / `_`, loading a saved query, or triggering a fresh reveal all end it
with no separate clear step.

### Split Modes in Artifacts Panes

Every Artifacts pane starts with an even left-list/right-detail split. Press `}` to grow
the list panel or `{` to shrink it. The mode is shared by every Artifacts sub-tab and
cycles with wraparound in either direction:

| Mode     | Left panel | Right panel |
| -------- | ---------- | ----------- |
| `narrow` | 30%        | 70%         |
| `even`   | 50%        | 50%         |
| `wide`   | 70%        | 30%         |

The `{████}` badge at the right of the sub-tab strip shows the current mode in the
active pane's accent color: one filled cell is narrow, two is even, and three is wide.
Clicking the badge cycles forward, like `}`.

The Patches pane remains content-sized instead of reserving empty list space. Its mode
sets the maximum list width for the available terminal width, while the existing 43-cell
readability floor and 80-cell upper bound still apply.

### Pane Description Brief

Every Artifacts pane — the five built-ins, the Plans pane, and every pane a sidecar ref
creates — carries a resolved, never-empty description, shown as a host-owned brief
directly under the sub-tab strip. Press `D` to cycle it through three modes:

| Mode      | What you see                                                     |
| --------- | ---------------------------------------------------------------- |
| `off`     | Nothing; the row disappears entirely.                            |
| `summary` | One line: an icon and a one-sentence summary, ellipsized to fit. |
| `full`    | The summary plus a longer body, capped at 6 rows.                |

`ace.artifacts.description_mode` seeds which mode a session starts in (default
`summary`); `D` changes it in memory for the current session only. Clicking the brief
cycles it the same way. An unconfigured document-provider pane shows, in `full` mode
only, a dim italic hint naming both places its description can be configured:
`ref.pane.description` in the sidecar's ref config, or
`ace.artifacts.panes."<pane_id>".description` in `sase.yml`. See
[`ace.artifacts`](reference/config/ace-behavior.md#aceartifacts) for the config surface
and
[Artifacts pane visual grammar](contribute/artifacts-pane-visual-grammar.md#pane-brief)
for the full rendering rules.

### Navigation in Agent, Commits, Beads, Provider Documents, and Files

The Agent pane is retired by default (`artifacts_agent_pane_retired`) and shows only
with the opt-out. The non-Patches panes share fast navigation over their selectable
left-panel entries. Commits and Files skip day headings; Agent, Beads, and provider
document panes skip group, section, and empty-state rows as applicable. Movement clamps
at the first or last entry and silently does nothing when a list is empty.

| Key                       | Action                                                                                 |
| ------------------------- | -------------------------------------------------------------------------------------- |
| `g` / `G`                 | Select the first / last agent, commit, issue, bead, document, or file                  |
| `Enter`                   | Open the selected commit, document, bead, or file in its full-screen reader            |
| `Ctrl+F` / `Ctrl+B`       | Move down / up 10 selectable entries                                                   |
| `Ctrl+D` / `Ctrl+U`       | Scroll the active right-hand detail pane down / up (half page)                         |
| `'`                       | Show adaptive entry hints; press `'` again for the first entry or the last jump origin |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk the link trail first, then the pane jump stack; back falls through to first hint  |
| `$$` / `$1`-`$9` / `$0`   | Follow the first / numbered artifact link, or open the complete links panel            |
| `Ctrl+J` / `Ctrl+K`       | Load `ace.page_size` more rows / unload that page (rewrites the host `limit:` cap)     |

Hint keys select an entry without activating it. Jump-back history is kept separately
for each non-Patches pane, and stale origins disappear automatically after filtering,
changing project scope, refreshing data, or collapsing an expanded bead tree. Escape or
an invalid hint exits jump mode. These actions use the configured keymap values; the
keys above are the defaults.

On the Agents tab Archive, `Enter` opens the [Archive chooser](#archive-agents-tab). `l`
/ `h` expand and collapse containers.

When the selected entry has declared relationships, a relation panel appears at the
bottom of the list column, starting collapsed into a one-line rail that names its own
expand key (`.` by default) so it is never hidden knowledge. Press `.`
(`toggle_relation_panel`) or click the rail to expand it; the expanded panel's border
carries the reverse affordance (`{key} collapse`, bottom-right) so it can be collapsed
the same way. Its section names come from the pane contract, so examples include parents
and children, document lifecycle stages, dependencies, linked beads or plans, and
file-version families. Navigation is two keystrokes: first a relation mode, then the key
printed in square brackets beside the target row. The modes are `<` for ancestors, `>`
for descendants, and `~` for session or siblings, and the footer lists only the ones the
current entry actually has; these keys stay live even while the panel is collapsed. A
section header ending in `(N hidden)` means the query is filtering out that many
targets, a row ending in `(missing)` points at an entry that no longer exists, and a row
ending in `→ <pane>` crosses to another Artifacts pane.

On Patches, choosing a hidden same-pane target rewrites the query to reveal it rather
than failing. Patches saves the query and selection you started from first and pushes
the old query onto the same history stack `^` walks, so `^` returns to the exact view
you came from. Other panes run relation jumps through the same engine as `$` link
follows (see [Link Jumps](#link-jumps)): a filtered-out target is unfolded, fetched, or
revealed by one reversible query rewrite, and each jump adds a link-trail hop that
`Ctrl+O` walks back.

Shared entry-jump surfaces allocate hints from the zero-based alphabet `0`–`9`, `a`–`z`,
`A`–`Z`. A session with at most 62 targets uses one character (`0` through `Z`). A
larger session uses two characters for every target, beginning `00`, `01`, …, `0Z`, `10`
and ending at the fixed `ZZ` capacity. The first character of a two-character hint keeps
jump mode open; the second completes the jump. Hints remain case-sensitive.

Outside the Artifacts panes above, a single shared implementation backs `'` everywhere
it appears: each Admin Center working section (see
[Global Keybindings](#global-keybindings)) and four modals — the notification options
modal, the model picker, the saved-group revival modal, and
[Launch Control](reference/tui/launch-control.md#launch-control-1). In all of them,
pressing `'` a second time while the hints are painted is the **jump back** key: it pops
the most recent origin off a bounded stack of the last ten pre-jump positions, rather
than toggling between one saved target and the current row. With an empty stack it falls
through to the first hinted row instead. The footer shows which of the two the next `'`
will do — `JUMP ' back` while the stack holds an origin, `JUMP ' first` when it does
not. Changes that shift which row is where — refiltering the model picker, paging or
deleting in the revival modal, drilling into or out of a Launch Control bucket, or an
async provider-snapshot reload — discard the stored origins instead of leaving them
pointing at whatever row inherited the index.

### Copy Mode in Agent, Commits, Beads, Provider Documents, and Files

Press `%` on any non-Patches Artifacts pane to open the context-aware **Copy as…**
palette for the visible entry. Rows are grouped by representation, show their configured
accelerator and a warm preview, and can be selected with the mouse, arrow keys or
`j`/`k` plus `Enter`, or the accelerator directly. `q`/`Esc` cancels. If an accelerator
is configured as `j`, `k`, or `q`, the configured copy target wins over navigation or
cancellation.

| Pane            | Keys                                                                                                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent           | `%@` artifact ref · `%!` ref in agent prompt · `%n` name · `%l` Markdown link · `%p` artifacts path · `%c` chat path · `%P` prompt · `%j` metadata JSON                          |
| Commits         | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` full SHA · `%m` message · `%r` `repo@sha` · `%p` plan                              |
| Beads           | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` id · `%t` title · `%b` description and notes · `%d` design · `%u` linked issue ref |
| Plans           | `%@` artifact ref · `%d` bead design ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` bead id · `%p` path · `%t` title · `%b` body                |
| Other providers | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%p` path · `%t` title · `%b` body                                                      |
| Files           | `%%` contents · `%@` artifact ref · `%L` Markdown link · `%p` stored path · `%o` source path · `%l` label · `%j` metadata JSON · `%!` ref in agent prompt                        |

`%s` captures the current `sase tui` tmux pane on every view.

The palette and copied value follow the active pane. After selection or cancellation,
the footer returns to the active pane's normal bindings. An unknown printable key warns
but leaves the palette open so another choice can be made.

When entries are marked, the reference choice copies newline-separated prompt
references, the Markdown-link choice copies a bullet list, the metadata-JSON choice
copies one array, and the handoff choice seeds one prompt with the marked set. Entries
that cannot produce the selected representation are skipped; the completion toast
reports both the copied and skipped counts. The palette title reports the visible marked
count and applicable rows use plural labels such as **commit SHAs**.

The same `%` prefix opens the palette above copy-forwarding readers and modals,
including the preview panel. Dismissing the palette returns to the underlying modal.
Snapshot choices dismiss the palette before capture, so the palette itself is not
included in the copied pane.

### Marks in Agent, Commits, Beads, Provider Documents, and Files

Press `m` to mark or unmark the selected entry and `u` to clear the active pane's marks.
Each non-Patches pane keeps an independent stable-target mark set, so marks survive
refreshes and switching panes without affecting marked PRs. Changing the shared
Artifacts project scope clears the non-Patches marks.

When marks exist, the pane's `%` copy targets operate on marked entries in visible order
instead of only the selected entry. Identity, location, and data representations use
paste-ready forms; content dumps retain labeled fenced sections. Content-shaped targets
are capped at 512,000 bytes per item and per assembled payload, with an explicit
truncation banner and toast. The footer shows the active pane's mark count only while
that count is nonzero.

### Filtering Agent, Patches, Commits, Beads, and Plans

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
[`sase agent search`](reference/cli/agent.md#sase-agent-search). It accepts `AND`, `OR`,
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
[VCS Provider Reference](reference/vcs/providers.md#sase-stitch-list)). `project:` is
not repeatable, comma-listable, or negatable because it selects the repository
constellation before commits are collected. With no `project:` token, collection spans
all projects. It accepts a configured project name, ProjectSpec directory key, or alias;
committed known values are rewritten to the configured project name. On first open, when
`ace.current_project.seed_filters` is on, the shared Artifacts project scope seeds from
the [current project](#current-project) unless an explicit `project:` / `+name` term
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
[flag beads](reference/work-units/bead-lifecycles.md#flag-bead-lifecycle) — the
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

### Beads Pane

The top-level Beads view (`3`) is the work-item home for standalone tasks, epic plan
beads, and their phase beads. Every bead appears once: tasks occupy their own section,
while epics expand with `l` and collapse with `h` to reveal phases. Rows show stored
status and ownership metadata, `✦` when a task has a pending TaskTriage decision, and
`▤` when the bead links a plan document. Linked issue chips use `○` for open, `●` for
closed, and `?` for a stale issue absent from the complete cached listing; stale or
drifted links are highlighted, and `+N` summarizes additional links. Closed beads are
loaded but hidden by the visible `-status:closed limit:<page_size>` default; press `f`
to edit or clear that query. Section headings report matched and total counts while a
filter is active.

`n` collects a standalone task for the selected project. Title, filing reason, size, and
task type are required. The reason is one or two sentences, at most 2000 characters, and
is stored separately from the title and description. `Ctrl+S` creates the bead and `Esc`
cancels. See [Creation Reason](reference/work-units/beads.md#creation-reason).

The pane supports the full bead workflow:

| Key                 | Action                                                                          |
| ------------------- | ------------------------------------------------------------------------------- |
| `j` / `k`           | Select the next / previous bead                                                 |
| `Enter`             | Open the complete bead detail in the preview reader                             |
| `f`                 | Edit the bead filter query                                                      |
| `Ctrl+J` / `Ctrl+K` | Load more matching beads / unload one page (rewrites `limit:`)                  |
| `l` / `h`           | Expand / collapse the selected epic                                             |
| `s`                 | Cycle the selected bead's status using the type-aware sequence below            |
| `z`                 | Snooze the selected task bead (or edit/cancel an existing snooze)               |
| `e`                 | Edit the bead's valid fields                                                    |
| `N`                 | Append a note; `@path` attaches a snapshot and `Ctrl+T` cycles its audience     |
| `n`                 | Create a task bead in the selected project (filing reason required)             |
| `c`                 | Close with a required reason and optional note, or reopen a closed bead         |
| `w`                 | Launch an epic or launchable task; phase work launches with its epic            |
| `E`                 | Open a linked external issue                                                    |
| `y`                 | Copy the bead's `@bead:` reference                                              |
| `% u`               | Copy a linked issue reference (copy mode)                                       |
| `b`                 | Enter issue-action prefix mode                                                  |
| `$`                 | Arm the [link rail](#contextual-artifact-links), e.g. to follow the linked plan |
| `R`                 | Open the [Refresh panel](reference/tui/agents-tab.md#refresh-panel)             |

`N` opens a modal for appending a note and leaves earlier notes in place. Add `@<path>`
to capture a file snapshot when you save with `Ctrl+S`: `Tab` completes paths, pasting a
single existing file path inserts an attachment reference, and `@@` inserts a literal
`@`. `Ctrl+T` cycles the attachment audience through automatic, private, and public.
Public asks you to confirm on save; policy can still reject the note and return you to
the editor. The bead detail lists each attachment's `🌐` or `🔒` chip from the stored
descriptor and leaves availability badges and thumbnails to the attachment viewer. See
[From the Beads pane](reference/work-units/bead-attachments.md#from-the-beads-pane).

When a bead has several issue links, `E`, `% u`, and the `b`-mode `v`, `e`, `s`, and `u`
actions first open a selector. In `b` prefix mode, press `v` to view the cached body,
`e` to edit supported title/body/label fields, `s` to close or reopen after
confirmation, `u` to copy the provider URL, `a` to attach an existing numeric issue, or
`c` to create and attach a new issue. Attach and create operate on the bead itself and
therefore do not select an existing link. Availability follows the active VCS provider's
capabilities. The detail reader shows each link's relation, state, labels, assignees,
author, update/comment metadata, and cached body. The info line reports linked,
remote-only, stale, and drifted counts, plus provider unavailability and per-project
errors, so tracker health remains visible without a separate Bugs pane.

Closing offers `done`, `canceled`, and `superseded` resolutions. A bead with unfinished
descendants is rejected unless the close modal's force option is enabled with a
non-`done` resolution; the modal previews those descendants first. Closing or launching
a task with a pending TaskTriage request settles that gate so the notification does not
outlive the decision. Mutation work runs as tracked procs and refreshes the pane after
completion.

The default `s` status action is type-aware:

```
task: open → ready → in_progress → closed → open
      claimed → ready
      snoozed → ready
other beads: open → in_progress → closed → open
```

The `s` action changes persisted status only; moving a task from `ready` to
`in_progress` does not itself launch a worker. Use `w`, the matching TaskTriage
notification, or `sase bead work <task-id>` to launch the work. The editor shows only
fields valid for the selected bead type, while dependencies remain read-only in the
detail panel. `s` only cycles a task _out_ of `snoozed` (back to `ready`, canceling the
snooze); entering `snoozed` needs `z`, since snoozing takes arguments (a wake time, and
optionally a `+1` target and a reason) that a blind status cycle cannot supply.

Press `z` on a task bead to open the snooze picker: presets for `4 hours`,
`Tomorrow morning`, `3 days`, and `1 week`, plus a custom duration field accepting the
same `"<duration> [+<N>]"` vocabulary as `sase bead snooze` (see
[Snoozing a Task Bead](reference/work-units/bead-triage.md#snoozing-a-task-bead)) and an
optional reason field. Pressing `z` on an already-snoozed task opens the same modal in
re-snooze mode, showing the current wake time and offering a cancel-snooze choice. A
snoozed row in the list shows the `snoozed` status glyph and a dim relative wake time.

When that worker appears on the Agents tab, its bead badge points directly to the task,
and its **SASE CONTEXT / BEAD** lane shows the task title and description, plus size
when one is stored, without trying to resolve an epic plan.

### Archive (Agents Tab)

Artifacts → Agent is retired: agent history lives in the Agents tab's **Archive** view.
Press `,a` to toggle between the Inbox and the Archive; the tab label reads `Agents ◷`
while the Archive is active. The Inbox holds undismissed agents, including completed
runs; dismissing an agent moves it to this machine's Archive. Selecting an archived run
shows its retained content in the decks (Main, Files, Tools, FINAL, Record) without
restoring it, marking it read, or starting another run.

The Archive's committed query always contains `in:archive`, shown as a chip, so `^`
history, saved slots, and
[`sase agent search`](reference/cli/agent.md#sase-agent-search) all agree on what is on
screen. Each view parks its own query, selection, folds, and deck state, and `,a` always
returns each view exactly as left. Pane-era saved slots and history were migrated once
to free `agents-live` slots with `in:archive` prepended.

Day banners group the list by default; `o` switches grouping between day, project,
outcome, and model. `j` / `k` move across rows, banners, containers, and `⋮ more` rows,
while `J` / `K` move between the Inbox pulse and the list. Selecting a row hydrates the
real decks from the retained bundle: the full prompt, the reply, diffs, tool calls, and
the Record deck's Lifecycle, Provenance, Relations, and Links cards.

The Jump panel shows the archived agent's relations, and the `linked:`, `relation:`, and
`artifact:` facets expose the same graph as query terms.

`Enter` opens the action chooser. Its ARCHIVE section lists Restore first:
`Restore to inbox`, `Restore N marked` when Archive marks exist, or
`Restore clan|session <name> (N members)` on a container. Marks take precedence over the
highlighted row. A container, collapsed or expanded and highlighted or marked, restores
every member that matches the current query, and the label's count is exactly the set
Restore acts on. Restore shows the existing agent in the Inbox again and starts no new
run.

Choose Restore with `r` **inside the chooser** to stay in the Archive. Successfully
restored rows dim and gain a `⌂ restored` suffix until the query changes or you leave
the Archive. A toast reports the outcome; mixed sets report restored, skipped, and
failed counts. The saved Inbox view keeps its selection, agent tab, folds, and jump
anchors. `Restore and show in inbox` (`s`, chooser only) switches to the Inbox when
exactly one agent is successfully restored; a larger restored set stays in the Archive
with a count summary. If the Inbox query hides the single restored agent, SASE replaces
it with an exact `name:"…"` query and saves the old query in history (`^`).

Fork (`F`, in the chooser and on the list) is offered for one named archived agent with
a recorded chat path or retained reply. It opens a prompt prefilled with that agent's
fork reference; submit the prompt to start a new run. Clan and session containers do not
offer fork. For an individual readable entry, the READ section offers Open chat in
`$EDITOR` (`e`), Copy `@agent` reference (`y`), and More copy targets (`%`). These also
work from the list. Opening chat does not restore the agent, but the editor opens the
file in its normal mode; SASE does not enforce read-only editing.

For a readable entry that cannot be restored, the chooser initially selects Open chat.
If its bundle cannot be read, the detail title reads
`Archive entry unreadable — Record only`, and the Record deck still shows the available
index facts. That entry cannot open the chooser unless other runs are marked for
restore.

Live Inbox actions stay in the Inbox. `x`, `X`, `s`, `S`, `w`, `W`, `A`, `R`, `n`, and
`U` toast that the key acts on inbox agents and name `,a` to get back. Agent-tab `[` /
`]` and the tab picker say agent tabs live in the Inbox; `N` says tribes do. List `s` is
that blocked save action; it is not the chooser's restore-and-show key.

| Key       | Action                                                             |
| --------- | ------------------------------------------------------------------ |
| `,a`      | Toggle between the Inbox and the Archive                           |
| `Enter`   | Open the chooser (Restore first; Open chat when restore is absent) |
| `j` / `k` | Select the next / previous archive row, banner, or `⋮ more` row    |
| `J` / `K` | Move between the Inbox pulse and the Archive list                  |
| `o`       | Archive grouping picker: day · project · outcome · model           |
| `l` / `h` | Expand / collapse a container row                                  |
| `m` / `u` | Mark / clear Archive rows (separate from Inbox marks)              |
| `y`       | Copy the `@agent:` reference                                       |
| `%`       | Open the **Copy as…** palette                                      |
| `e`       | Open the retained chat file in `$EDITOR`                           |
| `F`       | Open a fork prompt for a named run with chat metadata or content   |

### Document Provider Panes

Artifacts includes one document pane per configured artifact-reference provider. The
fixed tabs are Commits, Patches, Beads, and Files; provider-backed document tabs such as
Plans and Research appear between Beads and Files when an enabled project configures the
matching sidecar `ref:` policy. Persisted selections use stable ids such as `ref:plan`
and `ref:research`, so a missing provider falls back to Commits instead of crashing
startup. Each pane renders an icon before its label — the four fixed marks (`◉` Commits,
`⎇` Patches, `◈` Beads, `▤` Files) are built in, and a provider pane's mark comes from
its sidecar `ref.icon`. The active tab's icon takes that pane's accent color; inactive
icons render dim. A missing `ref.icon`, one that fails validation, or one wider than two
terminal cells uses the generic `◆` provider icon instead.

Plans is the built-in provider-backed document pane for the plans sidecar. It keeps the
existing plan actions: `A` and `X` approve or reject pending proposals. A plan's owning
bead (and a bead's linked plan) is an artifact link, so follow it from the
[link rail](#contextual-artifact-links) with `$`. Plans groups its list by **Kind**,
**Status**, or **Project** (`o` / `O`). Other document providers reuse the same list,
filter, detail, preview, copy, and refresh behavior from their declared properties and
detail fields, and group only when they declare `ref.grouping` (or `ref.pane.group_by`);
see
[Grouping declarations](contribute/artifacts-pane-contract.md#grouping-declarations).

### Commit Detail and Linked Plans

Press `Enter` on a Commits entry to open its full message and syntax-highlighted diff.
The modal uses `j` / `k` for line scrolling, `Ctrl+D` / `Ctrl+U` for half pages, `g` /
`G` for the ends, `y` to copy the full SHA, and `Esc` or `q` to close. When the current
result contains multiple commits, `Ctrl+N` / `Ctrl+P` move through them with wraparound.

The modal's header block carries a compact commit-time chip, right-aligned on the line
that also shows the diff path — an absolute stamp plus a relative age, such as
`Today 07:05:54 · 2h ago`. Today and yesterday show seconds; older commits show `HH:MM`
after their day label. Times are the commit's author time in the configured local
timezone. The chip is free on the Artifacts timeline, where the commit time is already
loaded; on the Agents tab, a commit whose stored metadata records no time has it looked
up from the VCS alongside the diff, so the chip appears once that load lands. Commits
made by SASE persist their author time in `commit_result.json` / `commit_results.json`,
so later views need no lookup at all. A commit whose time cannot be resolved simply
shows no chip.

Press `p` in the commit modal to load the last structured `SASE_PLAN` footer tag and
render its referenced local UTF-8 file as Markdown; press `p` again to return to the
cached diff. This is a local-only lookup: an absolute path is expanded and checked
directly, while a relative path is checked first in the commit repository, then in each
known project workspace and its plans store. sase's TUI does not clone or materialize a
missing store. A missing tag, invalid reference, unavailable path, non-file path, or
unreadable file produces a specific toast and leaves the commit visible. Moving to
another commit always returns the modal to commit mode.

### Preview Reader

Press `Enter` on a Beads entry, provider document, or Files row to open its full
contents in the preview reader. Prompt-normal-mode `K` opens the same reader for a
previewable macro, skill, or file. When sase's TUI knows a canonical artifact reference,
the title shows that logical reference beside the resolved local path.

The reader opens at its normal size when the content fits and grows toward a
near-full-screen maximum (a thin backdrop margin remains) for long or wide content.
Width follows the 95th-percentile line width, so one very long line does not force full
width. Switching views with `R` or `p` only ever grows the panel; resizing the terminal
recomputes it.

| Key                 | Action                                                     |
| ------------------- | ---------------------------------------------------------- |
| `j` / `k`           | Scroll down / up one line                                  |
| `Ctrl+D` / `Ctrl+U` | Scroll down / up half a page                               |
| `g` / `G`           | Jump to the top / bottom                                   |
| `y`                 | Copy the complete preview contents                         |
| `Y`                 | Copy the local source path, when available                 |
| `%`                 | Open the active Artifacts sub-tab's **Copy as…** palette   |
| `R`                 | Toggle Markdown previews between rendered and source views |
| `p`                 | Toggle the full macro properties view                      |
| `/`                 | Open source search (smartcase substring matching)          |
| `n` / `N`           | Jump to the next / previous match with wraparound          |
| `o`                 | Open the source path in `$EDITOR` (falling back to `nvim`) |
| `Z`                 | Hand the source path to the rich terminal artifact viewer  |
| `Esc`               | Cancel input, clear active search, then close the reader   |
| `q`                 | Close the reader                                           |

Path-only actions are omitted from the footer when the preview has no local source path;
invoking one still produces a specific warning instead of failing. Clipboard operations
run in the background and report when no clipboard tool is available. Plans open in
rendered Markdown by default when they fit the reader's bounded render budget; macros,
skills, files, and oversized documents open as source.

For a macro or skill preview with declared properties (inputs, tags, skill/snippet/
memory flags, local macros, or steps), a compact band appears above the source pane
showing its description, an inputs table, and a dim chips summary of everything else it
declares. `p` opens a full, scrollable properties view — the same projection
`sase macro show` renders — with the band hidden while that view is active; `p` again
restores whichever mode was showing before. A preview with no declared properties (a
bare-body macro, a plain file, a bead, and so on) shows no band, no `p` row in the
footer, and `p` emits a warning toast instead of switching views.

Search is commit-on-enter: `/` opens a one-line input prefilled with the last committed
query, and `Enter` highlights every matching source line before jumping to the first
match at or below the current viewport. Queries containing an uppercase character are
case-sensitive; other queries are case-insensitive. Starting search from rendered
Markdown switches to source view. `Esc` in the input cancels the edit, while `Esc` after
a committed search first clears the matches and only closes the reader on the next
press.

Prompt `K` on a supported image path (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) opens
the reader with an inline cell preview sized to the near-full-screen panel. It
re-renders on terminal resize. The footer shows
`Y path | % copy | Z viewer | esc close`, and `Z` opens the full-fidelity artifact
viewer. `y`, `/`, and `o` warn instead of acting on image previews.

### Files Pane

Files browses the artifact-file index that backs [`sase artifact list`](cli.md). The
pane is one of the four fixed Artifacts views: Commits, Patches, Beads, and Files. The
Agent pane is retired by default (`artifacts_agent_pane_retired`) and shows only with
the opt-out. Configured document-provider panes appear between Beads and Files in the
runtime tab strip. Rows are grouped by logical file identity, so repeated captures of
`@file:~/bob/gtd.md` or repeated `sase artifact create` rows for the same logical
artifact appear as one selectable row with versions.

Each row shows a view-mode glyph, the project, the producing agents, an origin badge,
the logical label, the latest selected version's timestamp, and the indexed size.

| Glyph | View mode  | Opens with                                                 |
| ----- | ---------- | ---------------------------------------------------------- |
| `▨`   | `image`    | The rich terminal viewer (`kitten icat`)                   |
| `▶`   | `video`    | The rich terminal viewer (`mpv`)                           |
| `▤`   | `pdf`      | The rich terminal viewer (PDF pages rendered to PNG)       |
| `▤`   | `markdown` | The [preview reader](#preview-reader), rendered by default |
| `•`   | `text`     | The [preview reader](#preview-reader), as source           |

The glyph comes from the same classifier that chooses the viewer, so it can never
disagree with what `Enter` actually opens. Origin badges distinguish files cited in a
prompt (`ref`), files registered explicitly with `sase artifact create` (`created`), and
automatic captures (`capture`).

The info line above the list summarizes the loaded snapshot as kind chips and origin
chips, where `documents` totals PDFs and Markdown. The index loads off the message pump
in two pages: a first bounded page paints immediately, then the full index replaces it,
and the status line reports both the loaded row count and any in-flight extension.

Selecting a row loads its detail panel off-thread. The detail header shows
`version i/n`, the durable `file:<id>` or logical `@file` reference, digest, capture
time, project, agent, origin, MIME type, and size. Markdown and text rows include a
bounded preview. `(`/`)` cycle the selected row's versions without moving to another
logical file; repeated captures with the same SHA-256 share one version and accumulate
provenance.

| Key                 | Action                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `j` / `k`           | Select the next / previous file, skipping day headings                                     |
| `Enter`             | View the file: preview reader for Markdown and text, rich viewer for media                 |
| `Z`                 | Hand the marked visible rows — or the selection — to the rich terminal viewer              |
| `E`                 | Open text in `$EDITOR` (falling back to `nvim`); open media with `xdg-open`                |
| `a`                 | Jump to the producing agent on the Agents tab, reviving it first when dismissed            |
| `f`                 | Edit the pane's filter query                                                               |
| `Ctrl+J` / `Ctrl+K` | Load more matching files / unload one page (rewrites `limit:`)                             |
| `z`                 | Cycle the kind filter through All and the stored kinds present in the snapshot             |
| `o` / `O`           | Cycle grouping (**Source**, **Kind**, **Project**) forward / backward                      |
| `(` / `)`           | Select previous / next version for the current logical file                                |
| `y`                 | Copy the row's `@file:<id>` reference                                                      |
| `Y`                 | Copy the row's anchored stored path                                                        |
| `m` / `u`           | Mark / unmark the selected file · clear this pane's marks                                  |
| `%`                 | Open the Files **Copy as…** palette                                                        |
| `R`                 | Refresh the index (through the [Refresh panel](reference/tui/agents-tab.md#refresh-panel)) |
| `p`                 | Change the shared Artifacts project scope (first-open seeds current project)               |

These are the default keymap values; the Files-pane actions retain their `files_*`
configuration names and are remappable under
[`ace.keymaps.app`](reference/config/ace-keymap-configuration.md#acekeymaps) as
`files_next`, `files_prev`, `files_view_selected`, `files_open_viewer`,
`files_open_external`, `files_open_agent`, `files_filters`, `files_cycle_kind`, and
`files_copy_path`. `y`/`R` are the shared `artifacts_copy_reference`/`refresh` actions
every Artifacts pane binds. `Ctrl+J` / `Ctrl+K` are the shared
`artifacts_load_more`/`artifacts_unload` actions. Version cycling uses the old
nested-files sub-tab keys. The pane also shares the navigation and jump keys described
in
[Navigation in Agent, Commits, Beads, Provider Documents, and Files](#navigation-in-agent-commits-beads-provider-documents-and-files).

`Y` copies the anchored stored path, except that PDF rows deliberately yield the live
Markdown source they were rendered from when the index recorded one. Relative index
paths are anchored to the producing workspace, so a copied path is always usable outside
the workspace that created it, and the completion toast says when the copied path no
longer exists. The palette previews that same preferred path, so what a PDF row shows is
what `%p` copies. `%` adds the rest of the Files-pane copy targets: contents, Markdown
link, source path, label, and metadata JSON, each of which also operates on the marked
set.

`a` resolves the producing agent from already-loaded live and dismissed agents by
artifact directory, then by raw name suffix, then by recorded agent name, always within
the row's own project. A file whose source workspace was recycled still opens and still
copies — only its `Source` path reports `missing`.

#### Filtering Files

Files keeps its committed query visible in a persistent filter row, the same idle chrome
Agent, Patches, Stitches, Beads, and Plans use. Press `f` or `/` to edit it. Filtering
is purely in-memory over the loaded snapshot, so a query narrows thousands of rows
without a re-query. Files accepts `id:`, `kind:`, `project:`, `agent:`, `workflow:`,
`origin:`, `since:`, `until:`, and host-owned `limit:`, plus free text matched against
the label, logical path, stored path, source path, digest, and artifact id. `id:` is the
pane's identity field: it matches a logical file id exactly and stays free-text
searchable too. Tokens from different facets combine with AND semantics, while
comma-separated or repeated values within `id:`, `kind:`, `project:`, `agent:`,
`workflow:`, and `origin:` combine with OR semantics. `kind:` accepts the stored kinds
`chat`, `plan`, `image`, `markdown`, `pdf`, and `file`; `origin:` accepts `ref`,
`created`, and `capture`; `since:` and `until:` accept `YYYY-MM-DD`, `YYYY-MM`,
`YYYYMM`, or a relative `Nd` / `Nw` / `Nm` offset and may each appear once.

`z` and the `kind:` token drive the same filter state: cycling with `z` closes an open
edit session and sets `kind:` to the next stored kind actually present in the snapshot,
wrapping back to All. A query listing several kinds is treated like All, so the next
press selects the first present kind. When a filter hides every row, the pane says so
and names the key that focuses the query row.

### Epic phase sizes across plan surfaces

sase's TUI uses the literal scope labels `xsmall`, `small`, `medium`, `large`, and
`xlarge`, with mint, sky, gold, rose, and violet chips whose text remains the primary
signal. Valid older plans and phase beads with an omitted size use the stable `small`
fallback, while an invalid authored value never produces a confident chip or count. The
Plans pane also uses that shared display fallback for a legacy standalone task with no
stored size; launch routing uses the same `@small` fallback.

| Surface                                                                  | Size contract                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agents author and lander                                                 | Shows every normalized authored size in roadmap order.                                                                                                                                                                                                                                                 |
| Agents phase worker                                                      | Shows only that worker's normalized authored size, preserving phase isolation.                                                                                                                                                                                                                         |
| Artifacts / Beads epic, phase, and task beads                            | Shows current persisted bead sizes in rows and details; the epic detail summarizes direct children in `xsmall`, `small`, `medium`, `large`, `xlarge` order. Standalone tasks appear in their own section. A legacy task with no stored size displays and launches through the shared `small` fallback. |
| Artifacts proposals, linked plans, and archives                          | Retains the authored `phases` property exactly once instead of adding a competing roadmap.                                                                                                                                                                                                             |
| Telegram epic review                                                     | Adds a validated textual size breakdown while retaining the detailed Properties card and source/PDF attachment.                                                                                                                                                                                        |
| Epic clan summary, `sase bead show`, and epic work preview               | Continues using persisted bead sizes, which these execution surfaces already exposed.                                                                                                                                                                                                                  |
| Raw approval, validation/schema, source/PDF, and mobile attachment paths | Remains a lossless generic/source view; authored phase metadata is preserved without a second summary.                                                                                                                                                                                                 |

## Keybindings: Artifacts / Patches

Default configurable actions are listed in the generated
[TUI keymaps reference](reference/tui/keymaps.md). This page keeps behavior details and
fixed widget keys.

### Navigation

| Key                     | Action                                                                      |
| ----------------------- | --------------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered artifact link, or open the complete links panel |
| `` ` ``                 | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))       |

> **Note:** `o` opens a direct grouping picker on the Agents tab. `o`/`O` cycle the L0
> grouping bucket forward / reverse on Artifacts panes that have a grouping mode (each
> surface keeps its own in-session mode). Beads has no grouping modes, and a provider
> document pane has them only when it declares `ref.grouping`, so the keys are a silent
> no-op on panes without modes; the same is true on the Services tab. The Artifacts
> open-externally verb moved to `E`; bang-mode `!o` still marks PR origin. See
> [PR Grouping and Folding](#pr-grouping-and-folding) and the Agents-tab
> [Grouping Modes](reference/tui/agents-tab-grouping.md#grouping-modes) below.

### PR Actions

| Key             | Action                                |
| --------------- | ------------------------------------- |
| `C` / `c1`-`c9` | Checkout PR (primary / workspace 1-9) |

### PR Grouping and Folding

The Patches sub-tab is always grouped — the renderer walks one of `BY_PROJECT`,
`BY_DATE`, or `BY_STATUS` and emits a banner row above each bucket. `BY_PROJECT` is the
startup default; `o` cycles `BY_PROJECT → BY_DATE → BY_STATUS` for the current session.

| Mode         | L0 buckets                                                                   | Notes                                                                                                                                                                                                                                                                                                       |
| ------------ | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BY_PROJECT` | Project name                                                                 | Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings. Singletons suppress their L1 banner.                                                                                                                                                                          |
| `BY_DATE`    | `Today` / `Yesterday` / `This Week` / `Earlier`                              | Bucket from the latest TIMESTAMPS entry. Today/Yesterday add 4-hour L1 windows; hourly L2 headings appear only inside 4-hour windows with 2+ PRs. This Week adds day headings; Earlier adds week headings plus `(no timestamp)`.                                                                            |
| `BY_STATUS`  | `Mailed` / `Ready` / `WIP` / `Draft` / `Submitted` / `Reverted` / `Archived` | Bucket from the literal `status` field; actionable buckets first (`Mailed` = awaiting response, `Ready` = next to mail), terminal states last. Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings inside each status bucket. Singletons suppress their L1 banner. |

In `BY_DATE` mode, PRs sort newest-first within each date bucket. `Today` and
`Yesterday` are grouped first by compact 4-hour windows (`8AM-12PM`); one-hour headings
(`09:00`) appear only when that 4-hour window contains at least two PRs. `This Week`
uses calendar-day subgroups; `Earlier` uses Monday-start week ranges. PRs without a
parseable TIMESTAMPS entry fall into `(no timestamp)` under `Earlier`.

The active grouping mode is shown in the Patches sub-tab's info-panel header as a
`[group: <label>]` badge.

Collapsed banner rows are first-class navigation stops: `j`/`k` step through them just
like Patch rows, and `'` jump-hints land on them too. After a fold change that hides the
focused PR, focus snaps to the deepest collapsed ancestor banner so the cursor always
sits on a row the user can see.

### Fold Mode (`z` prefix)

STITCHES, HOOKS, MENTORS, and TIMESTAMPS sections each cycle through three fold levels:

| Level              | Behavior                                                                           |
| ------------------ | ---------------------------------------------------------------------------------- |
| **Collapsed**      | Notes truncated to fit; multi-line body shown as `[+N lines]`; only latest drawers |
| **Expanded**       | Full notes; body shown in dimmed text; all CHAT/DIFF/PLAN drawers visible          |
| **Fully Expanded** | Everything visible including rejected proposals                                    |

The lowercase cycle keys (`z` `c`, `z` `h`, `z` `m`, `z` `t`) step through all three
levels in order. The uppercase toggle keys (`z` `C`, `z` `H`, `z` `M`, `z` `T`) skip the
intermediate **Expanded** state, jumping directly between **Collapsed** and **Fully
Expanded**.

When collapsed, a `[folded: CHAT + DIFF + PLAN + N proposals]` indicator appears on
STITCHES entries with hidden content. The indicator width is pre-calculated so that note
truncation accounts for it. TIMESTAMPS shows a `[folded: N]` indicator inline with the
header and displays the most recent timestamp entry when collapsed, giving a quick view
of the last lifecycle event.

The DELTAS section uses the same three levels with its own meaning. When **collapsed**,
the section renders a one-line file and line-count summary such as
`DELTAS:  +3 (+428) ~6 (+91 ~37 -14) -1 (-22) (10 files)`. When **expanded**, the
alphabetical entry list is shown with colored glyphs (green `+`, gold `~`, red `-`);
**fully expanded** adds inline line-count tokens to each entry. Binary files display
`binary`; zero-count entries display `0 lines`. `z` `D` jumps between the summary and
the full list. The section is omitted entirely when the Patch has no deltas.

### Workflows and Agents

| Key        | Action                                             |
| ---------- | -------------------------------------------------- |
| `,<space>` | Run an agent from the current PR (skips selection) |

If sase's TUI cannot detect a workspace provider for the selected Patch or agent, the
quick-launch actions show an error toast instead of opening a prompt with a broken VCS
prefix.

### Bang Mode (`!` prefix)

`!!` ends in a **Run Command** picker over previously run background commands: type to
filter the history or enter a new command, move with `Ctrl+N` / `Ctrl+P` or the arrow
keys, press `Enter` to run it, and `Esc` to cancel. `,!` skips the project and uses the
current PR's project.

A background command is a **oneshot service proc**: a durable proc-store row with a
recorded exit code, a store-owned log, and a stable `#1`–`#9` index, shown in the
Services tab's `── oneshots ──` section. It runs outside the TUI and the service host,
so quitting or restarting either does not kill it, and a rerun (`r`) works after a TUI
restart. At most nine oneshots can be _running_ at once; finished commands never block a
new one (the oldest finished index is reused once all nine are taken).
`sase service proc run` submits through the same path.

### Hook History Modal

Type `.` into the `F` edit-hooks input to open the hook history modal, which lists
previously added hook commands:

| Key         | Action                 |
| ----------- | ---------------------- |
| `Esc` / `q` | Cancel and close modal |

The modal supports live filtering as you type in the search box and displays last-used
timestamps for each hook.

### Leader Mode (`,` prefix)

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

The `,h` shortcut opens a home-context prompt directly. Project and PR launch pickers
use lifecycle-aware discovery: project entries, including `home` when it appears in
picker lists, must have enabled and launchable ProjectSpecs; PR choices come from
enabled ProjectSpecs. Disabled projects do not appear in normal launch pickers until
they are enabled with `sase project enable <project>`. You can also type a known-project
VCS ref explicitly; launch preparation treats that as intent to resume work and
re-enables the project before claiming a workspace. When the current project appears in
the list, the `+` picker highlights that row on mount; typing in the filter box still
resets the highlight to the first match.

Project launch pickers also support `Ctrl+D` for cleanup of empty project entries. This
deletes only the highlighted project's active/archive ProjectSpec files, refuses entries
whose ProjectSpec files still contain Patches, and does not delete workspace checkouts
or other SASE state. For lifecycle changes, bulk operations, ProjectSpec editing, or
deleting the whole SASE project directory, use the **Projects** tab of the SASE Admin
Center (press `#`).

The repeat binding is the leader prefix followed by the configured `repeat_last` key.
With the defaults both are comma, so the sequence is `,,`; if the leader prefix is
changed but `repeat_last` is not, the second key remains comma. Repeat re-dispatches the
last recognized leader subkey against the current tab and selection. If no leader
command has been run yet, sase's TUI shows a toast and does nothing.

> **Note:** `,x` (kill & edit) and `,X` (kill & edit last launched agent) are only
> available on the Agents tab — see [Agents Tab Leader Mode](#leader-mode-prefix_1).

### Mentor Review Modal

Press `,C` to open the Mentor Review modal, which lets you navigate mentor comments,
accept or reject suggestions, and apply accepted changes. See
[Mentors](reference/automation/mentors.md) for the full mentor system reference.

| Key         | Action      |
| ----------- | ----------- |
| `Esc` / `q` | Close modal |

### Copy Mode (`%` prefix)

Press `%` to open the **Copy as…** palette for the selected Patch. Select a row with the
mouse, arrows or `j`/`k` and `Enter`, or complete any configured two-key accelerator
directly. `q`/`Esc` cancels; configured target keys take precedence if rebound to `j`,
`k`, or `q`.

## Keybindings: Agents Tab

Default configurable actions are listed in the generated
[TUI keymaps reference](reference/tui/keymaps.md). This page keeps behavior details and
fixed widget keys.

<a id="machines"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#machines).
<a id="agent-tabs"></a> Moved to [Agents tab](reference/tui/agents-tab.md#agent-tabs).
<a id="navigation-1"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#navigation-1). <a id="agent-actions"></a>
<a id="x-how-a-kill-is-carried-out"></a> <a id="enter-act-on-an-agent"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#agent-actions).
<a id="forking-agents-and-groups"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#forking-agents-and-groups).
<a id="clan-and-session-detail-panels"></a> Moved to
[Agents tab panels](reference/tui/agents-tab-panels.md#clan-and-session-detail-panels).
<a id="refresh-panel"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#refresh-panel).
<a id="sase-agent-neighbors-section"></a> Moved to
[Agents tab panels](reference/tui/agents-tab-panels.md#sase-agent-neighbors-section).
<a id="opened-repository-context"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#opened-repository-context).
<a id="wait-modal"></a> Moved to [Agents tab](reference/tui/agents-tab.md#wait-modal).
<a id="vcs-tag-resolution-in-forkwait"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#vcs-tag-resolution-in-forkwait).
<a id="workflow-visibility"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#workflow-visibility).
<a id="agent-artifacts"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#agent-artifacts).
<a id="tribe-side-panels"></a> Moved to
[Agents tab panels](reference/tui/agents-tab-panels.md#tribe-side-panels).
<a id="group-banners-and-folding"></a> Moved to
[Agents tab grouping](reference/tui/agents-tab-grouping.md#group-banners-and-folding).
<a id="grouping-modes"></a> Moved to
[Agents tab grouping](reference/tui/agents-tab-grouping.md#grouping-modes).
<a id="agent-row-glyphs"></a> Moved to
[Agent row glyphs](reference/tui/agent-row-glyphs.md#agent-row-glyphs-1).
<a id="agent-search"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#agent-search).
<a id="leader-mode-prefix-1"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#leader-mode-prefix-1).
<a id="agents-tab-reproduction-bundles"></a> Moved to
[Agents tab](reference/tui/agents-tab.md#agents-tab-reproduction-bundles).
<a id="bang-mode-prefix-1"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#bang-mode-prefix-1).
<a id="copy-mode-prefix-1"></a> Moved to
[Agents tab search and modes](reference/tui/agents-tab-modes.md#copy-mode-prefix-1).

## Keybindings: Services Tab

Default configurable actions are listed in the generated
[TUI keymaps reference](reference/tui/keymaps.md). This page keeps behavior details and
fixed widget keys.

The visible tab is **Services**. Its sidebar is four stacked panels. The top **Service
Procs** panel holds every service proc assembled from built-in, plugin, user, and
machine-overlay configuration — daemon rows plus background commands (oneshot service
procs) in a separate `── oneshots ──` section below the daemon procs. Below it, one
panel per routine declaring source holds that source's routines with their job rows
nested under each parent: **User Routines**, then **Plugin Routines**, then **Builtin
Routines**. Source means the first config layer that declared the routine, not the layer
that last changed one of its fields — a builtin routine with a user interval override
stays Builtin, and jobs always render in their parent routine's panel. Each panel border
title carries at-a-glance metadata (counts, status chips, and badges such as hidden
oneshots or a non-running scheduler). `J` jumps to the first row of the next panel and
`K` to the last row of the previous panel, wrapping around and skipping empty panels;
`Ctrl+O` returns to where you jumped from. `j` / `k` cross panel boundaries on the
underlying global list without selecting chrome. Service proc rows show their lifecycle,
enablement provenance, restart state, and bounded output. The dashboard status line
reports the service host state (`Host: <state>`). Project-local `sase.yml` service
entries are intentionally ignored.

Builtin routine rows start folded on first sight so the dense builtin list stays calm; a
folded row still carries its jobs' health as a red `!N` badge (failed, timed-out, or
missing-script jobs, counted from the same cached snapshots as the panel title). Folding
applies only once those snapshots have arrived, so a header-only pre-load never hides
rows behind a misleading fold. `h` / `l` fold and expand the focused routine, and an
explicit fold persists for the session. `ace.services.fold_builtin_routines` (default
`true`) controls the first-sight behavior permanently.

Once service status has loaded, the info panel leads with a host clause:
`Services · host ● running 4d · sase.service` while the host runs (uptime in its largest
unit when known, then the installed native service unit or `detached`),
`Services · host ○ starting` while the host is still starting (not a failure),
`Services · host ○ stale · press !x to start` when the heartbeat is stale, or
`Services · host ○ stopped · press !x to start` when the host is down. A host config
error renders inline (`! <error>`), and an unreadable snapshot renders its short reason
in the header. Disabled rows carry an inline provenance chip (`disabled here` for a
local override, `disabled by <layer>` otherwise), unavailable rows show
`unavailable: <reason>`, and other non-running rows carry the core's human summary (for
example `crash-looping (3)`) plus the restart count (`· 5r`) whatever the state.

On a selected top-level service proc, `x` starts or stops it, `r` restarts it, and `!e`
enables or disables it on this machine. Those actions are no-ops when no service proc is
selected; in particular, `x` does not toggle the host from a routine or job row in any
of the routine panels. Use `!x` to start or stop the service host itself. The `SVC`
footer pill shows the running/desired service-proc count (`N/M`), or a red `!` when the
host or a service proc is unhealthy (see
[Service Health Pill](reference/tui/agent-statuses.md#service-health-pill)). The
right-hand panel shows the selected proc's effective command, current and desired state,
restart policy, dependencies, last exit, restart decision reason, stop provenance, any
pending start/restart request, and output tail, plus the host config error when one is
set. The description sits in the sticky [description panel](#description-panel) above
it.

The canonical tab id is `services` (`axe` is still accepted as a legacy alias, for
example `sase tui -t axe`). Configuration keys such as `ace.axe_description_expanded`
and many internal row names keep the historical `axe` spelling, which is why the
detailed scheduler reference below still uses “Axe.”

### Sidebar Row Taxonomy

The Services sidebar renders four row types across its four panels so the operational
tree reads at a glance:

- **Service proc** rows live in the Service Procs panel with a solid left accent bar
  (`▌`) in the service teal, a `[*]` / `[!]` / `[~]` / `[?]` / `[-]` / `[·]` status
  marker, the proc name, and an optional state chip (restart count, disablement
  provenance, or the core's human summary).
- **Routine** rows live in their declaring-source panel (**User**, **Plugin**, or
  **Builtin Routines**) as top-level sections with a solid left accent bar (`▌`) in the
  routine hue, a `[*]` / `[!]` / `[·]` running/error/idle marker, the routine name, an
  optional overrun roll-up (`⚠N`), a red health badge (`!N`) counting failed, timed-out,
  or missing-script jobs even when the row is folded, and an optional compact `Nc / Ne`
  cycles/errors chip at the end.
- **Job** rows are child rows indented under their parent with a `  └─` tree connector,
  a per-run status icon (`✓` success, `!` failure/timeout, `?` missing script, `●`
  running, `*` agent-launched, `·` no runs), and the job name in a dim-gold child hue.
  Disabled jobs remain visible with a quiet `disabled` chip but cannot be run manually.
- **Oneshot** rows (background commands run via `!!`) live in the Service Procs panel
  below the daemon procs under a dim `── oneshots ──` divider when both groups are
  present. Each row leads with a state glyph (`▷` running, `✓` exit 0, `✗` failed or
  killed), a muted `#N` index, and the command, and ends with a chip carrying the
  recorded exit code and age (for example `exit 0 · 4m ago`), so they cannot be mistaken
  for scheduled AXE work. Commands started before oneshots existed remain readable from
  their old slot directories (no exit code) until those directories age out.

### Description Panel

The right-hand dashboard keeps the selected service proc, routine, or job description in
a dedicated panel between the status line and scrolling output. Every row of the panel
carries a solid left accent gutter (`▌ `) in the row's own hue — service teal for
service procs, routine gold and job copper otherwise — so the block reads as a
blockquote and stays visually distinct from the output pane below. Generated `for_each`
job instances also show their target key on the summary row. The panel stays fixed while
output scrolls and disappears for background-command and empty Services views. It shares
one session state across the Services tab: `d` on a service proc row also collapses
routine and job panels, and the reverse is true too. A service proc with no configured
description shows the dim-italic `No description configured` fallback, while a proc
missing from the snapshot hides the panel entirely. Oneshot rows get no panel.

The panel has two states, and `d` toggles between them for the rest of the session. The
summary row ends with a `▸ d` / `▾ d` disclosure hint whenever there is a body to reveal
and the row has room for it:

Collapsed — one row, ellipsized at the pane width:

```
▌ Complete finished hooks and start stale ones, with zombie detection            ▸ d
```

Expanded — the summary, a blank gutter row, and the reflowed body:

```
▌ Complete finished hooks and start stale ones, with zombie detection            ▾ d
▌
▌ Scans every Patch matching the axe query, completes hooks whose runner exited, and
▌ starts the next stale hook when a runner slot is free.
▌
▌ • Honors max_hook_runners; a full slot table defers work to the next tick rather than
▌   queueing.
▌ • Hooks still running past zombie_timeout_seconds are marked ZOMBIE and stop holding a slot.
```

The body is reflowed rather than replayed: blank lines separate blocks, a block whose
first line starts with `-`, `*`, or `•` renders as a hanging-indent bullet list, and
every other block is joined into one paragraph and re-wrapped to the current pane width.
See
[Description Grammar](reference/automation/scheduler-description-grammar.md#description-grammar)
for the authored form.

`ace.axe_description_expanded` (default `true`) sets the state each `sase tui` session
starts in. `d` flips an in-memory session state and repaints from cached snapshot data —
it never reloads config, reads disk, or writes the toggle back.

An expanded panel never crowds out the job output it exists to explain. The dashboard
budgets `max(3, min(16, floor(pane_height * 0.45)))` rows for the panel, falling back to
10 rows before its height is known. If the rendered block exceeds that budget, the last
row becomes a dim `… +N more · e` marker on routine and job rows — service proc rows
read `… +N more` with no `· e`, because `e` does nothing there: nothing is silently
dropped, and `e` opens the AXE entry editor, whose first field is the full description
in a multi-line text area.

Because `d` belongs to the Services tab, `show_diff` is scoped to the Patches sub-tab.
Pressing `d` outside Patches no longer opens a diff for an unrelated Patch.

### Dynamic Sidebar Width and No-Wrap Rows

Every sidebar row is rendered as single-line Rich `Text` with `no_wrap=True` and
`overflow="ellipsis"`. After each refresh each panel computes its widest formatted row
and its border title, and the widest of the visible panels decides the sidebar width:
the AXE container resizes between a 35-cell minimum and an 80-cell maximum, clamped
further so the right-hand dashboard always keeps at least 40 cells. On terminals too
narrow to fit a label even at the clamped width, the row ellipsizes rather than wrapping
onto a second line, and a long panel title truncates with Textual's border-title
ellipsis.

### Controlled-Output Highlighting and ANSI Fallback

Output in the dashboard right panel uses a semantic highlighter for sources whose shape
is controlled by sase, and falls back to ANSI rendering for everything else:

- **Routine aggregate logs** (`[YYYY-MM-DD HH:MM:SS] [routine] message`) get timestamp,
  routine name, status words (`success`, `failure`, `timeout`, `running`, `error`, …),
  PIDs, durations, exit codes, and counts colored by severity and consistent with the
  sidebar taxonomy.
- **Controlled job output** — runner lifecycle lines such as
  `Launched proposal 1 as <name> (PID <pid>)` use the same status-word, PID, duration,
  and count highlighting as other routine messages.
- **External job scripts** and **background command output** are arbitrary text and stay
  on the ANSI fallback (`Text.from_ansi`) with the existing capping and tail-biased
  caching behavior.

Render cache slots are keyed on `(source_id, source_type)` so the semantic and ANSI
paths cannot collide for the same numerical identity.

### Job Result Documents

Selecting a recorded job run composes three sections inside the existing scroll region:

1. **RESULT** is always present and is derived entirely from the cached run entry. It
   includes the status, structured summary and reason, counters, proposal and launch
   rosters, evidence, dry-run/source markers, and any error or traceback.
2. A job-authored structured **report** follows when the result document supplies one.
   Semantic tones map to the AXE palette, tables elide cells at wide widths and stack at
   widths below 60 cells, and all job strings are rendered literally rather than parsed
   as Rich markup or ANSI.
3. **OUTPUT** contains the existing ANSI-rendered log tail and retains the waiting,
   failure, reason, and no-output fallbacks for runs with an empty log.

The card and report are cached by run identity, lifecycle state, completion timestamp,
and rendered width. They paint only from the in-memory job snapshot; navigation does not
read, stat, or glob the run files. Auto-scroll continues to follow active `running` and
`launched` output, but terminal runs open at the RESULT card so the report is not
scrolled off screen on selection.

### Navigation

| Key                     | Action                                                                 |
| ----------------------- | ---------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered job link, or open the complete links panel |
| `` ` ``                 | Jump to an entry across all tabs                                       |

### Commands

The `a` flow discovers installed `sase_job_*` executables and also accepts a custom
executable. Both add and edit open a single-page property sheet showing every schema
field, including unset and inherited fields. The active row's detail dock shows its
schema help plus effective, target-layer, and inherited values. Edits remain sparse: an
inherited field is not copied into the selected writable scope unless you touch it.
Compound and advanced fields expand in place as raw YAML, with inherit/reset available
for removing a target-layer override.

Editing a generated job row edits its immutable base job and warns that every generated
instance is affected. Before writing, the panel shows an exact effective before/after
preview plus a source-file diff. When the scheduler is running, the preview makes
restart explicit: save and restart the scheduler to reconcile it immediately, or save
only and leave the current scheduler configuration active until the next restart. `E`
remains reserved for opening recorded job output.

#### AXE Property Sheet

The panel opens existing entries in browse mode, with no editor focused, so property
navigation works immediately. A new entry opens in cell mode on its first required
property.

| Browse key            | Action                                                         |
| --------------------- | -------------------------------------------------------------- |
| `j` / `k` / `↑` / `↓` | Move to the next / previous property                           |
| `g` / `G`             | Move to the first / last property                              |
| `Enter` / `i`         | Edit the active value in place; toggle a boolean               |
| `Space`               | Toggle a boolean or cycle an enum forward                      |
| `h` / `l` / `←` / `→` | Cycle an enum backward / forward                               |
| `Ctrl+R`              | Mark inherit/reset; press again to restore the original value  |
| `1`…`9` / `Ctrl+T`    | Select a numbered writable scope / cycle scopes                |
| `Ctrl+S`              | Build the validation and source-diff preview                   |
| `Ctrl+L`              | Reload after a stale-write conflict while preserving the draft |
| `q`                   | Close the panel directly and discard unsaved edits             |
| `Esc`                 | Close the panel                                                |

| Cell key                       | Action                                                             |
| ------------------------------ | ------------------------------------------------------------------ |
| `Enter`                        | Commit a single-line value; insert a newline in a multi-line value |
| `Esc`                          | Leave INSERT for NORMAL, then commit and return to browse mode     |
| `q`                            | Type `q` in INSERT; close the panel directly from NORMAL mode      |
| `Tab` / `Shift+Tab`            | Commit and edit the next / previous property                       |
| Vim keys                       | Edit through the standard `VimTextArea` layer                      |
| `Ctrl+S` / `Ctrl+R` / `Ctrl+T` | Preview, inherit/reset, or cycle scope while the editor is focused |

| Preview key                     | Action                                            |
| ------------------------------- | ------------------------------------------------- |
| `↑` / `↓` / `Ctrl+D` / `Ctrl+U` | Scroll by line or page                            |
| `g` / `G`                       | Scroll to the top / bottom                        |
| `Enter`                         | Save, restarting the scheduler when it is running |
| `Ctrl+O`                        | Save without restarting the scheduler             |
| `q`                             | Close the panel directly                          |
| `Esc`                           | Return to the property sheet                      |

### Leader Mode (`,` prefix)

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

### Bang Mode (`!` prefix)

### Copy Mode (`%` prefix)

Press `%` to open the **Copy as…** palette for the selected AXE row. Choose with the
mouse, arrows or `j`/`k` plus `Enter`, or use a configured direct accelerator. `q`/`Esc`
cancels, with configured target keys taking precedence.

### Services Control

## Query System

### Editing Queries

`/` is the app-level query key on every Artifacts pane and on the top-level Agents tab.
Every pane with a filter session keeps a persistent idle filter row; `/` (or the local
`f`) focuses it for editing. On Agents, `/` (or `f`) opens the auto-hiding filter bar,
and `,/` starts forward inline deck search. Help is the app-level `?` on every tab.

| Context            | Default query key  |
| ------------------ | ------------------ |
| Patches            | `/` (or local `f`) |
| Stitches           | `/` (or local `f`) |
| Beads              | `/` (or local `f`) |
| Provider documents | `/` (or local `f`) |
| Files              | `/` (or local `f`) |
| Agents tab query   | `/` or `f`         |

The Services tab has no query editor. Its `?` help modal and the command palette both
still offer "Edit search query" there, but the action currently does nothing on
Services; use the tab's own filtering and navigation keys instead.

To save a query, prefix with `#`:

- `#3 "myproject"` -- save to slot 3
- `# "myproject"` -- save to next available slot
- `#3` (no query) -- delete slot 3

On Patches and the top-level Agents tab, these commands run inside the inline filter and
leave both the active query and editor session in place.

On first open, when `ace.current_project.seed_filters` is on and the Patches query
carries no `project:` / `+name` term of any polarity or depth, sase's TUI appends a
visible `project:<name>` token for the current project (the configured project name,
never the ProjectSpec key). An explicit term wins, including `NOT project:…` and a term
nested inside parentheses. The seeded token is session-only: it is not written to
`last_query.txt`. Press `p` and choose **All projects** to remove it. Submitting the
query from the filter bar keeps the token as yours and persists it.

### Saved Queries

Saved-query slots are kept separately for each Artifacts pane. On the Artifacts tab,
press `0` followed by a slot digit (`1`-`9`, then `0` again for slot 0) to load that
slot from the active pane's saved queries -- e.g. `02` loads slot 2. The active pane is
not switched; a slot saved for a different query dialect is refused with an error
instead of being applied. `Esc` or any other non-digit key after `0` cancels without
changing the query. Bare digits still select the corresponding visible Artifacts
sub-tab; the saved-query slot keys live behind the `0` prefix so the two never collide.

Press `*` on an Artifacts pane that supports saved queries to open the saved-query
chooser instead. Press a populated slot (`1`–`9`, then `0`), move with `j`/`k` or the
arrow keys and press `Enter`, or click a row. `q`/`Esc` closes the chooser without
changing the query. The chooser shows the saved query text and marks the active query;
an empty chooser also repeats the save syntax. The chooser is unavailable from the
Agents and Services tabs.

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on every Artifacts sub-tab whose pane contract enables
`query_history`, including provider-backed document panes, and inside the top-level
Agents tab filter bar. Each pane has its own durable previous/next stack, and Help shows
the active pane's stack with the configured previous/next key labels.

See [`docs/reference/query-language.md`](reference/query-language.md) for the full query
syntax reference, including boolean expressions, status shorthands, property filters,
and searchable fields.

## Config Flags pane

Open **SASE Admin Center** with `#`, then Config > **02 Flags**. The pane is the
keyboard-first control surface for every code-owned SASE feature flag. It shows
effective state, kind, default, provenance, saved machine preference, description,
removal bead, and removal horizon; it does not edit portable configuration files.

Config's nested catalog is:

```text
01 All · 02 Flags · 03 Holds · 04 Launch · 05 Memory · 06 Snippets · 07 Macros
```

`sase flag enable` and `sase flag disable` remain available alongside the pane as the
automation surface.

The pane uses the Admin Center list/detail layout: a header with registered/on/saved
counts, a flag rail, a scrollable detail card, a hidden inline filter, and a one-line
footer. Effective on/off and source are shown separately from saved on/off. When
environment or root CLI `-f`/`-F` still wins, a yellow “forced for this process” warning
explains that saving restarts sase's TUI and the service host but will not take effect
until that override is removed.

| Key              | Action                                                                             |
| ---------------- | ---------------------------------------------------------------------------------- |
| `/`              | Open an inline filter over key, description, kind, effective state, and provenance |
| `Esc`            | Close/clear the filter before closing Admin Center                                 |
| `j` / `k`        | Move the rail; arrows, Home/End, and mouse clicks work the same way                |
| `q`              | Close Admin Center                                                                 |
| `Enter`/`Space`  | Open a cancel-first confirmation (`OFF -> ON` or `ON -> OFF`)                      |
| `r`              | Reload the catalog                                                                 |
| `0` then `1`–`7` | Jump to a numbered Config child                                                    |

Confirmation is cancel-first. It names the flag, the current-to-target state, the saved
state path, any shadowing source, and that **sase's TUI and service host restart after
TUI tasks and installation changes finish**. Confirming writes only the machine-state
file, waits up to 60 seconds for TUI-local work and installation mutations, then
performs one controlled sase's TUI+service-host restart. Independent commands keep
running. Durable operations started from this TUI still finish their result handling
first, within the same 60-second wait. A restart failure does not roll back the saved
preference.

See [feature flags](reference/config/feature-flags.md#featureflags) for precedence, the
state file, and the CLI contract.

## Global Keybindings

Default configurable actions are listed in the generated
[TUI keymaps reference](reference/tui/keymaps.md). This page keeps behavior details and
fixed widget keys.

These work on all tabs:

| Key                     | Action                                                                        |
| ----------------------- | ----------------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered contextual artifact link, or open the links panel |

The generic **Open SASE Admin Center** action and the first `#` always open a
lightweight landing page without mounting a working pane. Press `#` again while home is
visible to resume the last section that was successfully active. With no prior visit,
the repeated key stays on home and loads nothing. Inside a working section, the same key
takes on a second meaning: it jumps to the section you were in immediately before the
current one, and pressing it again toggles back — exactly two sections remembered, like
a two-slot alternate. A color-coded, clickable footer along the bottom of the working
section names the jump target (or explains that none exists yet). The numbered strip
remains clickable: `1` Config, `2` Logs, `3` Machines, `4` Procs, `5` Projects, `6`
Statistics, `7` Tools, and `8` Updates. `Tab` enters Config, and `Shift+Tab` enters
Updates. Each working pane and its data are loaded only on first entry, then cached
while the modal remains open. Command-palette actions such as **Open logs panel**,
**Open procs panel**, and **Open statistics**, plus update shortcuts and indicators,
enter their requested pane directly and make a successful entry the next resume target.
Closing from home does not clear an older target.

Both the top-level resume target and the alternate are persisted machine-locally and
survive across sase's TUI process restarts. Within one running sase's TUI process,
closing and reopening Admin Center also remembers each selectable pane's last logical
entry by stable identity, plus the minimal scope or sub-tab needed to show it again.
Filters, marks, scroll position, loaded data, pane instances, Statistics controls, and
other pane-local state still end with the modal. If `ace.keymaps.app.open_config_center`
is rebound, repeat that configured key instead; the footer and landing page display the
effective binding and destination.

Inside every working section, `'` is an Admin Center-wide entry-jump key: it paints
adaptive hints over that section's selectable rows using the same hint alphabet
described under
[Navigation in Agent, Commits, Beads, Provider Documents, and Files](#navigation-in-agent-commits-beads-provider-documents-and-files),
a hint character moves the selection there, `'` again returns to the previous position
(or the first hint with an empty back stack), and `Esc` cancels. Each working section's
own keybindings table names its jump targets; two are deliberate exceptions. The
Statistics tab has no row cursor, so `'` there arms the same numbered-view selection the
`0` prefix already arms, using the visible strip numbers as hints. Config's nested
catalog is ordered **01 All · 02 Flags · 03 Holds · 04 Launch · 05 Memory · 06 Snippets
· 07 Macros**; `0` then the matching digits selects those children, while bare digits
continue to belong to the active child or the Admin Center's top-level tabs. The Updates
tab's single merged list jumps normally across every section — SASE, Plugins, and Agent
CLIs alike.

### Quit / Restart Menu

Pressing `Q` opens the **quit / restart menu**. When this TUI instance has in-process
work, the menu warns inline (`N TUI tasks will be interrupted`) and it offers three
actions:

- `1` / `s` — quit sase's TUI and stop the `scheduler` service proc (best effort: the
  TUI still quits if the stop fails); the service host and its other service procs keep
  running
- `2` / `r` — restart the TUI, leaving the service host running
- `3` / `a` — restart the TUI and restart the service host

Press `esc` (or `q`) to cancel and return to the TUI.

Durable procs, `!` background commands, monitor turns, and service procs survive
quitting and restarting; the menu says nothing about them because they keep running.

A plain `q` quits sase's TUI directly when nothing would be interrupted. Otherwise `q`
shows a y/n confirmation (default No) listing the in-process TUI work that would be
lost; confirming quits, declining (or `esc`/`q`) stays in the TUI.

An unsent agent prompt does not, by itself, ask you to confirm. After any required
confirmation — and immediately when none is required — plain `q` and menu quit (`1` /
`s`) write that prompt to Stash before exiting. The save is one Stash row: every
non-empty pane, in order, or the frontmatter alone when every pane is empty but
frontmatter is present. Plan Feedback and Coder Prompt bars are not saved. If the write
fails, the exit stops, the TUI stays open, and the error is
`Failed to stash prompt draft — staying so no text is lost`. Choosing `1` / `s` also
leaves the scheduler running when that save fails.

Restart (`2` / `r`, or `3` / `a`) tries the same save. When it succeeds, the TUI says
`Prompt draft stashed; press @ to restore after restart`. When it fails, the restart
still exits and the draft is not written.

A submitted prompt that is still waiting to launch does not, by itself, ask you to
confirm. The scheduler batches in the next paragraph are separate: they are chop
launches that have not all been started. When a quit or restart actually exits, each
waiting prompt is recorded in prompt history as cancelled and copied to Stash so `@` can
bring the Stash copy back. The exit still completes if that copy fails or does not
finish within 3 seconds. When a confirmation is shown for other in-process work, its
summary adds `Your unsent prompt draft will be stashed` when a draft is open, and a
count such as `1 pending launch will be stashed for @` when prompts are waiting.
Declining the confirmation writes nothing.

Options `1` and `3` also check for in-flight scheduler launch batches (a chop run that
has proposed launches but has not launched them all yet). When quitting would drop the
remaining launches — or when in-process TUI work would be lost — a y/n confirmation
(default No) lists exactly what would be lost. Option `2` confirms only for in-process
TUI work. Declining returns to the TUI without exiting or stopping anything; when
nothing would be lost, `q` and all three `Q` options behave exactly as before with no
extra prompt.

## Command Palette

Press `;` from any tab to open the **Command Palette** — a context-aware modal listing
every keymapped action that is currently runnable. The palette is the discovery surface
for the TUI: rather than memorizing every chord, you can search by command label, key
sequence (e.g. `%n`, `,A`, `zc`), category, or alias.

**Behavior:**

- Only commands applicable to the current tab and selected entry are shown by default.
  For example, PR diff appears only when a PR is selected; service start/stop appears
  only on the Services tab; agent-specific actions appear only when an agent row (not a
  group banner) is focused.
- Each row shows the keybinding, the command label, and a category badge such as
  `Navigation`, `PR Actions`, `Agent Actions`, `Copy`, or `Leader`.
- A title-bar badge (`Agents`, `Artifacts`, or `Services`) reflects the current tab.
- Typing `:` into an empty filter hops to the [Command Line](#command-line).
- When the filter has no match, a fallback row offers `Run `sase
  <query>` in Command Line`, which opens the Command Line pre-filled with the filter
  text (without running it).

**Keybindings inside the palette:**

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `Type`              | Filter commands (case-insensitive substring) |
| `:` on empty filter | Hop to the Command Line                      |
| `↑` / `↓`           | Move highlight                               |
| `Ctrl+P` / `Ctrl+N` | Move highlight                               |
| `Enter`             | Run the highlighted command                  |
| `Esc`               | Close without running anything               |

The palette delegates execution to the same handlers that the keybindings use, so
behavior matches pressing the chord directly. Selecting a built-in mode subcommand (e.g.
`%n` to copy an agent name) runs the action without forcing you through the transient
prefix mode. Custom modes defined in `sase.yml` are also represented per-command.

The `;` binding follows your configured keymap. To rebind it, set
`ace.keymaps.app.open_command_palette` in `~/.config/sase/sase.yml`; comma-separated
keys in that setting are treated as alternate bindings for the same action.

## Command Line

Press `:` from any tab to open the **Command Line** — a centered panel where you type
`sase` commands (the `sase` prefix is implicit) and run them without leaving the TUI.

**Behavior:**

- Selection-aware, fuzzy completion with a live signature line: the panel knows the
  current selection, ranks the selected entity first, and shows advisory grammar
  diagnostics. `Tab` completes, `Ctrl+F` accepts an active completion, `Ctrl+R` searches
  history, and `;` on an empty line hops back to the Command Palette.
- The frame's borders carry the chrome: `❯ Command Line` and the working-context chip
  (`⌂ +<project> · <path>`) on the top border, the key hints for the current context and
  the `N running` count on the bottom one. Both borders recompose when the terminal
  resizes, so their ends stay aligned: the chip is middle-truncated first, and the hints
  give way to the running count. The frame is 96% of the terminal wide (at most 200
  columns) and 80% of its height, centered; `Ctrl+T` toggles full height.
- The completion popup (and, on terminals at least 140 columns wide, the doc peek) sits
  in a completion tray beneath the input and signature line. It never covers command
  output. The tray keeps a fixed height (up to 13 rows), so the input never moves as
  candidates change. The candidate text still lines up under the slot being completed.
- The transcript follows new output. `Ctrl+D` / `Ctrl+U` scroll it by half a page from
  the input in INSERT or NORMAL mode, taking over the input's delete-char /
  delete-to-line-start keys in this panel. Scrolling back to the bottom (or running a
  command) resumes following.
- The completion popup shows an 8-row window that scrolls through every candidate; its
  footer counts the highlighted row (`N of M`) and shows the one key that fits the menu
  state. An empty line offers `RECENT` history and `FOR <selection>` suggestions under
  section headings. A slot whose provider failed reads `⚠ <kind> unavailable`, and one
  with nothing to offer reads `no <kind>`; the note never carries over to another slot.
  Provider results are cached briefly (pending plans for 5 seconds, everything else 15)
  and forgotten when a command finishes; the next fetch then skips the providers' own
  disk cache, so a plan you just approved is not offered again. A result that arrives
  after you edited the line or moved the cursor is dropped. Project slots always merge
  the provider behind the projects the TUI already knows, and a path slot lists dotfiles
  once the name you type starts with `.`.
- Every command runs as an ordinary durable proc (tagged `command-line`, visible by
  default in Admin Center → Procs), so hiding the panel never interrupts anything.
  Finished command-line procs keep their own retention bucket of 50.
- Running blocks show a spinner and live elapsed seconds even when the command produces
  no output. Reopening the panel restores the duration from the proc's start time;
  finished blocks keep their final duration.
- Run policies: most commands run as procs, some (editors, pagers, interactive tools)
  run in the real terminal with the TUI suspended, and a few refuse with an alternative.
  Declined confirmation commands render an explicit `R` rerun with `-y`; `R` does
  nothing for other blocks.
- Built-ins: `cd` (pin a working directory), `clear`, `help`, and `history`. They run
  instantly with no proc. `cd` takes a path, `+<project>` (the project's label as
  completion shows it, or `+home`), or `-` to unpin.
- Block keys (`NORMAL` mode): `o` expand, `v` pager, `K` kill, `r`/`R` rerun, `e` edit,
  `y`/`Y` copy output/command, `p` open in Procs, `x` remove, `i` back to input.

Panel keys are configurable under `ace.keymaps.command_line` in
`~/.config/sase/sase.yml`: history (`up`/`down`, `Ctrl+R`), the `;` palette hop,
`scroll_transcript_down` / `scroll_transcript_up` (`Ctrl+D` / `Ctrl+U`), and every Block
key above. Set an action to `unbound` to disable it; it also leaves the key hints. The
completion-menu keys follow the zsh menu-select contract and stay fixed: `Tab` /
`Shift+Tab` / `Ctrl+N` / `Ctrl+P` / `↑` / `↓` to move, `Enter` or `Ctrl+F` to accept,
`Esc` to leave the menu, `→` to accept ghost text at the end of the line.

The `:` binding follows your configured keymap. To rebind it, set
`ace.keymaps.app.open_command_line` in `~/.config/sase/sase.yml`.

## Machines Tab

Open the SASE Admin Center with `#`, then press `3` or select **Machines**. This is a
local inventory and administration surface for the controller plus every enrolled
remote. It does not contact all gateways when opened: remote rows begin with state **not
checked** and health **unknown** until you request an explicit status check. Remote
capacity remains **not reported** even after that check because the status response does
not carry runner capacity. The local row reports the controller's configured runner
capacity immediately.

The list shows Alias, State, Health, Capacity, Last observed, and Endpoint. The local
Alias is the controller's configured machine name even though its Agents query token is
`here`. The detail card adds capabilities, provider, pinned installation identity,
quarantine state, and the status message from the most recent check while this Admin
Center remains open.

| Key       | Action                                                                                               |
| --------- | ---------------------------------------------------------------------------------------------------- |
| `j` / `k` | Move selection                                                                                       |
| `/`       | Filter aliases, endpoints, providers, installation identity, and quarantine                          |
| `s`       | Run one bounded authenticated hello for the selected remote                                          |
| `c`       | Show the persistent connect/enrollment flow                                                          |
| `r`       | Show repair guidance for the selected remote                                                         |
| `R`       | Show the rename command for the selected remote                                                      |
| `x`       | Show removal guidance for the selected remote                                                        |
| `y`       | Copy the commands shown in the action card                                                           |
| `Enter`   | Close Admin Center and open this machine's agent tab (or filter Agents when the tab strip is hidden) |
| `f`       | Close Admin Center and open Agents filtered to this machine                                          |
| `U`       | Reload local machine inventory without probing gateways                                              |

Connect, repair, rename, and remove are guidance actions: they display canonical CLI
commands and safety notes but do not mutate machine state themselves. `Enter` selects
the machine's agent tab when the tab strip is visible, and otherwise applies an Agents
query of `machine:local` for the local controller or `machine:<alias>` for a remote (`f`
always filters). See the
[Remote Dispatch Runbook](reference/integrations/remote-dispatch.md) for the
credentialed enrollment and recovery procedures.

## Projects Tab

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
[`ace.keymaps.projects`](reference/config/ace-keymap-configuration.md#acekeymaps).

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
   refreshes discovery. When a provider remedy is offered, `t` runs it in a terminal and
   refreshes afterward. In the filter, use arrow keys to move and `Enter` to choose;
   `Esc` returns focus to the list.
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

## Statistics Tab

Open the SASE Admin Center with `#`, then press `6` or switch to **Statistics**. Its
eight sub-tabs summarize overview, runners, projects, providers, agent activity, macro
usage, plan/question activity, and performance for the selected time range. The strip is
numbered **01 Overview · 02 Runners · 03 Projects · 04 Providers · 05 Activity · 06
Macros · 07 Plans & Questions · 08 Perf**; press `0` and then the second digit to jump
straight to a view. The Admin Center-wide `'` entry-jump key arms this same
numbered-view selection instead of painting row hints — Statistics has no row cursor, so
the already visible strip numbers act as its jump hints; `Esc` or any non-digit cancels.
Use `[` / `]` to move between views, `t` / `T` to cycle time ranges, `c` to enter a
custom range, `p` / `P` to cycle project scope, `Ctrl+D` / `Ctrl+U` to scroll, `r` to
refresh, and `?` for the pane's key help. First open seeds the project filter from the
[current project](#current-project) when `ace.current_project.seed_filters` is on; `p` /
`P` can always cycle away from that seed, including back to **All projects**. On
Overview, Agents Run, Success Rate, and Commits open Projects; Plans Proposed and
Questions open Plans & Questions.

The **Perf** sub-tab combines five headline measures—Startup (median visible-ready),
Stalls (stall count, with hitches named separately in the tile's detail line), Launch
(p95 total launch time), Agent p95, and LLM p95—with startup stages, stall/hitch events,
grouped latency and reliability, and source-coverage diagnostics. Press `g` to group
latency by subsystem, provider, or workflow; the grouping also decides what the count
column counts (LLM invocations, agent runs, or an ungrouped count) and whether a Share
column applies. Perf counts come from telemetry and TUI logs, not the artifact index, so
they are not comparable with the run counts on the other sub-tabs. Perf is global: the
project chip remains visible but is marked **not applied**. See
[Reading the Admin Center Perf view](contribute/perf-runbook.md#reading-the-admin-center-perf-view)
for data sources, retention, and probe details.

The Statistics **Macros** sub-tab reports macros referenced by agent launch prompts:

- **By Usage** ranks macros by runs and shows references, share, agents, success,
  runtime, and recency.
- **By Model** breaks each macro down by model.
- **By Project** breaks it down by project.
- **Used With** shows macros referenced together in the same run.

Press `g` to cycle those four groupings without reloading the underlying statistics.
Press `x` to choose one macro and replace the ranking with its full time, model,
project, provider, tribe, and co-usage breakdown; press `X` to clear that focus. The
range and project filters apply before all macro aggregation.

These counts come from each run's launch-boundary `macros.json`, recorded before prompt
expansion. A run counts once per macro name, while **Refs** counts distinct argument
variants of the same name separately. References introduced inside workflow step
templates are intentionally excluded. Historical runs appear after the agent-artifact
index rebuilds at the current schema.

Each record carries a kind — `workflow`, `part`, or `swarm`. A macro swarm is consumed
by the dispatcher before any agent starts, so it never appears as a lexical reference in
a child's prompt; instead the swarm is attributed to every agent it launched, and a
nested swarm records every link of its chain. Because swarm records carry no arguments,
**Refs** equals **Runs** for a swarm row. Attribution is forward-only: runs launched
before this feature shipped are not backfilled.

This Statistics sub-tab is distinct from Config's **Macros** child described in
[Macro Browser](reference/tui/snippets.md#macro-browser): that child browses and edits
macro definitions, while the Statistics sub-tab measures how launch prompts used them.

## Tools Tab

Open the SASE Admin Center with `#`, then press `7` or switch to **Tools**. Its three
sub-views cover **Runs** (silent runs pinned first in red, then live, then settled
newest first), **Failures** (failure-signature groups with run and agent witness
counts), and **Catalog** (the current project's named tools with LAST and TYPICAL from
the run ledger). The pane is filtered to the current project by default; press `A` to
widen it to all projects. Use `[` / `]` to move between views, `/` to filter Runs with
`tool:`, `state:`, `agent:`, and `verdict:` tokens, `enter` to focus detail (`Failures`
lists the group's affected runs newest first with their agents), `a` to jump to the
run's ⚒ Runs block on the owning Agents row, `v` to open the retained log in the pager,
`y` to copy the run id, `s` to stop the focused live run (same DANGER confirm as the
Agents tab), `r` to run the focused catalog tool at the current project root, and `R` to
reload. The Runs detail reuses the Agents tab Runs block renderer. The pane never
settles or reconciles runs; the only writes it offers are the explicit stop and
catalog-run flows. The top-bar `tools:` group opens this pane with all projects, so the
pane never shows fewer runs than the chip claims.

<a id="models-panel"></a>

<a id="launch-control"></a> <a id="providers-usage"></a>
<a id="default-effort-controls"></a> <a id="runner-capacity-controls"></a>
<a id="provider-routing-controls"></a> <a id="disabled-provider-launch-panel"></a>
<a id="automatic-provider-drain"></a> <a id="tmux-agent"></a> <a id="alias-history"></a>
Moved to [Launch Control](reference/tui/launch-control.md#launch-control-1).
<a id="temporary-overrides"></a> Moved to
[Launch Control overrides](reference/tui/launch-control-overrides.md#temporary-overrides).
<a id="persistent-edits"></a> Moved to
[Launch Control overrides](reference/tui/launch-control-overrides.md#persistent-edits).
<a id="examples-1"></a> Moved to
[Launch Control overrides](reference/tui/launch-control-overrides.md#examples-1).

## Notifications Modal

Press `i` to open the notifications modal. On the Agents tab, `Enter` opens the selected
agent's pending gate or Patch directly, without the modal. See the
[notifications reference](reference/automation/notifications.md) for the full keybinding
reference, modal tabs, priority/error/muted classification, and the per-notification
snooze and mute affordances.

Rows and the detail header begin with the notification's single-glyph icon when one is
present, with a per-action fallback icon otherwise. The text action badge remains
visible as the secondary label.

Press `d` on the highlighted inbox row to open Gate Debug, even when the row is not
gate-backed or its gate modal can no longer load. The same `d` binding is available
inside plan/epic approval, user-question, launch-approval, custom-gate, and workflow
HITL panels. Gate Debug presents Overview, Request, Response, Errors, and raw Row tabs;
`[` / `]` switch tabs, `y` copies the current tab, `Y` copies the bundle path, `e` opens
the backing file, and `d`, `q`, or `Esc` closes the overlay without losing state in the
underlying panel.

The `inbox:` top-bar group renders one colored `<icon><count>` chip per
notification-panel tab, in the panel's own order and colors, or a dim `inbox: 0` when
nothing is pending. See
[Top-Bar Indicator](reference/automation/notifications.md#top-bar-indicator) for the
snoozed-only and overflow forms.

### Snooze Reminder Scheduling

Snooze expiry does not depend on the general refresh cadence. sase's TUI keeps at most
one timer for the nearest deadline reported by the current notification snapshot, so
reminders fire on time even with clean inotify state or `--refresh-interval 0` (which
disables ordinary auto-refresh). The timer callback stays thin and synchronous: it
compares cached wall-clock values on Textual's message pump and hands the store read to
a coalesced proc, so no disk or worker I/O runs on the pump and an expired snooze never
triggers a full Agents-list rebuild.

While any snooze is pending, sase's TUI rechecks the wall clock at most one second
apart, so a suspended host, a resumed session, or a forward/backward system-clock change
re-evaluates the authoritative UTC deadline promptly instead of waiting out a monotonic
timer. Startup reconciliation, notification-file watcher events, ordinary polling, and
modal snooze/resnooze/unmute/dismiss completions all route through the same coalescing
guard, so an external mutation can replace or cancel the cached nearest deadline
immediately. The coordinator starts after first paint and its timer and task are
cancelled during normal and controlled teardown.

Once due, sase's TUI performs one current-state snapshot read, applies counts, toasts,
and status projections, then schedules the next future deadline. Each observed resurface
batch produces toasts (one per row, or grouped per severity when more than three rows
arrive together) and at most one tmux bell, unless a
[delivery rule](reference/automation/notifications.md#delivery-rules) overrides it —
including rows that were marked read while snoozed — and no repeat on later polls.
Cancelled, dismissed, permanently muted, and not-yet-due rows never ring. If another
process wins the expiry, the persisted unread state and `resurfaced_at` still make the
transition observable here. Resurfaced rows sort as recent activity in the modal while
continuing to display their original sent time. See the
[notifications reference](reference/automation/notifications.md#snooze-expiry-and-resurfacing)
for the full state and timing contract.

## Notification Actions

Some notifications carry an `action` field that triggers a handler when the notification
is selected. The following notification action types are supported:

| Action                | Source          | Behavior                                                                                                                                                                                               |
| --------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CustomGate`          | Agent/tool      | Opens the generic choices, add-ons, and feedback modal                                                                                                                                                 |
| `GateExecutionFailed` | Gate executor   | Opens the resume / restart / cancel dialog, or the error report when none applies                                                                                                                      |
| `HITL`                | Workflow        | Opens the workflow human-in-the-loop response modal                                                                                                                                                    |
| `JumpToAgent`         | Agent/workflow  | Jumps to the matching Agents-tab row, revealing it first like the Node Finder: expands collapsed folds, grouping banners, and panels; shows `I`-hidden rows; clears a hiding Agents query with a toast |
| `JumpToPatch`         | Sync/workflow   | Jumps to the referenced Patch on the Patches sub-tab                                                                                                                                                   |
| `JumpToMentorReview`  | Mentors         | Jumps to the Patch and opens mentor review output when available                                                                                                                                       |
| `LaunchApproval`      | Agent           | Opens the launch approval modal for an agent-requested launch                                                                                                                                          |
| `OpenToolRun`         | Tool run        | Selects the settled run's Agents-tab node with its ⚒ Runs card active and the run's block selected, or opens Admin Center → Tools focused on the run                                                   |
| `PlanApproval`        | Agent           | Opens the plan approval modal                                                                                                                                                                          |
| `RemoteAttention`     | Remote machine  | Opens the remote question or gate modal and submits to the owning machine                                                                                                                              |
| `SudoRequest`         | Agent           | Opens the [sudo review modal](reference/automation/sudo.md#review-ux); approving runs in a terminal                                                                                                    |
| `Tmux`                | External bridge | Runs `tm <workspace-name>` for the notification's `action_data.workspace_dir`                                                                                                                          |
| `UserQuestion`        | Agent           | Opens the structured user-question response modal                                                                                                                                                      |
| `ViewErrorReport`     | Axe/agent       | Opens `action_data.error_report_path`, or the first attached file, in `$EDITOR`                                                                                                                        |

The axe `error_digest` job creates `ViewErrorReport` notifications whose digest files
live under `~/.sase/axe/error_digests/digest_<timestamp>.txt`; user-agent failures can
use the same action for their own attached error reports.

The custom-gate modal shows the sender and notes or verified preview, one icon-led
button per terminal choice, and checkboxes for that choice's independently selectable
add-on commands. The Decision column holds those controls only; an option that declares
typed input wears a dim `✎ n inputs` badge and collects those values in the dedicated
input panel instead (see [Remapping Gate Modal Keys](#remapping-gate-modal-keys)).
Required feedback also opens that panel, whose submit stays blocked until non-empty text
is present; optional feedback still answers in one keystroke and is attached by pressing
`i` first, and disabled feedback shows no note field at all. Unsupported future actions
produce a warning instead of silently doing nothing.

Custom gates and neutral HITL gates execute through the shared hash-verifying gate
executor. sase's TUI schedules the terminal command and each selected add-on through the
tracked proc queue, streams live stdout/stderr to the proc, shows each command as a
reporter phase, and refreshes the inbox when the proc completes. Legacy HITL bundles
retain the direct response-file fallback.

### Toast Notifications

Each newly-arrived notification produces a short toast in the TUI. The toast text is
derived per-action type (plan, question, HITL, axe error, Patch sync, agent update) so
the message previews the actual event rather than a generic "N new notification(s)"
line. Severity is also picked per type: plans, questions, and HITL render as warnings;
axe errors (and sync failures) render as errors; everything else renders as information.

A genuinely new tale or epic plan review rings the terminal bell on arrival (one bell
announcement, sent as three short tmux beeps) and remains visually prominent as a
warning toast and priority inbox row. Already-answered plan reviews discovered during
polling and the post-approval coder or epic handoff stay silent. Questions, other
audible notification classes, and explicit snooze-expiry reminders retain their existing
bell behavior; snoozing a plan review therefore still produces the requested reminder
bell when it expires.

These are defaults.
[`ace.notification_rules`](reference/automation/notifications.md#delivery-rules) can
suppress a toast or replace the bell with a sound file or silence for any notification,
including snooze-expiry reminders; rows whose toast is suppressed are left out of the
grouped-toast count.

When more than 3 notifications arrive in the same poll tick, per-notification toasts are
consolidated into one grouped toast per severity bucket (e.g.,
`2 warnings: 1 plan, 1 question`). Ordering is urgency-first: errors, then warnings,
then information. Silent notifications are excluded from this pipeline entirely.

Agent completion and failure toasts include the `%id`-set agent name with an `@` prefix
when present (e.g., `CLAUDE(opus) @sase-q.land completed: ace(run)-...`); anonymous
agents (no `agent_name`) keep the prior format.

<a id="macro-browser"></a> <a id="keybindings"></a> <a id="editing-macros"></a>
<a id="creating-macros"></a> Moved to
[Snippets](reference/tui/snippets.md#macro-browser).

## Jump All Modal

Press `` ` `` (backtick) on any tab to open the Jump All Modal. It displays all entries
across Agents, Artifacts, and Services tabs with the same adaptive one- or two-character
hints used by current-tab entry jump. Completing an entry's hint switches to the
appropriate tab and focuses it.

Up to 62 entries use `0`–`9`, `a`–`z`, `A`–`Z`. Larger result sets use fixed-width pairs
from `00` through `ZZ`; a first character is consumed without closing the modal, and
uppercase characters remain case-sensitive.

| Key                 | Action                                                   |
| ------------------- | -------------------------------------------------------- |
| Hint                | Jump to the corresponding entry                          |
| `` ` ``             | Jump back to the previous position (see below)           |
| `Ctrl+D` / `Ctrl+U` | Scroll the entry list down / up                          |
| `Esc`               | Close modal (any other key that is not a hint also does) |

The modal groups entries by tab (Agents, Artifacts, Services) and shows contextual
information for each: PR names and statuses, agent names with running indicators, and
Axe routine/command labels.

### Jump Back

Both jump modals support a jump-back feature for toggling between two entries:

- **Backtick jump-back**: Pressing `` ` `` inside the Jump All Modal returns to the
  previous position, enabling quick toggling between two entries across tabs.
- **Apostrophe jump-back**: Pressing `'` twice (`''`) in the single-tab entry jump mode
  jumps back to the previously jumped-from entry. The footer shows a "JUMP" mode
  indicator with `' back` when a target exists.
- **Fast jump**: `Ctrl+O` runs the same current-tab jump-back path without painting
  hints first; when no jump-back target exists, it selects the first current-tab hint.
- **Forward jump**: After walking backward, `Ctrl+Shift+O` walks forward through that
  current tab's jump stack. Agents, Artifacts/Patches, and Services keep independent
  back and forward positions.

The single-tab variant (`'` apostrophe) shows entries only from the current tab with the
same hint-character navigation.

## Node Finder

Press `"` (quotation mark) on the Agents tab to open the Node Finder modal. It lists
every reachable sase node as a tree — clans, agent nodes, session turns (including
monitors and gates), workflow roots, workflow `agent` steps, and stand-alone named procs
— including rows hidden by collapsed folds, collapsed grouping banners, collapsed or
isolated tribe panels, and the Agents query. Jumpable live node rows carry jump hints;
Archive results below them use selection and `Enter`.

| Key                          | HINTS mode (default)                              | SEARCH mode (query focused)   |
| ---------------------------- | ------------------------------------------------- | ----------------------------- |
| `0-9a-zA-Z`                  | Complete a hint and jump, or set a pending prefix | Edit the query; live refilter |
| `Tab` / `Shift+Tab`          | Focus the query                                   | Back to HINTS, query kept     |
| `/`                          | Focus the query                                   | Types `/`                     |
| `Enter`                      | Jump to the highlighted node                      | Jump to the highlighted node  |
| `Ctrl+N` / `Ctrl+P`, `↓`/`↑` | Next / previous jumpable row (wraps)              | Same                          |
| `"`                          | Jump back (same as `Ctrl+O`)                      | Types `"`                     |
| `Backspace`                  | Cancel a pending prefix; otherwise swallow        | Delete a character            |
| `Esc`                        | Cancel a pending prefix; otherwise close          | Back to HINTS, query kept     |
| `PgUp` / `PgDn`              | Scroll the preview pane                           | Scroll the preview pane       |
| Any other key                | Swallow; the footer flashes `no hint ‹x›`         | Types                         |

The why-hidden glyph legend: blank means visible, `◆` you are here, `⊘` hidden by the
Agents query, `◌` hidden by `I` (until listed, shown as an `I hides K` chip), `▭` inside
a collapsed or isolated-away tribe panel, `≡` inside a collapsed grouping banner, `▸`
inside a collapsed fold.

"Hidden" covers folds, banners, panels, and rows the Agents query hides. Jumping to a
query-hidden node clears the Agents query (recorded in query history, announced with a
toast); restore it with the query-history keys. The one-line jobs of the sibling
surfaces: `'` jumps by hint on the current tab, `` ` `` jumps across all tabs, digits
jump roster members, and `"` in the finder jumps back.

A `◷ In Archive` section follows the live rows. It lists up to five dismissed runs from
this machine: the first five names in the Archive's day order when the query is empty,
or the five best fuzzy name matches once you type. While that list is loading the
section reads `Archive warming…` or `Searching Archive…`; an empty search result reads
`No archived name matches.`, and a loading or search error reads `Archive unavailable.`
The finder searches an already-warm Archive snapshot; if none is available when it
opens, the section fills in once the Archive warms while the finder stays open (it
rechecks on each keystroke and for about 15 seconds after opening). Select a result with
the arrow keys or `Ctrl+N` / `Ctrl+P`. Its preview reads `ARCHIVED RUN`,
`Dismissed on this machine · read-only`, and `⏎ opens the run in the Archive`. `Enter`
switches to the Archive and selects the run without restoring it. This replaces the
Archive query with `in:archive`; it does not add a name filter. The toast reads
`Node Finder · opening archived run · read-only`. Archive results carry no jump hints.

The preview sits beside the list. On a terminal at least 140 columns wide the list also
keeps a status column. From 100 columns up to that width the two panes split evenly and
the status column is hidden. Below 100 columns the preview stacks under the list. `PgUp`
and `PgDn` scroll the preview in both modes.

The preview paints from the snapshot taken when the finder opened. The highlighted row
shows its kind and name, a compact identity block, and a breadcrumb from the tribe panel
through ancestor names to the row (`@default ▸ parent ▸ name`). It also says whether the
row is visible, and what `Enter` will do: `⏎ selects it` when the row is already
visible, or the reveals it will perform first (clearing the Agents query, opening a
hidden panel, opening a collapsed group, expanding folds) and then selecting it. A
session row lists its turns. A clan lists a status tally and up to twelve members, then
`… N more members` when the clan is larger. A monitor or named proc shows its command
and an output tail. A gate turn shows its label and state. A workflow root shows a
step-status tally. A non-node row says `Select a node to inspect it.`

Agent turns then fill two more sections from that turn's artifacts: a `PROMPT` head and
a `REPLY · tail`. A session container uses its newest agent turn for those sections and
labels the prompt with that turn's name. Clans, monitors, gates, and named procs stop
after the in-memory preview. The prompt and reply slots read `⋯ loading` until that read
finishes, then `(no prompt recorded)` or `(no reply recorded)` when the artifact is
empty. The reply tail names how many earlier lines were left off.

## Mentor Comment Stats in PR List

When a Patch has completed mentor reviews with comments, its Patches sub-tab list entry
shows inline stats:

- **checkmark + count** (e.g., `✓3`) — number of accepted comments
- **dot + count** (e.g., `●2`) — number of unread comments

These stats are computed from the latest stitch's finished mentors. They update as you
accept or read comments in the Mentor Review modal.

## PR Origin Chip

A Patch with a `pr_url` shows a `PR_ORIGIN` chip next to its PR badge in the Patches
sub-tab list and in the detail panel: nothing for the default `sase` origin (a PR SASE
created through the tracked PR workflow), `external` for a PR SASE adopted but did not
create, and `origin?` for `unknown` (no evidence either way). The detail panel adds a
one-line note for `external` Patches, since AXE excludes external-origin Patches from
its candidate selection entirely (see [AXE](reference/automation/scheduler.md)). Press
`!o` on a PR row (see [PR Actions](#pr-actions) above) to open the Mark PR Origin modal
and set it explicitly, or run `sase patch set-origin <name> <sase|external|unknown>`
(see [CLI Reference](cli.md#work-tracking-and-planning)). See
[PR_ORIGIN](reference/work-units/patches.md#pr_origin) and
[Origin Matching](reference/query-language.md#origin-matching) for the underlying Patch
field and the `origin:` query property.

## Current project

sase's TUI has one **current project**: the head of the VCS macro MRU store. Launching
an agent on a project — or on a Patch owned by that project — promotes it to that head.
`sase project set-current <project>` and the Projects tab's `c` key (see
[Projects Tab](#projects-tab)) move it the same way, by promoting the project to the MRU
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
[runner load gauge](reference/tui/agents-tab-grouping.md#grouping-modes) sits just
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
[`ace.current_project`](reference/config/ace-behavior.md#acecurrentproject) for the
three fields.

## Tab Bar Display

The tab bar renders plain tab labels (`Agents`, `Artifacts`, `Services`). Per-bucket
counts live inside each tab's body — for example the per-panel count summaries on the
Agents tab — rather than as suffixes on the tab title itself.

### Top-Bar Indicators

The right-aligned indicator cluster speaks the same visual language as the status-row
cluster beneath it (`load: 5/8 · model: opus@high · project: +sase`): every group
renders as a `<type>: <body>` group where only the `<type>:` label is dim, so a group's
value looks the same in full and compact modes, and visible groups are joined by a dim
`·`. The left-to-right order runs from activity to system state to launch routing to
personal queues: `tools`, `bg`, `updates`, `overrides`, `priority`, `disabled`, `stash`,
`inbox`. The always-visible `inbox` anchors the right edge directly above `project:`.
Labels are fixed strings that never pluralize. Count chips carry their identity glyph
inside the fill — `⚒` for tool runs (sky blue, red with `⚠` while silent), `⚙` for
background procs (blue) and bare monitors (orange), `⬆` for updates, `≡` for the stash,
`★` for priority — so compact mode (labels dropped together when the full cluster does
not fit in the cells left over after the tab strip and a 2-cell minimum gap; separators
kept) still identifies each group; widening restores full labels without oscillation.
Every group is clickable: tools opens Admin Center › Tools › Runs with all projects, bg
opens the Admin Center Procs tab, updates opens the Updates tab (or the Procs tab on the
running update while SASE is updating, when the badge shows its green gear inset, or the
Procs tab on the first restart blocker while a restart is queued, when the badge shows
its yellow gear inset), overrides, priority, and disabled open Launch settings, stash
opens the Prompts overlay on Stash, and inbox opens the notification modal. While SASE
is updating itself, the `updates` group shows a green `⚙` gear inset at its left edge.
While installed code waits for TUI-local tasks, submissions, or installation changes
before restarting ACE and the SASE service, it shows a yellow `⚙` gear inset instead
(green outranks yellow). Independent commands keep running. Durable operations started
from this TUI still finish their result handling first, within the same 60-second wait.
The yellow tooltip names the actual blockers and the time ACE restarts anyway; clicking
it opens the Procs tab on the first blocker. Feature-flag restarts never show the yellow
gear.

### Tools and Background Indicators

The `tools:` group shows every live `sase tool` run on the machine: a sky-blue `⚒ N`
chip for healthy runs, a red `⚒⚠ M` chip for silent runs (no activity for 60 s or more),
and an orange `⚙ K` chip for monitor turns not currently carrying a run. The `⚒` count
comes from the ToolRun ledger, so it covers every mode (escalated, detached, catalog,
monitor adopt/join, foreground) on every tab, ignoring the project filter, tribe
selection, and session; a live child folds into its live parent. An execution is drawn
exactly once: a proc that carries a live run is never drawn as a gear. Each chip hides
at zero and the group hides only when all chips are zero. Before the first glance load
the `⚒` chips stay hidden rather than showing a false zero; if loads keep failing the
last snapshot renders dim with a trailing `?`. Hover lists up to five runs (silent
first, then oldest) plus bare monitors; click to open Admin Center › Tools › Runs with
all projects.

The `bg:` group shows a filled blue `⚙ N` chip while sase's TUI own background procs are
running (e.g., sync, mail, accept, and notification-gate operations) — the same count
the Procs tab header shows in blue. Tool-run carriers never count here; they live under
`tools:`. Procs that are updating SASE move to the green `⚙` gear in `updates:` and no
longer count in the blue chip. The chip hides at zero. The group excludes service-host
rows — service procs and oneshots — which the Services tab reports instead. Hover for
the proc labels; click to open the Procs tab.

### Current Project Indicator

The uniquely colored `+<project>` chip is not in the tab bar: it is the project half of
the launch-context cluster at the right of each tab's status row
(`model: <launch default> · project: +<name>`). Clicking it opens the `+` launch picker.
See [Current project](#current-project) for what the chip means, what it seeds, and how
to turn each part off.

### Runners Modal

Press `,R` (leader + `R`) to open the runners modal. It shows concurrency information
including hook runners, agent runners, and a **Procs** section listing active and
recently completed TUI procs from the current sase's TUI session. These include Patch
actions, agent launch and cleanup work, `monitor-stop`, and notification updates. Each
row shows the target, proc type and status, and elapsed or total duration; a failed row
also shows its error message. This modal does not show proc output. Use the Admin
Center's [Procs tab](#procs-tab) or `sase proc show ID` for durable records and captured
output. Press `j` to paint hint keys over the rows and jump to the matching agent or
Patch; `Ctrl+D` / `Ctrl+U` scroll, and `r`, `q`, or `Esc` closes the modal.

## File Panel Rendering

Agent files render in full and scroll natively in the file panel. Syntax highlighting
falls back to plain text for large content. Pathological outputs above the file-panel
safety limit show the first 5,000 lines and an explicit editor notice; press `E` to open
the complete content.

<a id="agents-zoom-and-node-rail"></a> Moved to
[Agents tab main deck](reference/tui/agents-main-deck.md#agents-zoom-and-node-rail).

## Image Preview Foundation

sase's TUI renders PNG, JPEG, WebP, and GIF attachments with a Pillow-backed Rich cell
preview. The renderer decodes the first image frame, preserves aspect ratio within the
visible panel bounds, composites transparency, and paints colored half-block cells using
truecolor when the terminal advertises it and 256-color approximations otherwise.

Generated images are already attached to successful agent completion notifications and
recorded in `done.json` as `image_paths`. The Agents tab file panel and notification
modal route supported raster image attachments through this preview layer before
attempting text decoding. See [`agent_images.md`](reference/agent-attachments.md) for
supported image extensions, guardrails, and current preview behavior.

<a id="agent-auto-naming"></a> <a id="providermodel-suffixes"></a>
<a id="per-step-naming-for-multi-agent-workflows"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#agent-auto-naming).
<a id="agent-statuses"></a> <a id="execution-waiting-review-and-handoff-statuses"></a>
<a id="service-health-pill"></a> <a id="completed-statuses"></a>
<a id="agent-revival"></a> <a id="legacy-dismissed-name-prefix"></a>
<a id="agents-deck-picker"></a> <a id="agent-data-decks-and-cards"></a>
<a id="deck-views"></a> <a id="card-blocks"></a>
<a id="finalizers-on-the-agents-tab"></a> Moved to
[Agent statuses](reference/tui/agent-statuses.md#agent-statuses-1).
<a id="agents-tab-main-deck"></a> Moved to
[Agents tab main deck](reference/tui/agents-main-deck.md#agents-tab-main-deck-1).
<a id="agents-tab-llm-calls-panel"></a> Moved to
[Agents tab LLM calls and tool runs](reference/tui/agents-deck-panels.md#agents-tab-llm-calls-panel).
<a id="agents-tab-tool-runs"></a> <a id="state-vocabulary"></a>
<a id="at-a-glance-the-row-chip"></a>
<a id="in-context-the-header-chip-and-tool-runs-field"></a>
<a id="to-diagnose-the-runs-card"></a>
<a id="links-from-llm-calls-slow-tools-and-context-cards"></a>
<a id="stopping-a-run-and-running-a-tool"></a> Moved to
[Agents tab LLM calls and tool runs](reference/tui/agents-deck-panels.md#agents-tab-tool-runs).
<a id="plan-workflows"></a> <a id="auto-approve-toggle"></a>
<a id="plan-approval-keybindings"></a> <a id="custom-approval"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#plan-workflows).
<a id="launch-approval"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#launch-approval).
<a id="agent-holds"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#agent-holds).
<a id="linked-chats-in-multi-step-workflows"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#linked-chats-in-multi-step-workflows).
<a id="retryfallback-display"></a> <a id="prior-agent-attempts"></a> Moved to
[Agent workflows](reference/tui/agent-workflows.md#retryfallback-display).

## Custom Keymaps

Configurable TUI actions use the `ace.keymaps` section in `sase.yml`; their bundled
defaults are listed in the generated [TUI keymaps reference](reference/tui/keymaps.md).
You can remap app-level, gate-modal, Memory-panel, and focused Statistics-pane keys and
define entirely new prefix-key modes.

### Remapping Built-in Keys

Override any app-level keybinding under `ace.keymaps.app`:

```yaml
ace:
  keymaps:
    app:
      next_patch: "n" # Remap j -> n
      prev_patch: "p" # Remap k -> p
      edit_query: "f5" # Structured query on Artifacts and Agents
      show_notifications: "N" # Remap i → N
```

Agents deck search is independent: remap
`ace.keymaps.modes.leader_mode.keys.search_forward` to change the subkey after the
configured leader prefix. Structured query editing on every query-capable surface,
including Agents, is `ace.keymaps.app.edit_query`. Stale `app.search_forward` and
`leader_mode.keys.edit_query` overrides are ignored with a warning pointing at those
replacements.

### Remapping Statistics Pane Keys

Override focused Statistics bindings under `ace.keymaps.statistics`:

```yaml
ace:
  keymaps:
    statistics:
      prev_view: "left_square_bracket"
      next_view: "right_square_bracket"
      select_view: "0"
      jump_to_entry: "apostrophe"
      cycle_range: "f11"
      cycle_range_reverse: "shift+f11"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      cycle_project_filter_reverse: "P"
      focus_macro: "x"
      clear_macro_focus: "X"
      scroll_down: "ctrl+d"
      scroll_up: "ctrl+u"
      refresh: "f10"
      help: "f9"
```

The example above names every Statistics binding, but only some are remapped: it shows
`cycle_range`, `cycle_range_reverse`, `refresh`, and `help` moved off their `t`, `T`,
`r`, and `?` defaults, and repeats the defaults for the rest. Override only the keys you
want to change.

These keys dispatch only while the Admin Center Statistics pane is focused. They may
overlap app-level bindings without creating a global conflict, and the pane's hint bar
always shows the effective keys. Press the configured `select_view` prefix and then
`1`–`8` to select the matching view displayed as `01` through `08`; bare digits continue
to switch the Admin Center's top-level tabs. `jump_to_entry` arms that same
numbered-view selection, which is how the Admin Center-wide `'` behaves on a pane that
has no row cursor to jump between — the visible strip numbers serve as its hints. The
group control is visible and active only in Projects, Macros, and Perf. On the Macros
view, the focus key opens a filterable picker and the clear-focus key restores **All
macros**. Project filtering cycles through **All projects** and the latest cached
unfiltered ranking: the configured forward key moves toward the first ranked project,
the reverse key moves toward the last, and both wrap. First open seeds the current
project when `ace.current_project.seed_filters` is on; either key can cycle away from
that seed. Either key clears an active project filter directly when its loaded result is
empty.

### Remapping Gate Modal Keys

Override the shared plan/custom gate controls under `ace.keymaps.gate`:

```yaml
ace:
  keymaps:
    gate:
      next_control: "down"
      previous_control: "up"
      toggle_option: "space"
      submit_primary: "enter"
      submit_branch: "ctrl+enter"
      open_inputs: "o"
      next_input: "ctrl+n"
      previous_input: "ctrl+p"
      decision_next: "l,right"
      decision_prev: "h,left"
      decision_reset: "r"
      decision_reset_all: "R"
      decision_zoom: "z"
```

These bindings dispatch only while a branch-driven gate modal is open, and its footer
shows the effective keys. The example remaps navigation, `submit_branch`, and the input
panel keys, and repeats the defaults for `toggle_option` and `submit_primary`.
`open_inputs` (default `i`) opens the input panel for the focused option's note or
declared fields, including an optional note that would otherwise skip the panel.
`next_input` and `previous_input` (defaults `tab` and `shift+tab`) walk the panel's
fields and buttons; they are inactive on the gate modal itself. Confirming the panel
submits the branch; cancelling it returns to the gate without answering. The retired
`activate_control` setting is accepted as a deprecated alias for `submit_primary`.

### Remapping Memory Panel Keys

Override [Memory panel](reference/tui/prompt-completion-panels.md#memory-panel) bindings
under `ace.keymaps.memory`. A value may list more than one key, separated by commas:

```yaml
ace:
  keymaps:
    memory:
      follow_link: "enter,l"
      travel_back: "backspace,h"
      filter_notes: "slash"
      toggle_body_filter: "greater_than_sign"
      toggle_web: "space"
      next_strand: "s"
      prev_strand: "S"
      add_note: "a"
      edit_note: "e"
      delete_note: "d"
      publish: "I"
```

These bindings dispatch only while the panel is open. The full action list and defaults
are in the
[`ace.keymaps` configuration reference](reference/config/ace-keymap-configuration.md#acekeymaps).
`.` (`full_stop`) is reserved for the fixed `.` then `1`–`9` numbered-chip prefix; a
config that assigns it to a Memory action is warned and reverted to that action's
default. `>` (`greater_than_sign`) remains a valid configurable key and is the default
for `toggle_body_filter`.

The retired Glossary panel's bindings folded into these Memory panel actions:
`add_note`/`delete_note` branch on the selected row (a web row adds a strand, a strand
row deletes one), and `next_link`/`prev_link`/`follow_link` follow a glossary strand's
mention-relation chips the same way they follow a note's `PARENT`/`CHILDREN` chips.
`ace.keymaps.glossary` is still accepted in config for one release, but it is inert: no
defaults ship for it and it builds no bindings. `sase doctor` warns when a loaded config
layer sets it explicitly and points at `ace.keymaps.memory` instead.

### Remapping Snippets Panel Keys

Override [Snippets panel](reference/tui/prompt-completion-panels.md#snippets-panel)
bindings under `ace.keymaps.snippets`. A value may list more than one key, separated by
commas:

```yaml
ace:
  keymaps:
    snippets:
      follow_relation: "enter,l"
      travel_back: "backspace,h"
      filter_snippets: "slash"
      toggle_body_filter: "full_stop"
      add_snippet: "a"
      edit_snippet: "e"
      delete_snippet: "d"
```

These bindings dispatch only while the panel is open. The full action list and defaults
are in the
[`ace.keymaps` configuration reference](reference/config/ace-keymap-configuration.md#acekeymaps).

### Custom Modes

Define user-defined prefix-key modes under `ace.keymaps.modes`. Each custom mode has a
`prefix` key and a `keys` dict where each sub-key specifies either a `shell` command or
a built-in `action`:

```yaml
ace:
  keymaps:
    modes:
      my_mode:
        prefix: "B"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
          show_log:
            key: "l"
            shell: "git log --oneline -20"
          refresh:
            key: "r"
            action: "refresh"
```

Pressing `B` activates the mode, then pressing `t` runs `just test`, `l` shows the git
log, etc.

### Validation

The keymap loader validates all configuration:

- **Invalid keys** are reverted to their defaults with a warning
- **Duplicate keys within one binding scope** are detected and the conflicting override
  is reverted
- Stale `app.search_forward` and `leader_mode.keys.edit_query` overrides are ignored
  with a warning; they are not translated into a second live shortcut
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned
- Key names follow Textual's spelling (`slash`, `dollar_sign`, `backslash`,
  `vertical_line`, …); the raw glyphs `+`, `-`, `$`, `_`, `\`, and `|` are also
  accepted, and key hints display the glyph

See the
[ACE keymap configuration](reference/config/ace-keymap-configuration.md#acekeymaps) for
the full `ace.keymaps` reference.

<a id="prompt-input-widget"></a> <a id="cursor-readout"></a> <a id="prompt-search"></a>
<a id="insert-mode-default"></a> <a id="raw-placeholder-inputs"></a>
<a id="launch-target-picker"></a> <a id="editing-an-existing-macro-from-the-tui"></a>
<a id="alt-brace-syntax"></a> Moved to
[Prompt input](reference/tui/prompt-input.md#prompt-input-widget).
<a id="prompt-stacks"></a> Moved to
[Prompt stacks](reference/tui/prompt-stacks.md#prompt-stacks-1). <a id="completion"></a>
<a id="next-word-prediction"></a> Moved to
[Prompt completion](reference/tui/prompt-completion.md#completion).
<a id="glossary-terms"></a> Moved to
[Prompt completion panels](reference/tui/prompt-completion-panels.md#glossary-terms).
<a id="memory-panel"></a> Moved to
[Prompt completion panels](reference/tui/prompt-completion-panels.md#memory-panel).
<a id="snippets-panel"></a> Moved to
[Prompt completion panels](reference/tui/prompt-completion-panels.md#snippets-panel).
<a id="repo-names"></a> Moved to
[Prompt completion panels](reference/tui/prompt-completion-panels.md#repo-names).
<a id="word-definitions-spellcheck"></a> Moved to
[Prompt completion panels](reference/tui/prompt-completion-panels.md#word-definitions-spellcheck).
<a id="normal-mode"></a> <a id="motions"></a> <a id="operators"></a>
<a id="text-objects"></a> <a id="operator-search"></a> <a id="other-commands"></a> Moved
to [Prompt modes](reference/tui/prompt-modes.md#normal-mode). <a id="visual-mode"></a>
Moved to [Prompt modes](reference/tui/prompt-modes.md#visual-mode).
<a id="prompt-history-modal"></a> <a id="keybindings-1"></a> <a id="filtering"></a>
Moved to [Prompts overlay](reference/tui/prompts-overlay.md#prompt-history-modal).

## Procs Tab

Open the SASE Admin Center with `#`, then press `4` (or switch tabs until you reach
**Procs**). You can also run the keyless **Open procs panel** command from the command
palette. The tab shows procs (hook runs, mentor executions, agent launches, plugin
operations, etc.) with live output for running procs and completed output for finished
ones.

### Durability and Scope

Procs the TUI runs itself are **mirrored** into the durable proc store
(`~/.sase/procs/procs.jsonl`, with one combined output log per proc under
`~/.sase/procs/logs/`), so their outcome survives the session that produced them and is
visible from `sase proc list` / `sase proc show`. Supervisor-backed procs — commands
submitted with `sase proc run`, programmatic submissions, and the unattributed command
fallback for an epic approval whose planner agent session cannot be resolved — are read
back out of that store and rendered here, so work that this process never owned still
shows up on the tab.

The pane defaults to **this session** plus unattributed procs; press `a` to widen it to
every session. Historical `detached` rows remain visible in both modes. The pane title
names the active scope and the running-lane counts, e.g.
`Procs · this session   ⚙ 2  ⚒ 1  ⚙ 1   [4 running · 5 done]`. The blue gear is running
TUI background procs — the same rows the top-bar `bg:` group counts, excluding monitors,
tool-run carriers, and update rows; the sky-blue `⚒` chip is tool-lane procs (an
inventory count, so it shows a dim `⚒ 0` when empty — it can differ from the top-bar run
count because foreground runs have no proc and a joined run has two); the orange gear is
bare monitors. A green `⚙ N` chip appears after the orange chip only while update procs
run, and update rows carry a green `⚙` marker. All counts follow the tab's current
scope, so `a` moves them with the list. A zero blue/orange lane still renders as a dim
`⚙ 0` so a missing chip cannot be read as "unknown". The bracketed totals keep their
current meaning: blue plus tool plus green plus orange equals the running count. Rows
read from the store carry a colored session chip (`ace·sase#14 4f2a`) that matches the
one `sase proc list` prints; a session that has since exited renders dim with a `†`. An
ordinary unattributed proc renders a dim `—`; a historical detached proc carries a cyan
`◆ detached` marker that makes the legacy row kind explicit.

Store reads happen on a worker thread and are revalidated by store mtime about once a
second, so the tab never stats, reads, or locks the store from a render or keystroke
path. Retention is governed by `procs.history_limit` (see
[configuration](reference/config/runtime-and-storage.md#procs)): finished rows and their
logs age out oldest-first, and running procs are never pruned. Because the store owns
that retention, `d` / `D` do not dismiss rows; they only explain the retention policy.

The top-bar `bg:` group's blue chip counts this session's active background procs plus
**every active unattributed proc globally**, including an approved epic that had to use
the unattributed command fallback. Tool-run carriers are counted in `tools:` instead,
running bare monitor turns in the orange chip there, and service procs and oneshots are
left to the Services tab.

### Layout

The tab uses a two-panel layout: a proc list on the left and an output pane on the
right. Running procs refresh their output on the pane's 0.25 s tick while the Procs tab
is visible.

### Opening a row

With the proc list focused, `Enter` or a click opens the first matching destination
below. The hints line can list more than one `⏎:` token when a row qualifies for more
than one action; these are not separate choices, and their display order does not
determine what opens. Jump mode (`'`) selects a row by its hint without opening it.
While jump mode is active, the hints line shows the jump prompt and these opening
actions do nothing.

1. **Command Line** (`command-line` tag). Admin Center closes and the
   [Command Line](#command-line) opens on that block. The hint is `⏎: block`. A missing
   record still opens the panel and says the record was pruned.
2. **Tool run.** The row's `tool-run:<id>` tag wins. If that tag is absent, a
   `tool-run-join:<id>` tag is used. Admin Center stays open and switches to **Tools**,
   focused on that run. The hint is `⏎: run`. This is how a monitor that reserved a run,
   and a monitor that joined one with `sase monitor start -J`, open the run. Those rows
   show `⚒`.
3. **Monitor without a run tag.** When the monitor's agent row is loaded, Admin Center
   closes and the Agents tab reveals that agent. The hint is `⏎: agent`, and only when
   the jump can land. If the agent is not on the Agents tab, sase's TUI says so and
   stays put.

A row that is none of these does not navigate.

### Proc Status Icons

| Icon | Color  | Meaning                                                    |
| ---- | ------ | ---------------------------------------------------------- |
| `◌`  | Dim    | Pending (supervisor starting)                              |
| `●`  | Green  | Running                                                    |
| `✓`  | Cyan   | Success                                                    |
| `✗`  | Red    | Error                                                      |
| `⊘`  | Yellow | Killed                                                     |
| `?`  | Dim    | Unknown                                                    |
| `⚙`  | Orange | Monitor turn (same mark as the Agents tab and the top bar) |
| `⚒`  | Sky    | Tool-run carrier (same mark as the `tools:` group)         |

### Monitors on this tab

A `sase monitor start` supervisor is a durable proc like any other, but this tab marks
it the same way the rest of sase's TUI does. See
[Monitors](reference/automation/monitors.md).

- **Orange `⚙`.** Bare monitor rows carry the orange gear between the status icon and
  the label (`● ⚙ just check-full`), matching the Agents tab and the orange chip in the
  top bar's `tools:` group. A monitor carrying a live run shows `⚒` instead. The same
  mark prefixes the output header.
- **Agent name.** Each monitor names its member agent (`acme--mon`) on the list's
  secondary line (`acme--mon · Working...`) and on an `agent` line in the output header.
- **Status chip.** When the matching agent row is loaded, the effective status label
  (`TESTING` while running, `TESTED` once settled) appears in that pair's accent color
  between the agent name and the secondary text (`acme--mon · TESTING · Working...`),
  and again on the output header's `agent` line.
- **Live `live_reply.md`.** While the Procs tab is active, the 0.25 s tick refreshes the
  selected running proc. For a monitor, that output is the tail of
  `<artifacts_dir>/live_reply.md`: the last 400 lines, including text rotated into
  `live_reply.md.1`. Until that log has text, the pane still shows `Working...`. On the
  Agents tab, the Reply card follows that same file in place when the live-reply follow
  is active; see
  [Agents Tab Main Deck](reference/tui/agents-main-deck.md#agents-tab-main-deck-1).
- **`<enter>`.** A monitor that owns or joined a tool run opens that run (`⏎: run`). A
  monitor without a run tag whose agent is loaded jumps to the Agents tab (`⏎: agent`).
  Command Line rows take precedence over both destinations. See
  [Opening a row](#opening-a-row).
- **Visible in both scopes.** Monitor procs are unattributed, so they appear in both
  **this session** and **all sessions**.
- **`K` stops the supervisor.** Kill uses the named-proc stop path: it stops the
  supervisor, settles the session, and runs any `--next` action.

### Durable Procs

Procs are durable records shared by every SASE surface, not just rows in this pane. They
live in `~/.sase/procs/procs.jsonl`, with one combined stdout/stderr log per proc under
`~/.sase/procs/logs/<proc_id>.log`. Because the records outlive the process that
produced them, `sase proc` can list and inspect work started anywhere — including a
TaskTriage launch or unattributed command submitted from another client.

Each proc carries a 12-character id resolvable by unique prefix (three characters
minimum, like a git short SHA), so `sase proc show k7m2` works. Statuses are `pending`,
`running`, `success`, `error`, and `killed`; terminal states are final, and a proc whose
supervisor died without reporting is reconciled to `error` rather than left running
forever. `sase proc list` reuses the icons above and adds `◌` for pending and `⊘` for
killed.

A proc may also carry a **named proc**: `sase proc run -N/--name NAME` (bare names
resolve beneath the calling sase-agent; `agent/name` is fully qualified) names the proc
so `sase proc show`, `sase proc list -N`, and `sase proc kill` can address it by name
instead of id. Resolution tries an exact fully qualified name, then an exact proc id,
then a unique id prefix. Active uniqueness is scoped per project — starting a proc under
a name already held by an active proc in the same project is a conflict — and a name is
only reusable once the proc holding it settles. A monitor's member agent name (for
example `acme--mon`) is its own named proc.

**Kinds and ownership.**

| Kind       | Typical producer                                          | Owner and scope                                                     |
| ---------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| `tui`      | Work run and mirrored by sase's TUI                       | sase's TUI process; scoped to its session                           |
| `command`  | `sase proc run` or `sase.procs.submit_proc()`             | The proc supervisor; attributed to one session or left unattributed |
| `detached` | Historical rows from retired CLI/API detached submissions | The legacy proc supervisor; global because no session owns the row  |

The programmatic submission API is `sase.procs.submit_proc()`. Pass `session_id=None`
when no interactive session should own the row; it still writes a `command` proc. The
legacy `sase.procs.submit_detached_proc()` wrapper remains for old callers but now
records the same unattributed command row. The public `read_procs()` and
`filter_procs()` helpers accept `kind=` as either one kind or a collection, including
`detached` when a caller needs historical rows. A `command` or historical `detached` row
that remains `pending` without a supervisor PID for 60 seconds is reconciled to `error`;
a mirrored `tui` row is left to its owning TUI. Epic launches record the approving
surface as `ace`, `telegram`, `cli`, or `axe`, with `api` retained as the fallback for
direct or unrecognized API callers.

Session attribution controls which TUI includes a proc by default; the proc still
executes under its own supervisor. Here, a **TUI session** is one running TUI process,
not an agent session. The attribution rules depend on how the proc starts.

A hand-off tool-run proc (`sase tool run -H`, `sase tool run -d`, or the automatic
reservation path) is stamped only when the submitting process is itself a live
registered TUI session, such as a catalog launch started inside sase's TUI. An agent
escalation, a detached run, and a human shell `-H` leave the proc unattributed even when
another TUI is open. There is no latest-session fallback, and a failed session lookup
still submits the proc with no session. Unattributed rows stay visible in **this
session**.

For `sase proc run` and `sase proc list`, `--session` accepts a full session id, a
unique id prefix or short handle, or `current`, `latest`, and `none`. The default
(`current`) uses this process's registered TUI session, then the newest live one, then
no session. This latest-session fallback applies to these proc commands, not to tool-run
hand-offs. `sase proc run --session none` creates an unattributed command row.
`sase proc list` scopes work to the resolved session plus unattributed rows by default,
and widens to every session with `--all`. Rows from a session that has since exited
render dim with a `†` marker.

**Retention.** [`procs.history_limit`](reference/config/runtime-and-storage.md#procs)
caps how many _finished_ procs are kept; pending and running work is never pruned for
being old. Lowering the limit removes the oldest finished rows and their log files.
Finished procs tagged `command-line` (TUI Command Line submissions) keep a separate
bucket of 50 beside this limit. The legacy `tasks.history_limit` key is still honored as
a deprecated alias.

The CLI equivalents are `sase proc list`, `sase proc show ID` (`--follow` to stream),
`sase proc run [--session SESSION|none] -- COMMAND` (`--wait` to stream and inherit the
exit code), and `sase proc kill ID`. A hidden legacy `--kind` filter remains for
historical kind rows. Approved epics normally launch as
[monitor turns](reference/automation/monitors.md); only an unresolvable planner agent
session uses an unattributed command proc. See the
[CLI reference](cli.md#daily-operation).

### Filtering procs

Press `/` to reveal a query bar above the proc list, prefilled with the query already
active. Typing narrows the list live; the status lane shows `N matches` or a parse error
with its exact span. `Enter` commits and returns focus to the list; `Esc` restores the
query that was active when the bar was opened. Unlike the Artifacts panes, the bar is
**hidden when there is no query** and appears — read-only, syntax-highlighted — only
while a filter is active, so an active filter is never invisible without also being
silent. The header gains a `· N/M shown` segment while filtered, and the query survives
closing and reopening the Admin Center in the same session.

Free text (and its explicit `text:` spelling) matches the command string, the row label,
and the retained output; `cmd:` and `out:` narrow to one side. Every key is negatable
with a leading `-`, and a boolean key takes the bare shorthand (`monitor` means
`monitor:true`). The `service` boolean matches service-proc runs (daemon or oneshot),
and `svc:<name>` narrows to one service proc by exact name. `tag:<tag>` matches a proc
tag exactly (for example `tag:command-line` for Command Line runs, visible by default),
and `origin:<origin>` matches the submitting origin (for example `origin:ace`).

The seeded default query is `-service`, so service-proc runs stay hidden unless asked
for; `ace.procs.default_query` in `sase.yml` changes the seed. It applies only when no
committed query is persisted — a user-cleared query stays cleared.

| Key        | Kind     | Meaning                                                        |
| ---------- | -------- | -------------------------------------------------------------- |
| free text  | string   | Command, label, output (implicit AND); same as `text:`         |
| `cmd:`     | string   | Command string only                                            |
| `out:`     | string   | Retained output only (last 32 KB)                              |
| `name:`    | string   | Row label / display name                                       |
| `agent:`   | string   | A monitor row's member agent name                              |
| `project:` | string   | Project key or display name                                    |
| `status:`  | enum     | `pending`, `running`, `settling`, `success`, `error`, `killed` |
| `kind:`    | enum     | `command`, `tui`, `detached`                                   |
| `monitor`  | bool     | A `sase monitor start` named proc                              |
| `service`  | bool     | A service proc run (daemon or oneshot)                         |
| `svc:`     | string   | Service name (exact)                                           |
| `tag:`     | string   | Proc tag (exact, for example `command-line`)                   |
| `origin:`  | string   | Submitting origin (exact, for example `ace`)                   |
| `running`  | bool     | Active and owned by a live session                             |
| `failed`   | bool     | Terminal status is `error` or `killed`                         |
| `exit:`    | int      | Exit code (exact)                                              |
| `min:`     | duration | Runtime at least N seconds (or `5m`, `2h`, `1d`)               |
| `max:`     | duration | Runtime at most N                                              |
| `after:`   | date     | Completed at or after the bound                                |
| `before:`  | date     | Completed at or before the bound                               |
| `since:`   | date     | **Started** at or after the bound                              |
| `until:`   | date     | **Started** at or before the bound                             |
| `limit:`   | host     | Row cap; `all` removes it                                      |

Runtime is `(finished_at or now) - started_at`, so `min:`/`max:` read sensibly for a
still-running proc too. `before:`/`after:` bound **completion** time and `since:`/
`until:` bound **start** time; a running proc has no completion time, so
`before:`/`after:` never match it and `-before:X` includes it. For example,
`"just check" -monitor -min:300` matches non-monitor procs that ran for at least five
minutes and mention `just check` in their command or output.

`m` cycles the `monitor` term through three states without opening the bar for editing:

```
(no monitor term)  →  monitor  →  -monitor  →  (no monitor term)
```

Each press rewrites the query in place, leaving every other term untouched, and never
steals focus from the row list. If the monitor term was the query's last term, the last
press clears the filter and removes the bar.

### Keybindings

| Key                 | Action                                             |
| ------------------- | -------------------------------------------------- |
| `j` / `k`           | Navigate proc list                                 |
| `/`                 | Filter procs                                       |
| `m`                 | Cycle the `monitor` filter                         |
| `'`                 | Jump to a proc row via adaptive hints              |
| `a`                 | Toggle scope: this session / all sessions          |
| `K`                 | Request a kill for a selected active durable proc  |
| `Enter`             | Open the selected monitor's agent                  |
| `d`                 | Explain finished-proc retention (does not dismiss) |
| `D`                 | Explain finished-proc retention (does not dismiss) |
| `e`                 | Open proc output in `$EDITOR`                      |
| `y`                 | Copy proc output to clipboard                      |
| `Ctrl+D` / `Ctrl+U` | Scroll output pane down / up                       |
| `g` / `G`           | Jump output pane to top/bottom                     |
| `Tab` / `Shift+Tab` | Switch Admin Center tabs                           |
| `q` / `Esc`         | Close SASE Admin Center                            |

`K` and `D` also answer to `Shift+K` and `Shift+D`, matching the pane's existing
`Shift+G` convention. `d` and `D` currently perform no dismissal; both explain that
finished rows age out according to `procs.history_limit`.

`K` opens a danger confirmation only for a store-backed row that sase's TUI still
considers active. The backend stops command/named-proc records, including monitor
supervisors. It refuses a TUI-owned record because only its owning sase's TUI session
may stop it, and a legacy record whose supervisor has died is reconciled to `error`
rather than killed. Other ineligible rows explain why: a finished proc reports
`Proc already finished`, a proc still being submitted reports
`Proc is still submitting — try again in a moment`, and a session-local row with no
durable record reports that it cannot be killed from the Procs tab.

## Updates Tab

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
[`sase plugin`](reference/integrations/plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)
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
[Updates tab reference](reference/tui/admin-center.md#updates-tab) for the full keymap
and behavior, [Plugins](reference/integrations/plugins.md) for the equivalent
`sase plugin` CLI, and
[Agent providers](reference/providers/agent-clis.md#inventory-and-updates) for the
equivalent `sase agent-cli` CLI.

The Updates pane still binds `a` to a tracked agents-sidecar publication sync. That
action publishes and reconciles agent hoods for every enabled project; it is not part of
the comprehensive update. See [Agent Hood Synchronization](reference/agents/index.md)
for privacy, publication, status, and recovery behavior.

<a id="snippets"></a> <a id="usage"></a> <a id="snippet-variables"></a>
<a id="capitalized-aliases"></a> <a id="save-location-picker"></a>
<a id="existing-definition-finder"></a>
<a id="authoring-a-snippet-from-the-prompt-bar"></a> <a id="macro-picker"></a> Moved to
[Snippets](reference/tui/snippets.md#snippets-1).

## Auto-Refresh

sase's TUI auto-refreshes data at a configurable interval (default: 10 seconds). The
remaining time until the next refresh is shown in the info panel. Set
`--refresh-interval 0` to disable. Press `R` on Artifacts or Services, or `r` on Agents,
to open the [Refresh panel](reference/tui/agents-tab.md#refresh-panel) and choose a
manual refresh without waiting for the next tick.

Tab switches are instant: cached data is shown immediately while a background refresh
runs asynchronously, so moving between tabs never blocks on disk I/O.

When the inotify-based artifact watcher is active, the periodic tick is
**event-driven**: it consults per-surface dirty flags (`_dirty_patches`,
`_dirty_agents`, `_dirty_axe`) and short-circuits the whole tick when nothing has
changed. Cheap stat-only change tokens also skip unchanged surfaces when no watcher is
available. A 300-second `--sanity-refresh-interval` floor still triggers a full
reconcile to recover from missed events, so a quiet TUI does ~zero work between real
changes without going stale.

Until the initially visible tab is ready — or a 45-second safety timeout fires —
auto-refresh ticks keep probing change tokens but do not collect axe, run a sanity or
broad Agents load, or reload Patches. That hold keeps the first tick from racing the
startup axe init (auto-start / `--restart-axe`) and from competing with the Agents
loader. Hidden-surface loads, the app-wide link index, and other CPU-heavy maintenance
wait for the same release and then run one job at a time.

### Performance Tracing

For diagnosing TUI latency, set `SASE_TUI_TRACE=1` before launching `sase tui`. Tracing
is near-zero-cost when the env var is unset; with it enabled, each instrumented hot path
emits one JSONL line per span to `~/.sase/perf/tui_trace.jsonl` (override via
`SASE_TUI_TRACE_PATH=…`). See
[`docs/contribute/perf-runbook.md`](contribute/perf-runbook.md) for the full span
catalog, benchmark harness, and per-phase performance targets.
