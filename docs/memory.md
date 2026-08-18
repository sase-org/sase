# Memory

SASE memory is durable context that survives individual agent chats. Project notes live
as Markdown files directly under `sase/memory/`; home notes live under `~/sase/memory/`.
Each non-README note declares its tier in YAML frontmatter:

- **Short-term memory** uses `type: short`. It is always-loaded instruction context:
  `sase memory init` inlines each short-term note into the
  `## 1. Tier 1 (short-term) Memory` block of the managed `AGENTS.md`; generated section
  numbers span the whole document (e.g. `### 1.1 Build & Run Commands (build_and_run)`
  and `#### 1.1.1 IMPORTANT: Two-Speed Verification`) when the root opts in with
  project-local `is_sase_managed: true`. `memory.h1_title` optionally customizes the
  generated title. The retired `memory.enabled` key no longer authorizes management.
- **Long-term memory** uses `type: long`. It is reference context, requires
  `description` frontmatter, and can set `parent: sase/memory/<note>.md` to appear under
  another long note's `## Children` section. A long note description may be a Markdown
  block authored as a YAML literal block scalar; that block renders verbatim as the body
  of the note's numbered Tier 2 section, while single-line surfaces collapse it.
- **Audited memory operations** live under the project state directory and record agent
  reads plus proposed writes and human review decisions.

