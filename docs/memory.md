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
  block authored as a YAML literal block scalar; generated Tier 2 entries render that
  block verbatim, while single-line surfaces collapse it.
- **Audited memory operations** live under the project state directory and record agent
  reads plus proposed writes and human review decisions.

Use [initialization](init.md#memory-initialization) to create or refresh the files. Use
[`sase memory agent-docs list`](init.md#agent-documents) to inspect `AGENTS.md` and
provider instruction file status. Initialization always generates the short
`sase/memory/sase.md` workspace note. For SASE-managed project repositories it
additionally generates two long notes: the `sase/memory/sase_beads.md` bead reference
listed in Tier 2 of managed agent instructions, plus `sase/memory/sase_sizes.md`
size-scale guidance nested under `sase_beads.md` and surfaced through that note's
`## Children` section on an audited read. Day to day, the usual order is: inspect loaded
context with `sase memory list`, have agents use `sase memory read` for audited
long-term reads, have agents use `sase memory write` only to create proposals, then have
a human approve or reject those proposals with `sase memory review`.

## XPrompt Inclusion

Every valid, flat, non-README note is also available as an explicit `#memory/<stem>`
xprompt reference: `sase/memory/glossary.md` (or the home equivalent) expands with
`#memory/glossary`. The `memory/` prefix is required — there is no bare `#glossary`
alias, and an ordinary xprompt cannot claim the `memory/` namespace. A selected
project's note shadows a same-stem home note using the same first-wins precedence
described in [Audited Reads](#audited-reads) below.

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
In a normal human shell, use regular file reads instead of this audited command unless
you are intentionally simulating an agent identity.

Pass `--include proposals` to include memory proposal and review ledger events in the
same audit dashboard. Path and agent filters also apply to proposal target paths and
proposal/review actors.

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
