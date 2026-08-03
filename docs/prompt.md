# Prompt History

Prompts you launch with `sase run` or from [ACE](ace.md) are recorded in prompt history when they are useful to replay.
Normal launch writes skip prompts shorter than five words (terse scraps like `y`, `ok`, or `fix the bug` are not worth
replaying), while recovery paths — and a few launch surfaces that opt in with `allow_short` — can still preserve a short
submitted prompt when a launch fails. Current installs write monthly JSON shards under
`~/.sase/prompt_history/YYMM.json`, with unparseable last-used timestamps grouped into `unknown.json`. If an old
`~/.sase/prompt_history.json` file is found before a shard directory exists, it is migrated on first read or write and
kept as a `legacy-imported-<timestamp>.json.bak` backup inside the shard directory. The `sase prompt` command group is
the first-class way to inspect, search, reuse, curate, and clean up that history. It is built to feel like a well-made
shell-history tool: fast to scan, exact when printing text, safe around destructive actions, and scriptable through
stable JSON.

`sase prompt` reads and writes those JSON shards directly - there is no separate database to manage. Readers aggregate
and deduplicate records across shards, so reusing the same prompt in a later month still shows one newest entry even if
older shard copies remain on disk. New launch recordings only touch the current-month shard. Maintenance commands such
as `delete` and `prune` remove every stored copy of the selected exact prompt text. Replay commands (`run`, `edit`,
`select`) route through the same launch machinery as `sase run`, so multi-prompt, multi-model, and xprompt behavior stay
identical.

## Selectors

Prompts are addressed by a **stable content ID** derived from the exact prompt text, not by a recency index that would
change every time you launch something new:

- `ph_<sha256[:12]>` — the canonical ID printed by `sase prompt list`.
- A bare hash prefix (for example `8f3a9c0d`) — any unambiguous leading slice of the SHA-256 digest.
- `sha256:<full_hash>` — the fully qualified digest when you need to be unambiguous.

If a short prefix matches more than one prompt, the command prints the colliding IDs and asks for a longer selector.
Adding newer prompts never changes an existing prompt's ID.

## Command Inventory

| Command              | Purpose                                                                              |
| -------------------- | ------------------------------------------------------------------------------------ |
| `sase prompt list`   | List recent prompts as a Rich table (default) or stable JSON (`-j`).                 |
| `sase prompt show`   | Print one prompt as raw text, Markdown, or JSON.                                     |
| `sase prompt search` | Find prompts matching a query across the canonical agents archive and local history. |
| `sase prompt stats`  | Summarize the store: counts, size, length percentiles, largest prompts, top chips.   |
| `sase prompt copy`   | Copy a prompt's exact text to the system clipboard.                                  |
| `sase prompt run`    | Replay a stored prompt through the normal launch path.                               |
| `sase prompt edit`   | Open a stored prompt in the editor, then launch the edited text.                     |
| `sase prompt select` | Pick a prompt with an `fzf` picker, then launch it.                                  |
| `sase prompt doctor` | Read-only health report for the store (parseability, duplicates, oversized, …).      |
| `sase prompt delete` | Remove exactly one prompt by selector.                                               |
| `sase prompt prune`  | Remove prompts by objective criteria (`--keep`, `--before`, `--cancelled`).          |
| `sase prompt save`   | Save a prompt as a reusable [xprompt](xprompt.md) markdown file.                     |
| `sase prompt export` | Export a prompt to stdout or a local file; `--sdd` is a retired compatibility flag.  |

`list`, `show`, `search`, `stats`, and `doctor` are read-only. `list`, `search` (default `compact` format), `stats`, and
`doctor` never print full prompt text — they show previews only — so they stay bounded even on a history with thousands
of entries. `show`, `export`, `copy`, and `search -f json|full` are the intentional full-text escape hatches.

Run `sase prompt <command> --help` for the full flag list of any subcommand.

## Search

`sase prompt list -q` filters the **local history only**. `sase prompt search` is the broader tool: it searches **two
stores at once** and ranks canonical archived prompts first, so it answers "I remember a prompt about X — find it,
whether it was archived from an agent run or just ran once last month."

- **Canonical agents archive** — prompts published by agent-backed commits and approved planner runs in the agents
  sidecar under `prompts/<YYYYMM>/`. Search resolves the current project's archive the same way `sase agent prompts`
  does, reads each entry's primary body, and ranks these curated records first. For a commit publication that body is
  the pre-expansion XPrompt; for an approved planner publication it is the dry-expanded plan snapshot.
- **Local prompt history** — the machine-wide `~/.sase/prompt_history/` shard store: every prompt ever submitted on this
  machine, across all repos.

Use `sase agent prompts list` and `sase agent prompts validate` to inspect or validate the canonical archive directly.
`sase agent prompts show <prompt>` prints the archived Markdown document.

Matching is a **case-insensitive substring** test of the literal query (no regex or globbing) against these searchable
fields: title, body, locator/ID, archive path, plan label, and tags. Each hit can therefore report _why_ it matched.
Results are ranked deterministically: archive before local, a title/locator/path hit before a body-only hit, newer
before older, with a stable tiebreak so output is byte-identical across runs. `search` is **read-only**: it never writes
or locks either store, so it is safe to run against a corrupt or unreadable history.

