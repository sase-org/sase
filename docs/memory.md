# Memory

SASE memory is durable context that survives individual agent chats. Project notes live
as Markdown files directly under `sase/memory/`; home notes live under `~/sase/memory/`.
Each non-README note declares its tier in YAML frontmatter:

- **Core memory** uses `type: core`. It is always-loaded instruction context:
  `sase memory init` inlines each core note into the `## 1. Tier 1 (core) Memory` block
  of the managed `AGENTS.md`; generated section numbers span the whole document (e.g.
  `### 1.1 SASE = Structured Agentic Software Engineering (sase)` and
  `#### 1.1.1 SASE Memory`) when the root opts in with project-local
  `is_sase_managed: true`. A core note may set `priority:` to a non-negative integer;
  the default is `20`, lower values render earlier, and ties break by path. The
  generated `sase/memory/sase.md` note uses `priority: 10`. `memory.h1_title` optionally
  customizes the generated title. The retired `memory.enabled` key no longer authorizes
  management.
- **Reference memory** uses `type: reference`. It is reference context, requires
  `description` frontmatter, and can set `parent: sase/memory/<note>.md` to appear under
  another reference note's `## Children` section. A reference note description may be a
  Markdown block authored as a YAML literal block scalar; that block renders verbatim as
  the body of the note's numbered Tier 2 section, while single-line surfaces collapse
  it.
- **Audited memory operations** live under the project state directory and record agent
  reads.

The legacy frontmatter values `type: short` and `type: long` are still accepted and mean
`type: core` and `type: reference` respectively.

