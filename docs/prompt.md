# Prompt History

Every prompt you submit to `sase run` (and every launch started from [ACE](ace.md)) is recorded in the prompt-history
store at `~/.sase/prompt_history.json`. The `sase prompt` command group is the first-class way to inspect, search,
reuse, curate, and clean up that history. It is built to feel like a well-made shell-history tool: fast to scan, exact
when printing text, safe around destructive actions, and scriptable through stable JSON.

`sase prompt` reads and writes the existing JSON store directly — there is no separate database to manage. Replay
commands (`run`, `edit`, `select`) route through the same launch machinery as `sase run`, so foreground, `--daemon`,
multi-prompt, multi-model, and xprompt behavior stay identical.

## Selectors

Prompts are addressed by a **stable content ID** derived from the exact prompt text, not by a recency index that would
change every time you launch something new:

- `ph_<sha256[:12]>` — the canonical ID printed by `sase prompt list`.
- A bare hash prefix (for example `8f3a9c0d`) — any unambiguous leading slice of the SHA-256 digest.
- `sha256:<full_hash>` — the fully qualified digest when you need to be unambiguous.

If a short prefix matches more than one prompt, the command prints the colliding IDs and asks for a longer selector.
Adding newer prompts never changes an existing prompt's ID.

## Command Inventory

| Command              | Purpose                                                                            |
| -------------------- | ---------------------------------------------------------------------------------- |
| `sase prompt list`   | List recent prompts as a Rich table (default) or stable JSON (`-j`).               |
| `sase prompt show`   | Print one prompt as raw text, Markdown, or JSON.                                   |
| `sase prompt stats`  | Summarize the store: counts, size, length percentiles, largest prompts, top chips. |
| `sase prompt copy`   | Copy a prompt's exact text to the system clipboard.                                |
| `sase prompt run`    | Replay a stored prompt through the normal launch path.                             |
| `sase prompt edit`   | Open a stored prompt in the editor, then launch the edited text.                   |
| `sase prompt select` | Pick a prompt with an `fzf` picker, then launch it.                                |
| `sase prompt doctor` | Read-only health report for the store (parseability, duplicates, oversized, …).    |
| `sase prompt delete` | Remove exactly one prompt by selector.                                             |
| `sase prompt prune`  | Remove prompts by objective criteria (`--keep`, `--before`, `--cancelled`).        |
| `sase prompt save`   | Save a prompt as a reusable [xprompt](xprompt.md) markdown file.                   |
| `sase prompt export` | Export a prompt to stdout, a file, or an [SDD](sdd.md) snapshot.                   |

`list`, `show`, `stats`, and `doctor` are read-only. `list`, `stats`, and `doctor` never print full prompt text — they
show previews only — so they stay bounded even on a history with thousands of entries. `show`, `export`, and `copy` are
the intentional full-text escape hatches.

Run `sase prompt <command> --help` for the full flag list of any subcommand.

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
sase prompt run ph_8f3a9c0d12ab -d         # launch as a detached background agent
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
sase prompt select -q auth -e -d   # filter to "auth", edit the choice, launch in daemon mode
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

sase prompt save ph_8f3a9c0d12ab -g       # write to ~/.xprompts/ instead of ./.xprompts/
sase prompt save ph_8f3a9c0d12ab -p bob   # namespace under ~/.config/sase/xprompts/bob/
```

With no `--name`, `save` derives a deterministic slug from the prompt preview. It never overwrites an existing xprompt
file unless you pass `--force`.

### Export a prompt to SDD

`export` snapshots a prompt as a committed artifact. `--sdd` writes under `sdd/prompts/YYYYMM/` with provenance
frontmatter (ID, hash, timestamps, status, and source) and a filename built from a clean preview slug plus the prompt
ID:

```bash
sase prompt export ph_8f3a9c0d12ab -s              # SDD snapshot under sdd/prompts/YYYYMM/
sase prompt export ph_8f3a9c0d12ab -o prompt.md    # write to an arbitrary path
sase prompt export ph_8f3a9c0d12ab -m              # stdout, wrapped in frontmatter
sase prompt export ph_8f3a9c0d12ab                 # stdout, byte-exact (like show -f raw)
```

Existing destination files are never silently overwritten — pass `--force` to replace one.

## Health and Scripting

`doctor` is a read-only diagnostic that never echoes full prompt text. It reports the store path, size, and
parseability; entry and cancelled counts; invalid or duplicate entries; oversized prompts; very short prompts saved
through recovery paths; and whether `fzf` and a clipboard command are available:

```bash
sase prompt doctor          # pretty report
sase prompt doctor -j       # stable JSON for editor integrations
sase prompt stats           # length percentiles, largest prompts, top chips
sase prompt stats -j
```

The `-j` JSON output of `list`, `stats`, and `doctor` uses a stable schema and degrades cleanly under `NO_COLOR` or when
piped to a non-TTY, making it safe to build tooling on top of.
