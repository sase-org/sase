---
title: Memory initialization
description: Look up how SASE initializes, lists, and audits agent memory.
---

# Memory initialization

This page describes memory initialization and the related list and audit commands.

<a id="memory-initialization-1"></a>

## Memory Initialization

`sase memory init` always initializes the home-level memory surface. It initializes
project-local memory only for a SASE-managed repository, and independently owns provider
instruction copies:

`sase memory init -M` is the convenience path for a repository that should be
SASE-managed: it creates or updates `sase/sase.yml` with the repository-wide marker
before loading configuration and running the normal initializer. Despite the
compatibility option name `--enable-project-memory`, this does not change ProjectSpec
lifecycle state and is independent of `sase project enable`.

- Project memory under `./sase/memory/`, including `sase/memory/README.md`, the
  project-only generated core `sase/memory/task_types.md` catalog note, the committed
  `sase/task_types.json` snapshot, and flat note files with `type`/`parent` frontmatter,
  only when the project's own `sase/sase.yml` contains `is_sase_managed: true`.
  `plugins.required` is verified before any snapshot or note comparison, so a missing
  required plugin is reported as an install error rather than as memory drift. When a
  committed type's spec digest changes, `--check` names the type and its package.
- Home memory under `~/sase/memory/`, or under
  `~/.local/share/chezmoi/home/sase/memory/` when `use_chezmoi: true`.
- A managed project `AGENTS.md` only with that same explicit opt-in. `memory.h1_title`
  customizes its H1; otherwise SASE derives the stable `<project> - Agent Instructions`
  title.
- Provider instruction files `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`;
  each is a byte-for-byte copy of that root's final `AGENTS.md`. Chezmoi home source
  roots stay on static `.md` files unless a machine overlay under `dot_config/sase/`
  declares `memory.h1_title`. In that case initialization writes `AGENTS.md.tmpl` and
  preferred `*.md.tmpl` shims whose H1 switches on `.chezmoi.hostname`, and each
  title-declaring overlay must have a `.chezmoiignore` hostname guard (the stanza
  `sase config init` writes). Legacy `@AGENTS.md` / `@/path/to/home/AGENTS.md` import
  shims and leftover static or `*.md.tmpl` sources are still recognized and migrated.