Use [initialization](init.md#memory-initialization) to create or refresh the files. Use
[`sase memory agent-docs list`](init.md#agent-documents) to inspect `AGENTS.md` and
provider instruction file status. Initialization always generates the short
`sase/memory/sase.md` workspace note and the short `sase/memory/task_types.md` catalog
note (agent-creatable types, their `when_to_use` text, and field names). For
SASE-managed project repositories it additionally generates two long notes: the
`sase/memory/sase_beads.md` bead reference listed in Tier 2 of managed agent
instructions, plus `sase/memory/sase_sizes.md` size-scale guidance nested under
`sase_beads.md` and surfaced through that note's `## Children` section on an audited
read. The project-root task-type note and `sase/task_types.json` snapshot render from
the committed catalog (builtins, `plugins.required` types, and `bead.task_types`); the
home-root note renders from the builtin catalog only. Day to day, the usual order is:
inspect loaded context with `sase memory list`, have agents use `sase memory read` for
audited long-term reads, have agents use `sase memory write` only to create proposals,
then have a human approve or reject those proposals with `sase memory review`.

## XPrompt Inclusion

Every valid, flat, non-README note is also available as an explicit `#memory/<stem>`
xprompt reference: `sase/memory/sase_beads.md` (or the home equivalent) expands with
`#memory/sase_beads`. The `memory/` prefix is required — there is no bare `#<stem>`
alias, and an ordinary xprompt cannot claim the `memory/` namespace. A selected
project's note shadows a same-stem home note using the same first-wins precedence
described in [Audited Reads](#audited-reads) below. Project glossary terms are not a
memory note and have no `#memory/glossary` form; fetch a definition on demand with
`sase glossary read`, covered in [Glossary](#glossary) below.

This is explicit, launch-time prompt composition, not an audited lookup: expanding
`#memory/<stem>` strips frontmatter and inlines the note body but does not append the
`## Children` section, and never writes a `sase memory read` audit event. Use
`sase memory read` (below) when an already-running agent needs to consult long-term
memory on its own and have that access recorded. It is not a restoration of the retired
dynamic-memory runtime — there is no keyword matching, prompt scanning, or automatic
context injection. See [Memory Field](xprompt.md#memory-field) for the full expansion
contract and [Memory Order](content_layout.md#memory-order) for source precedence.

## Inspect Context

`sase memory` and `sase memory list` render the memory files visible from the current
directory:

```bash
sase memory
sase memory list
```

The dashboard separates:

- `loaded` files reached by transitive `@...` references from `AGENTS.md` in the project
  or home context. Provider instruction files (`CLAUDE.md`, `GEMINI.md`, …) are full
  copies of `AGENTS.md`; they are reported as instruction roots but are not separate
  traversal roots for this dashboard.
- `referenced` files mentioned by plain `sase/memory/...` text or by audited
  `sase memory read` instructions, but not loaded.
- `available` files present under project or home `sase/memory/` but unreachable from
  the current launch context.
- `missing` referenced files that do not exist.

Approximate token counts are included so large instruction surfaces are visible before
an agent launch.

## Show a Note

`sase memory show <memory-relative-path>` resolves and prints a long-term memory note
the same way `sase memory read` does, minus the audit event:

```bash
sase memory show generated_skills.md
sase memory show sase_beads.md -f rich
sase memory show cli_rules.md -f json
```

Path resolution is identical to `read`: project `sase/memory/` first, then
`~/sase/memory/`, and only `type: long` notes are accepted. Leading YAML frontmatter is
stripped, and a `## Children` section (or, in `rich`, a `Children` block) is appended
when the note has nested long-term children. `-f/--format` selects `markdown` (the
default, byte-identical to `read`'s stdout for the same note), `rich` (a styled terminal
view), or `json` (a structured payload with `project`, `origin`, `note`, and
`children`). No audit event is written and no agent identity is required.

## Audited Reads

Agents should read long-term memory through `sase memory read` so the access is
attributable:

```bash
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --agent agent-a
sase memory log --id <read-id>
```

The read argument remains relative to the selected project or home memory root, so
callers pass `generated_skills.md`, not `sase/memory/generated_skills.md`. It accepts
long-term notes (`type: long`). Short-term notes are excluded because they are intended
to arrive through instruction loading rather than ad hoc reads. The command strips one
leading YAML frontmatter block from stdout and appends a `## Children` section when the
note has nested long-term children. The audit event records metadata such as path, agent
name, timestamp, cwd, byte count, and reason.

Every read requires a non-empty reason via `-r` or `--reason` and agent attribution from
`SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json` (`name`,
`workflow_name`, or `agent_name`). Unattributed reads fail instead of writing the log.
Agents should always use `read`, not `show`, when consulting memory to accomplish a
task; nothing is printed unless the read was recorded.
[`sase memory show`](#show-a-note) is the supported way for a human shell to view a
note.

Pass `--include proposals` to include memory proposal and review ledger events in the
same audit dashboard. Path and agent filters also apply to proposal target paths and
proposal/review actors.

## Glossary

Project glossary entries authored under `memory.glossary` in `sase/sase.yml` (see
[glossary configuration](configuration.md#memoryglossary)) are not rendered into an
always-loaded memory note. `sase memory init` instead renders a compact `Glossary Terms`
H3 section at the end of Tier 2 — after the `Long-Term Memory Files` H3 — that names
every term with its aliases in parentheses. Agents fetch a definition on demand with the
`sase glossary` command group:

```bash
sase glossary list
sase glossary list hood -f names
sase glossary show "Agent Hood"
sase glossary show Stitch -d 0 -f markdown
sase glossary read "Agent Hood" -r "Need the hood/agent distinction"
sase glossary log
sase glossary log -t Stitch -a agent-a
sase glossary add "Test Term" "A test term that references Agent Hood." -a tt
sase glossary del "Test Term"
sase glossary del tt -n
```

`sase glossary` with no subcommand defaults to `sase glossary list`. Every subcommand
accepts `-p/--project REF` (a project key, display name, or alias) before or after the
subcommand name.

Without `-p`, the project is inferred from the current directory the same way
`sase repo`, `sase workspace`, and `sase memory` do: a path inside the project's
ProjectSpec workspace (the primary checkout), a numbered managed workspace whose
`.sase/checkout.json` marker identifies an enabled project, or the workspace-provider
and sibling-workspace backstops. If none of those match an enabled project, the command
exits 1 with `no enabled project matched the active workspace; pass -p/--project`.

`sase glossary list [PATTERN]` prints the terms configured for a project. `PATTERN` is
an optional case-insensitive substring match against each term and its display aliases;
`-d/--definitions` extends the match into definition bodies. `-f/--format` selects
`table` (the default, with term, aliases, reference count, and a summary), `names` (one
canonical term per line, pipe-friendly), or `json` (full records including aliases,
definition, reference terms, and source location).

`sase glossary show TERM [TERM ...]` resolves one or more terms — by canonical term,
alias, or an unambiguous prefix — and prints each definition plus the recursive closure
of terms its definition depends on. Every related term shows why it appeared: which
requesting term's definition mentioned it, and the exact matched phrase. `-d/--depth N`
caps the recursion (`-d 0` prints only the requested terms; the default is unlimited).
`-f/--format` selects `rich` (the default terminal rendering), `markdown` (plain
Markdown for pasting into a prompt), or `json` (the closure with full provenance). An
unresolvable term exits 1 with near-miss candidates.

`sase glossary read TERM [TERM ...] -r/--reason TEXT` is identical to `show` in every
other respect, except it requires a non-empty reason and records an audited read before
printing — the same audited-read discipline as [`sase memory read`](#audited-reads).
Agents should always use `read`, not `show`, when consulting the glossary to accomplish
a task; nothing is printed unless the read was recorded. Reads are attributed the same
way as memory reads (`SASE_AGENT_NAME`, `SASE_AGENT`, or
`SASE_ARTIFACTS_DIR/agent_meta.json`), and each event records the requested terms, every
related term the closure added, the depth limit, and the total bytes of definition
served. The read also appears in the `GLOSSARY` lane of the agent metadata panel in
[ACE](ace.md#agents-tab-metadata-panel).

`sase glossary log` summarizes recorded reads: with no selector, a dashboard shows
totals plus by-term and by-agent breakdowns and recent events. `-t/--term` and
`-a/--agent` filter the event set, and both are echoed in the dashboard header so a
filtered view is never mistaken for the whole log. `-i/--id READ_ID` selects one event
by id or unambiguous prefix and prints its full detail. `-f/--format json` emits
deterministic JSON for both the summary and the single-event view.

`sase glossary add TERM DEFINITION [-a ALIAS]...` writes a new entry into the project's
`sase/sase.yml` after the same Rust validation that rejects duplicate terms and
colliding aliases. Required values are positionals; `-a/--alias` may be repeated. The
term is inserted so the glossary map stays sorted. On success the command prints the
project display name, the term, its aliases, and the config path written.
`-f/--format json` emits a stable object with the same fields plus `created_section`.

`sase glossary del TERM` resolves `TERM` through the same alias, slug, and unique-prefix
lookup as `show` and `read`, then removes that entry. It is non-interactive: instead of
a prompt it prints the exact `sase glossary add …` restore command, the inbound
reference count, and the written config path. `-n/--dry-run` prints that same block and
exits without writing. Copy-pasting the restore command is the undo.

Both write commands regenerate the project's agent instruction files in-process after a
successful write (`AGENTS.md` and the provider shims) so the new or removed term is
visible to agents. `-I/--no-init` skips that step. A regeneration failure is reported as
a warning and does not roll back the config write; run `sase memory init` by hand if
that happens.

ACE's Glossary panel uses the same add/delete engine. From a prompt, press `gG` or
`Ctrl+G G` to browse terms, follow relations, cycle projects, and add or delete entries;
see [Glossary panel](ace.md#glossary-panel).

## Propose Memory

Agents do not write canonical long-term memory files directly. They create proposals:

```bash
sase memory write \
  --title "Generated skills" \
  --slug generated_skills \
  --evidence "$(sase repo path research)/skills.md" \
  --body "Durable memory body" \
  --notify

cat draft.md | sase memory write \
  --title "Generated skills" \
  --target generated_skills.md \
  --from-chat abc123
```

`sase memory write` is the agent-side authoring path. It writes proposal state only
under `~/.sase/projects/<project>/`; it never modifies canonical memory files. A
proposal needs:

- `--title`
- exactly one of `--slug <slug>` or `--target <slug>.md`
- at least one non-note evidence item
- body content from `--body`, `--file <path>`, `--file -`, or piped stdin when neither
  `--body` nor `--file` is supplied

Use `--file -` when a wrapper needs the explicit `--file` form but should still pass the
body on stdin.

Targets must be one-level long-memory paths such as `generated_skills.md`; slugs must
match `[a-z0-9][a-z0-9_-]*`. Evidence can be a path, `chat:<id>`, `--from-chat <id>`,
`url:<url>`, a bare HTTP(S) URL, or a supplemental `note:<text>`. Note-only evidence is
rejected.

Proposal bodies must be non-empty UTF-8 and at most 256 KiB. Bodies above 16 KiB produce
a warning unless `--allow-large` is passed. Prompt-injection-like text is also recorded
as a warning for the reviewer.

Proposal authors are attributed from the same agent identity sources as audited reads.
`--manual-author` exists for tests and demos; normal agent writes should rely on the
SASE-provided identity.

Use `--notify` to best-effort append a `memory.proposed` notification after proposal
creation. The notification carries the `memory` tag, attaches any evidence paths that
resolved to local files, and opens the interactive memory review TUI at that proposal
when selected in ACE. The notification is only a prompt to review; it does not approve,
reject, or edit the proposal by itself. Notification delivery is reported in the human
output and as `notification_id` in JSON output.

Use `--json` for deterministic machine-readable output.

## Review Proposals

Humans review proposals with `sase memory review`:

```bash
sase memory review                         # interactive TUI on a TTY
sase memory review --list
sase memory review --list --all --json
sase memory review <proposal-id> --show
sase memory review <proposal-id> --approve
sase memory review <proposal-id> --edit
sase memory review <proposal-id> --approve --edited-file edited.md
sase memory review <proposal-id> --reject --reason "Too speculative"
```

A bare `sase memory review` opens the Textual review app when stdin/stdout are TTYs. In
non-interactive shells it prints the pending list instead. `--list` and `--show` are
inspection commands; `--approve`, `--edit`, and `--reject` are the human promotion
decisions. Proposal ids can be abbreviated when the prefix is unambiguous.

Agents cannot approve, edit-approve, or reject proposals: those actions fail when agent
identity is present in `SASE_AGENT_NAME`, `SASE_AGENT`, or
`SASE_ARTIFACTS_DIR/agent_meta.json`. Human review events record the local user and
hostname. `--edit` opens `$VISUAL` or `$EDITOR`, then approves the edited body.

Approval writes the canonical file under the current repo's `sase/memory/` path and
prepends frontmatter:

```yaml
---
type: long
parent: AGENTS.md
description: Generated skills
source_candidate: mem-20260523-142233-a1b2c3d4
---
```

Approval refuses to overwrite an existing target. Use `--target <slug>.md` to approve
into a different unused one-level target, `--edit` to open `$VISUAL`/`$EDITOR` before
approving, or `--edited-file` for non-interactive edited approval.

If approved memory should be loaded every time, add an explicit `@sase/memory/<note>.md`
reference from the appropriate instruction file.

Legacy project `memory/` and home `~/memory/` trees remain readable to migration tooling
during the compatibility window. Canonical and legacy trees are exclusive: non-identical
coexistence blocks initialization instead of merging context. See
[Canonical SASE Content Layout](content_layout.md#compatibility-and-collisions).

## Review TUI

The interactive review app shows pending proposals, evidence, target status, diffs
against existing files, warnings, and audit events. Keybindings:

| Key         | Action                                         |
| ----------- | ---------------------------------------------- |
| `j` / `k`   | Move through pending proposals                 |
| `Down`/`Up` | Move through pending proposals                 |
| `g` / `G`   | Jump to first / last proposal                  |
| `/`         | Filter by id, title, author, target, or status |
| `Enter`/`d` | Toggle detail view                             |
| `Esc`       | Return from detail view                        |
| `a`         | Approve as-is                                  |
| `e`         | Edit in `$VISUAL`/`$EDITOR`, then approve      |
| `r`         | Reject with a required reason                  |
| `t`         | Override the approval target                   |
| `y`         | Copy the proposal id                           |
| `q`         | Quit                                           |

The proposal ledger is append-only JSONL with a lock sidecar. Malformed rows are skipped
when reading, and every review action appends a new event rather than mutating previous
events.