```bash
sase prompt search auth                  # both stores, compact, most-relevant first
sase prompt search auth -s archive       # only canonical archived prompts
sase prompt search auth -s sdd           # deprecated alias for -s archive
sase prompt search auth -s local -x      # only cancelled local prompts
sase prompt search auth -t review        # only prompts tagged "review" (repeatable; ORs)
```

### Output is bounded by default

The local history can hold tens of thousands of entries, so `search` shows the **20 best matches by default** and never
silently truncates — every format reports the full match count, and `-n 0` returns an unlimited result set.

`-f compact` (default) groups hits by source under dim `── Archived prompts (N) ──` / `── Local history (N) ──` headers,
prints one entry per hit with the matched term highlighted plus a one-line snippet (or a `plan: "…"` / `tag: "…"` line
when the match was off-body), and ends with a footer such as `27 matches (3 archive · 24 local) · showing 20`.

`-f json` emits a stable, never-colored envelope — `query`, `count`, `total`, per-source `counts`, and a `results` array
carrying the full prompt `text` — so editors and scripts can build on it. `count` versus `total` makes truncation
explicit:

```bash
sase prompt search auth -f json | jq '.total, (.results | length)'
```

`-f full` prints each hit completely, divider-separated: a **local** hit reuses the exact `sase prompt show -f markdown`
rendering, and an **archived** hit shows its available path, `plan`, artifact-count, tag, and local-history metadata
plus the primary archive body with the match highlighted.

### Filtering by date, tag, source, and status

- `-a|--after` / `-b|--before` keep prompts within an inclusive date window. Both accept `2026-06-01`, `202606`
  (`YYYYMM`), `260601` (`YYmmdd`), a full `260601_143000` SASE timestamp, or a relative offset `30d` / `2w` / `6m` /
  `1y`; an unparseable date is a usage error. Archived prompts are dated by archive frontmatter first, falling back to
  the `YYYYMM` path segment, then the file mtime; local prompts use their last-used time.
- `-t|--tag` keeps prompts carrying a matching tag — archived `prompt_tags` frontmatter plus the embedded `#xprompt`
  chips parsed from the prompt body. Low-signal runner-control `%` directives (`%model`, `%id`, `%wait`, …) are
  execution mechanics, not content tags, so they are deliberately excluded. Repeats OR together (`-t review -t auth`
  matches either).
- `-s|--source` scopes to `archive`, `local`, or `all` (default). The deprecated `sdd` spelling remains as an alias for
  `archive` for one compatibility window.
- `-x|--cancelled` restricts **local** results to cancelled prompts; it has no effect on archived prompts, which have no
  cancelled state.
- `-c|--color` is `auto` (colorize on a TTY unless `NO_COLOR` is set), `always`, or `never`; JSON is never colored.

An empty or whitespace-only query is a usage error (exit `2`). A query that matches nothing is **not** an error (exit
`0`): `compact`/`full` print `No prompts match "<query>".` and `json` returns an envelope with `count: 0`. When `-s all`
finds the same authored prompt in both stores after normalizing whitespace and canonical-archive xprompt links, the
local copy collapses into the archive hit, annotated `also in local history`.

## Common Workflows

### Find a recent prompt

`list` defaults to the 20 most recent non-cancelled prompts, newest first. Narrow it with a case-insensitive substring
filter:

```bash
sase prompt list
sase prompt list -q auth          # only prompts whose text contains "auth"
sase prompt list -l 50            # widen the window to 50 entries
sase prompt list -j               # stable JSON for scripts and editor integrations
```

The table shows the prompt ID, last-used time, status, character count, project/xprompt/directive hint chips, and a
one-line preview — never the full text.

### Print raw prompt text

`show -f raw` writes the exact bytes of the prompt with no added or stripped newline, so it is safe in command
substitution or a pipe:

```bash
sase prompt show ph_8f3a9c0d12ab -f raw
sase prompt show ph_8f3a9c0d12ab -f raw | wc -c
sase prompt show ph_8f3a9c0d12ab -f markdown   # metadata header + body
sase prompt show ph_8f3a9c0d12ab -f json       # metadata + full text
```

### Rerun a prompt, optionally editing first

```bash
sase prompt run ph_8f3a9c0d12ab            # launch the exact prompt
sase prompt run ph_8f3a9c0d12ab -e         # open in the editor, then launch
sase prompt edit ph_8f3a9c0d12ab           # memorable alias for edit-before-launch
```

`edit` (and `run -e`) abort cleanly without launching if you save an empty buffer.

### Replay under another VCS prefix

`--prefix` reuses the existing VCS-tag replacement logic, so a prompt captured under one workspace can be replayed under
another without retyping it. Prefix replacement happens before the editor opens, so what you see is what will run:

```bash
sase prompt run ph_8f3a9c0d12ab -P "#gh:bob-cli"     # reuse a "#gh:sase" prompt elsewhere
sase prompt edit ph_8f3a9c0d12ab -P "#gh:bob-cli"    # adjust details after re-prefixing
```