Managed projects can override the packaged Jinja templates for `AGENTS.md`, minimal
agent instructions, `sase/memory/sase.md`, and `sase/memory/README.md` with
root-relative paths in `sase/sase.yml`. The generated project-only reference notes
`sase/memory/sase_artifacts.md`, `sase/memory/sase_beads.md`, and
`sase/memory/sase_sizes.md` are fixed packaged assets with no override keys, generated
only for SASE-managed project repositories and never for home or chezmoi-home roots.
Home roots use convention-based template files in the SASE user-config directory (or its
chezmoi source counterpart). Template variables and validation rules are listed in the
[generated templates configuration](../config/core-behavior.md#generated-templates).

`sase/memory/glossary.md` is not a generated note — it is a user-owned memory-web
descriptor, exactly like any other `sase/memory/<web>.md` file, with the project's terms
authored as sibling strand files under `sase/memory/glossary/`. Memory initialization
always inlines its descriptor body into the `## Memory Webs` section of `AGENTS.md` and
the provider instruction files, plus the descriptor's inline `**GLOSSARY TERMS:**`
roster naming every strand keyword and alias, semicolon-separated. Strand bodies never
inline into `AGENTS.md`; agents fetch a definition on demand with
`sase memory read glossary:<keyword> -r "<why>"`, passing every keyword needed in one
command. See [Memory Webs](../memory/memory.md#memory-webs) for the full read, browse,
and edit workflow.

For a SASE-managed project, `sase memory init` inlines each core note into
`## Core Memory` and numbers every heading in the generated document, renders each
memory web as its own numbered H3 subsection of `## Memory Webs` (omitted entirely when
the root has no webs), and renders reference memory as one ordered-list entry per
top-level reference note, adds missing canonical frontmatter, and validates
reachability. The instruction paragraph pointing agents at `/sase_memory_read` is direct
body content of the `## Reference Memory` heading, immediately followed by those
per-note list entries; both the paragraph and the entries are omitted when a root has no
top-level reference notes. Missing, false, merged-global, or `memory.h1_title`-only
configuration does not authorize any project memory or root `AGENTS.md` creation,
refresh, or validation. The retired `memory.enabled` key is not an alias. Existing
projects must replace it once with:

```yaml
is_sase_managed: true
```

Home and chezmoi-home initialization is unchanged: those roots remain managed and take
an optional title from user config (`~/.config/sase/sase.yml`, overlays, or source-side
`dot_config/sase/`). Chezmoi machine-overlay titles additionally emit `AGENTS.md.tmpl`
as described under provider instruction files above.

Provider copying is the exception to project ownership. In both managed and unmanaged
projects, every readable `AGENTS.md` found with the normal project-tree pruning rules is
copied byte-for-byte to `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` beside
it. A directory with no `AGENTS.md` is untouched, including any standalone provider
files already there.

When `use_chezmoi: true`, the home files are written to the chezmoi source tree. The
command can then commit those home changes and run `chezmoi apply --force`;
`--no-commit` does not disable that home deployment path.

The generated `sase/memory/sase.md` summarizes workspace naming, linked repositories,
and the `/sase_final` terminal-action contract for end-of-turn declarations. The
generated reference `sase/memory/sase_artifacts.md` note owns artifact-reference and
indexed-file workflow guidance. The generated reference `sase/memory/sase_beads.md` note
provides shared bead workflow guidance and has `sase/memory/sase_sizes.md` as a child
size-scale note. Top-level project-only reference notes are listed in the
`## Reference Memory` section of managed agent instructions, generated for SASE-managed
project repositories only and never for home or chezmoi-home roots. The core
`sase/memory/task_types.md` catalog note is likewise project-only. A root that no longer
manages those notes (for example, a home root that previously generated them) deletes
generated copies on the next `sase memory init` pass; copies a human has since edited
are left alone and keep behaving as ordinary notes. Project memory reads linked-repo
descriptions from the project-local `sase/sase.yml`; home memory reads them from the
global config `~/.config/sase/sase.yml`, or from the chezmoi-managed config path when
`use_chezmoi: true`. Generated memory requires agents to use `/sase_repo` before reading
or modifying any repository outside their own workspace checkout. This rule applies to
configured linked repos and sidecars, other SASE projects, and unlinked GitHub repos
even when no linked repositories are configured; the skill carries the command grammar
and workspace-selection details.

Every configured `linked_repos` entry (or its deprecated `sibling_repos` alias) must
have a non-empty `description`. Initialization fails instead of generating ambiguous
memory when a description is missing.

By default, project memory initialization runs `commit_hooks.before`, stages generated
project files, commits them with the standard memory-init commit message, pulls with
rebase, and pushes. This path does not run `commit_hooks.after`. Use
`sase memory init --check` to report drift without writing, or
`sase memory init --no-commit` when you want to review generated project files before
committing. `--no-commit` only skips the project deploy path; home memory deployment
still follows `use_chezmoi` when it is enabled.

The tracking part of `--check` also fails when an existing managed file is untracked,
including when Git ignores it. It does not require tracked files to have a clean index
or worktree; the separate drift check compares generated content. The managed set is
every existing file under `sase/memory/` and the legacy `memory/` directory (including a
symlink that points at a file), plus managed instruction files: a discovered project
`AGENTS.md` that SASE recognizes as a managed instruction document, the provider shims
beside discovered `AGENTS.md` files, and `AGENTS.md.tmpl` sources under the checked
root. If this instruction-file scan finds nothing, existing root `AGENTS.md` and shims
are included regardless of their contents. Tracking uses resolved paths for symlinks, so
their targets are checked rather than the symlink's own Git entry. The project root is
checked when the working directory is a project. The home root is checked only when
`use_chezmoi` is on. Files without an identifiable owning Git repository, and
repositories whose tracked-file lookup fails, are skipped by this tracking check. A
missing Git binary therefore does not itself produce a tracking blocker. A reported
blocker names the file and asks you to commit it so its history can start.

After a committing project deploy succeeds, the command checks that project root again.
After a chezmoi home deploy succeeds, it checks the chezmoi source the same way. The
command exits `1` and prints to stderr when a managed file was left untracked, ignored,
or with uncommitted changes. `--no-commit` skips the project check because it skips the
project commit; it does not skip chezmoi deployment or its guard. These guards run
**after** deployment and do not undo files, commits, or pushes when they report a
problem. A Git error skips the affected tracking or cleanliness check, and an unexpected
guard failure leaves the deploy's own result in place.

Memory drift is judged against the running build's generator templates, so the build
that answers matters. When the invoked project carries its own `.venv/bin/sase` but the
command is running under a different interpreter — the usual case being a bare `sase` on
`PATH` that resolves to a separate `uv tool` install — both `--check` and apply modes
print a non-fatal warning naming the foreign interpreter and the pinned invocation to
use instead (`<project>/.venv/bin/sase memory init --check`, or `just check` in a repo
that provides it). Phantom drift that disappears under the pinned build is exactly this
situation.

For managed roots, memory validation is reachability-based: Markdown files under
`sase/memory/` must be reachable from `AGENTS.md` directly or through transitive
`@sase/memory/...` or `sase/memory/...` references. Unreferenced memory files make the
command fail so important agent context is not silently ignored. Unmanaged project
memory is not validated.

## Memory Context List

`sase memory list`, or bare `sase memory`, renders a read-only dashboard for the current
directory. It reports:

- `loaded` files reached by transitive `@...` references from `AGENTS.md` in the project
  or home context.
- `referenced` files mentioned by plain `sase/memory/...` text from loaded context or by
  audited `sase memory read` instructions. These are visible in the dashboard, but their
  contents are not loaded unless another `@...` edge reaches them.
- `available` files present under project or home `sase/memory/` that the current launch
  context does not reach.
- `missing` referenced memory paths that do not exist.

The dashboard includes approximate local token estimates for loaded memory context.

For day-to-day read/write operations, including audited reads, see
[Memory](../memory/memory.md).

## Memory Read Audit Log

`sase memory read <selector>... -r <reason>` is the audited path for agent-initiated
reference memory reads. Each selector is a flat note name relative to the selected
project or home `sase/memory/` root (such as `generated_skills.md`), a bare memory-web
name (such as `glossary`, which prints every strand), or a `web:keyword` strand
reference (such as `glossary:stitch`); one unknown selector fails the whole batch. The
command also accepts `-d/--depth`, `-f/--format`, and `-p/--project`, and it allows
`type: reference` Markdown notes and rejects `type: core` notes because core memory is
expected to arrive through instruction loading. The command strips one leading YAML
frontmatter block from stdout and appends `## Children` when nested reference notes
exist, but the audit log records only metadata such as path, agent name, timestamp, cwd,
byte count, reason, and content hashes in Git's SHA-1 blob format. A flat note's hash
covers its text including frontmatter; a strand's hash covers only its body. Batch reads
record target/hash pairs. `sase memory log --id <read-id>` shows **Blob OID** and, when
present, **Blob OIDs**; older events that lack the fields still load. Agent launch also
attempts to store the workspace `HEAD` and an instruction-file inventory in
`agent_meta.json`, without blocking launch on capture failure. See
[Audited Reads](../memory/memory.md#audited-reads) for the hash and snapshot details.

This audited path is distinct from `#memory/<stem>` macro inclusion: an explicitly
authored `#memory/<stem>` reference in a prompt expands the same note body at launch
time, for both `type: core` and `type: reference` notes, without writing an audit event.
See [Memory Field](../macros/fields.md#memory-field).

Every read must include a non-empty reason via `-r` or `--reason`. The command also
requires agent attribution from `SASE_AGENT_NAME`, `SASE_AGENT`, or
`SASE_ARTIFACTS_DIR/agent_meta.json`; unattributed reads fail instead of writing a log
row. Human shell users normally use `sase memory show <selector>...`, which prints the
same content without a reason or audit event.

`sase memory log` reads the project-scoped audit log from SASE state under
`~/.sase/projects/<project>/`, not from the repo. Use `--path` or `--agent` to drill
down to matching read events, `--id <read-id>` to inspect one event, and `--json` for
deterministic machine-readable output.

```bash
# read requires SASE agent identity
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory log
sase memory log --path generated_skills.md
sase memory log --id <read-id>
```

## Related

- [Agents and workspaces](index.md) — the section hub.