Use [initialization](init.md#memory-initialization) to create or refresh the files. Use
[`sase memory agent-docs list`](init.md#agent-documents) to inspect `AGENTS.md` and
provider instruction file status. Initialization always generates the core
`sase/memory/sase.md` workspace note — workspace naming, linked repositories, and the
`/sase_final` terminal-action contract. For SASE-managed project repositories it
additionally generates the core `sase/memory/task_types.md` catalog note
(agent-creatable types, their `when_to_use` text, and field names),
`sase/memory/sase_artifacts.md` for artifact-reference and indexed-file workflows,
`sase/memory/sase_beads.md` for bead workflows, and `sase/memory/sase_sizes.md`
size-scale guidance nested under `sase_beads.md` and surfaced through that note's
`## Children` section on an audited read. The top-level reference notes are listed in
Tier 2 of managed agent instructions. The project-root task-type note and
`sase/task_types.json` snapshot render from the committed catalog (builtins,
`plugins.required` types, and `bead.task_types`). Day to day, the usual order is:
inspect loaded context with `sase memory list`, have agents use `sase memory read` for
audited reference reads, have agents route every memory write through
`/sase_memory_write`.

ACE's **Memory panel** is the interactive surface for browsing, adding, editing, and
deleting these notes by hand across every memory-bearing project plus Home. From a
prompt, press `gm` or `Ctrl+G m`; see [Memory panel](ace.md#memory-panel). It is a human
surface only: it never edits `AGENTS.md` or the provider shims directly — only
`sase memory init` (run from the panel's publish flow, or by hand) does that.

## XPrompt Inclusion

Every valid, flat, non-README note is also available as an explicit `#memory/<stem>`
xprompt reference: `sase/memory/sase_artifacts.md` expands with
`#memory/sase_artifacts`, and `sase/memory/sase_beads.md` expands with
`#memory/sase_beads`. The `memory/` prefix is required — there is no bare `#<stem>`
alias, and an ordinary xprompt cannot claim the `memory/` namespace. A selected
project's note shadows a same-stem home note using the same first-wins precedence
described in [Audited Reads](#audited-reads) below. The bundled `glossary` memory web's
descriptor renders as the core note `sase/memory/glossary.md`, so `#memory/glossary` is
a valid xprompt reference and the note appears in `sase memory list`. That expansion is
the descriptor body only — strand bodies never inline. Full definitions still come from
`sase memory read glossary:<term>`, covered in [Memory Webs](#memory-webs) below;
`sase memory read glossary.md` still fails because `read` rejects core notes as
already-loaded context.

This is explicit, launch-time prompt composition, not an audited lookup: expanding
`#memory/<stem>` strips frontmatter and inlines the note body but does not append the
`## Children` section, and never writes a `sase memory read` audit event. Use
`sase memory read` (below) when an already-running agent needs to consult reference
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

`sase memory show <memory-relative-path>` resolves and prints a reference memory note
the same way `sase memory read` does, minus the audit event:

```bash
sase memory show generated_skills.md
sase memory show sase_beads.md -f rich
sase memory show cli_rules.md -f json
```

Path resolution is identical to `read`: project `sase/memory/` first, then
`~/sase/memory/`, and only `type: reference` notes are accepted. Leading YAML
frontmatter is stripped, and a `## Children` section (or, in `rich`, a `Children` block)
is appended when the note has nested reference children. `-f/--format` selects
`markdown` (the default, byte-identical to `read`'s stdout for the same note), `rich` (a
styled terminal view), or `json` (a structured payload with `project`, `origin`, `note`,
and `children`). No audit event is written and no agent identity is required.

## Audited Reads

Agents should read reference memory through `sase memory read` so the access is
attributable:

```bash
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory log
sase memory log --path generated_skills.md
sase memory log --agent agent-a
sase memory log --id <read-id>
```

The read argument remains relative to the selected project or home memory root, so
callers pass `generated_skills.md`, not `sase/memory/generated_skills.md`. It accepts
reference notes (`type: reference`). Core notes are excluded because they are intended
to arrive through instruction loading rather than ad hoc reads. The command strips one
leading YAML frontmatter block from stdout and appends a `## Children` section when the
note has nested reference children. The audit event records metadata such as path, agent
name, timestamp, cwd, byte count, and reason.

Every read requires a non-empty reason via `-r` or `--reason` and agent attribution from
`SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json` (`name`,
`workflow_name`, or `agent_name`). Unattributed reads fail instead of writing the log.
Agents should always use `read`, not `show`, when consulting memory to accomplish a
task; nothing is printed unless the read was recorded.
[`sase memory show`](#show-a-note) is the supported way for a human shell to view a
note.

## Memory Webs

A memory web is a third kind of memory alongside flat notes: a project- or home-owned
catalog of small, keyword-addressed entries called strands. Kind (note, web, or strand)
and rendering (`core` or `reference`) are independent axes. A web's own descriptor
renders exactly like an ordinary note — a `core` descriptor inlines into Tier 1 of
`AGENTS.md`, a `reference` descriptor is read on demand — but a strand's body is never
inlined into `AGENTS.md`, no matter what tier its web renders at.

A web lives as one flat descriptor note plus a sibling strand directory: the descriptor
`sase/memory/<web>.md` describes the collection, and `sase/memory/<web>/<strand>.md`
files are its strands. The bundled `glossary` web ships this way:
`sase/memory/glossary.md` is the core descriptor, and each term is a strand file under
`sase/memory/glossary/`. `sase memory init` inlines a core web's descriptor body into
Tier 1 of `AGENTS.md`, plus — for a web that opts into an inline roster, as `glossary`
does — a single semicolon-separated `**GLOSSARY TERMS:**` line naming every strand
keyword and alias. The descriptor note is listed by `sase memory list` and is available
as `#memory/glossary`; `sase memory read glossary.md` still fails because `read` rejects
core notes as already-loaded context.

### Inspecting webs

```bash
sase memory web list
sase memory web list -f json
sase memory web show glossary
sase memory web show glossary stitch
sase memory web show glossary -b -f json
```

`sase memory web list` prints every discovered web: slug, rendering type
(`core`/`reference`), scope (`project`/`home`), strand count, and description.
`-f/--format` selects `table` (the default), `names`, or `json`.

`sase memory web show WEB [PATTERN]` prints one web's filterable strand _index_ —
keyword, slug, aliases, mention-reference count, and a one-line summary — never a
strand's body. `PATTERN` is an optional case-insensitive substring match against
keywords and aliases; `-b/--bodies` extends the match into strand bodies. `-f/--format`
selects `table` (the default), `names`, or `json`. Both subcommands accept
`-p/--project REF` the same way `sase repo`, `sase workspace`, and `sase memory` infer a
project from the current directory when `-p` is omitted.

### Reading strands

`sase memory read` and `sase memory show` accept three selector shapes in one variadic
batch, and the whole batch resolves before anything is printed or logged:

- a flat note name, e.g. `generated_skills.md`
- a bare web name, e.g. `glossary`, which reads every strand in that web
- a `web:keyword` strand reference, e.g. `glossary:stitch`, resolved by canonical
  keyword, alias, or an unambiguous prefix

```bash
sase memory read glossary:stitch -r "Need the stitch/patch vocabulary"
sase memory read glossary:stitch glossary:patch "Agent Hood" -r "Need the patch/stitch/hood vocabulary"
sase memory read glossary -r "Need the whole glossary"
sase memory show glossary:stitch
sase memory show glossary:stitch -d 0 -f markdown
```

`web:keyword` is an explicit read-time addressing alias, not a runtime trigger: nothing
scans a prompt for glossary phrases at read time, and nothing auto-injects context. Pass
every strand you need in one command: shared related strands print once, and a batch
that names an unknown strand reports every unresolved reference at once, prints nothing,
and exits 1.

Markdown output labels every flat note in a multi-note or mixed batch as
`---------- MEMORY FILE: <canonical-path>` and every web section as
`---------- MEMORY WEB: <slug>`. Each of those headers starts on a new line after one
blank line, including the first header in the command output, so file boundaries remain
unambiguous when several bodies are concatenated. The exact one-note case stays
header-free for backward compatibility and appends that note's nested `## Children`
section. Multi-note and mixed Markdown batches currently omit the per-note children
sections; read a parent note by itself when you need its child list.

A web whose descriptor sets `closure: mentions` — `glossary` is one — additionally walks
the recursive closure of strands each requested strand's body mentions. Every related
strand shows why it appeared: which requesting strand's body mentioned it, and the exact
matched phrase. `-d/--depth N` caps the recursion (`-d 0` prints only the requested
strands; the default is unlimited). `-f/--format` selects `markdown` (the default for
`read`/`show`), `rich` (a styled terminal view), or `json` (the closure with full
provenance). This is not an audited read when used with `show`; agents must use `read`.

Every audited read requires a non-empty reason via `-r`/`--reason` and agent attribution
the same way as [Audited Reads](#audited-reads) above, and the event records the
requested selectors, every related strand the closure added, the depth limit, and the
total bytes served. A `glossary:<keyword>` read also appears in the `GLOSSARY` lane of
the agent metadata panel in [ACE](ace.md#agents-tab-metadata-panel) alongside any legacy
pre-migration events; selecting that lane's numbered hint pages a generated report of
the read's output.

`sase memory log --include glossary` folds in audit events recorded under the retired
pre-web `sase glossary read` command, so historical reads stay visible; that legacy
parsing lives under `sase.memory`, not a `sase.glossary` package, which no longer
exists.

### Browsing and editing strands

ACE's [Memory panel](ace.md#memory-panel) is the browse-and-edit surface for webs and
strands alongside flat notes: expand a web row to walk its strands, follow
mention-closure relation chips the same way `read`'s closure does, and use `a`/`d` to
add or delete a strand — `a` on a web row opens an add-strand form, `d` on a strand row
confirms a delete after showing its aliases, body, source path, and reverse mention
references. There is no CLI write path for strand content; every write goes through the
panel's tracked mutation engine, which validates frontmatter, checks catalog ambiguity
for digest conflicts, and refreshes the descriptor roster through the normal
`sase memory init` publish path described in [Memory panel](ace.md#memory-panel).