This is the shared, drift-free implementation behind the `sase run "#vcs:ref ."` compatibility path.

### Pick interactively with fzf

```bash
sase prompt select                 # fzf over launched prompts, newest first
sase prompt select -q auth -e      # filter to "auth", edit the choice, then launch
sase prompt select -a              # include cancelled prompts as candidates
```

If `fzf` is not installed, `select` points you at `sase prompt list` and `sase prompt run` instead of failing silently.

### Recover a cancelled prompt

Prompts you typed but did not launch (or whose launch failed) are stored as **cancelled** so you can recover them. They
are hidden by default:

```bash
sase prompt list -c                # only cancelled prompts
sase prompt list -a                # launched and cancelled together
sase prompt run ph_8f3a9c0d12ab    # relaunch a recovered prompt by ID
```

### Delete a secret

If a prompt captured something sensitive, remove exactly that one prompt. `delete` confirms on a TTY unless you pass
`--yes`; in a non-interactive shell it refuses to act without `--yes`:

```bash
sase prompt delete ph_8f3a9c0d12ab        # confirms before removing
sase prompt delete ph_8f3a9c0d12ab -y     # skip the prompt (e.g. in scripts)
```

Because IDs are content-addressed, deleting a prompt removes every stored copy of that exact text.

### Prune cancelled or old prompts

`prune` cleans up by objective criteria. Predicates intersect, and `--keep` is a hard floor that always preserves the
newest N entries. Always preview with `--dry-run` first:

```bash
sase prompt prune -c --dry-run            # show which cancelled prompts would go
sase prompt prune -c -y                   # remove all cancelled prompts
sase prompt prune -k 500 -y               # keep only the 500 newest prompts
sase prompt prune -b 2026-01-01 --dry-run # preview removing entries older than a date
```

`--before` accepts `YYYY-MM-DD`, `YYmmdd`, or a full `YYmmdd_HHMMSS` SASE timestamp. A dry run never mutates the store,
and neither `delete` nor `prune` will rewrite a corrupt or unreadable store.

### Save a prompt as a reusable xprompt

Bridge a useful one-off prompt into a durable [xprompt](xprompt.md) so you can trigger it with `#name`:

```bash
sase prompt save ph_8f3a9c0d12ab -n fix-auth-review -t review
sase run "#fix-auth-review"               # the existing loader resolves it

sase prompt save ph_8f3a9c0d12ab -g       # write to ~/sase/xprompts/ instead of project sase/xprompts/
sase prompt save ph_8f3a9c0d12ab -p bob   # namespace under ~/sase/xprompts/bob/
```

With no `--name`, `save` derives a deterministic slug from the prompt preview. It never overwrites an existing xprompt
file unless you pass `--force`.

For drafts that have not been submitted to prompt history yet, ACE's prompt bar can save directly to xprompt storage:
use `gx` in prompt NORMAL mode, or use either `Ctrl+G x` or `Ctrl+G Ctrl+X` in INSERT or NORMAL mode. The unified save
panel starts in xprompt mode; press `Ctrl+X` there to switch to snippet mode and choose which config file should hold
the new `ace.snippets` entry. Thus `Ctrl+G Ctrl+X Ctrl+X` opens the panel and immediately selects snippet mode.
Prompt-input `Ctrl+T` remains completion. If the prompt bar contains a stack, ACE saves the non-empty panes as one
`---`-separated xprompt body, while snippet mode saves only the active pane.

### Export a prompt to a file

`export` is a local-history escape hatch. It prints a stored prompt byte-exactly, wraps it in metadata frontmatter, or
writes either form to an arbitrary path. It does not create canonical archive entries: archived prompts come from agent
runs with captured provenance in the agents sidecar. The old `--sdd` flag remains parseable only so it can fail with an
actionable message naming `--out` and `sase agent prompts`.

```bash
sase prompt export ph_8f3a9c0d12ab -o prompt.md    # write to an arbitrary path
sase prompt export ph_8f3a9c0d12ab -m              # stdout, wrapped in frontmatter
sase prompt export ph_8f3a9c0d12ab                 # stdout, byte-exact (like show -f raw)
sase prompt export ph_8f3a9c0d12ab -s              # exits with retired-flag guidance
```

Existing destination files are never silently overwritten — pass `--force` to replace one.

## Health and Scripting

`doctor` is a read-only diagnostic that never echoes full prompt text. It reports the shard directory path, aggregate
store size, shard count, and parseability; entry and cancelled counts; invalid or duplicate entries; oversized prompts;
prompts shorter than the five-word recording minimum that were saved through recovery paths; and whether `fzf` and a
clipboard command are available:

```bash
sase prompt doctor          # pretty report
sase prompt doctor -j       # stable JSON for editor integrations
sase prompt stats           # length percentiles, largest prompts, top chips
sase prompt stats -j
```

The `-j` JSON output of `list`, `stats`, and `doctor` uses a stable schema and degrades cleanly under `NO_COLOR` or when
piped to a non-TTY, making it safe to build tooling on top of.
