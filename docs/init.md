# Initialization

SASE initialization commands create or refresh durable files that agents and sidecar
tools rely on. Bare `sase init` checks the current project and home setup first, then
either reports that everything is current or shows the initializers that need attention:

```bash
sase init -c       # report drift without writing
sase init          # prompt before each needed initializer
sase init --yes    # run every needed initializer in order
sase init -M --yes # mark this repository as SASE-managed, then initialize it
sase init --all --check # check every enabled main project without writing
sase init --all         # visit every enabled main project; prompt when interactive
sase init --all --yes   # skip generic prompts for every enabled main project
```

The coordinator first builds all four read-only plans in registry order—config, memory,
repositories, then skills—before it writes anything. It then applies the changed
initializers in that same order. Config initialization establishes the explicit
per-user/per-machine owner identity; memory initialization owns agent-document
initialization (managed `AGENTS.md` and its provider instruction copies); repository
initialization owns configured sidecars and the workspace ignore rule. In
non-interactive shells, bare `sase init` reports drift and exits non-zero instead of
prompting; use `sase init --yes` when you want to apply everything that does not require
a resource-specific confirmation. Owner identity creation and migration still require a
TTY. Apply runs can write project files, deploy home files through chezmoi when
configured, and use each initializer's normal commit/push behavior. Project-wide
ownership requires `is_sase_managed: true` in the current repository's own
`sase/sase.yml`; defaults and merged user configuration cannot grant it. Without that
local marker, memory init leaves project memory and the root `AGENTS.md` untouched while
still copying every existing project-tree `AGENTS.md` to the provider instruction files
beside it, and explicit repository initialization exits successfully without detecting a
provider, materializing sidecars, or generating files.

One resource-specific exception is intentionally non-bypassable: `--yes` can run the
repository initializer, but it cannot approve creation of a missing provider sidecar.
Each creation always requires an interactive `y`/`yes` response to a prompt naming the
host, repository, and configured visibility; unattended initialization can connect
existing sidecars but cannot create them.

`sase init --all` uses the registered project inventory, so it can be run inside a
project or from an unrelated directory. It visits enabled main projects only: disabled
projects, sibling bookkeeping records, and the system-managed `home` project are
excluded. Each project runs from its recorded primary workspace. Missing workspaces,
invalid project records, planning errors, and initializer failures are reported under
that project's heading without preventing later projects from being attempted; the final
summary and exit status reflect the whole batch. `--all --check` is fully read-only and
exits non-zero if any project has drift or cannot be checked. Without a TTY, `--all`
remains read-only unless `--yes` is supplied.

Use `-M, --enable-project-memory` to create or update the current project's
`sase/sase.yml` with `is_sase_managed: true` before normal initialization. The
compatibility spelling remains, but the marker now authorizes SASE management of the
repository as a whole and thereby enables managed project memory and explicit repository
initialization. The option preserves other local configuration and is available on both
bare `sase init` and `sase memory init` (as well as the `sase init memory` compatibility
alias). Because it writes configuration, it cannot be combined with `--check` or
`--all`; repositories must be marked one at a time.

Explicit subcommands are still available when you need narrower control:

```bash
sase config init
sase config init --check
sase init config # compatibility alias
sase memory agent-docs list
sase memory init --no-commit
sase memory init --enable-project-memory --no-commit
sase memory init --check
sase memory list
sase memory review --list
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --id <read-id>
sase repo init
sase repo init --check
sase repo init --diff --no-commit
sase init repo # alias for sase repo init
sase skill list
sase skill init --dry-run
sase skill log
sase skill log --runtime codex

# Agent-side audited operations, normally run from a SASE-launched agent:
sase memory read generated_skills.md --reason "Need generated skill context"
sase skill use sase_plan --reason "Need to prepare an implementation plan"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
```

Start with `sase init -c` or `sase memory init --check` when you only want a drift
report. After that, `sase memory init --no-commit` is the usual first apply run for
memory because it writes the generated files but skips the project git commit/pull/push
path. It is not a dry run: it can still write project files, write home memory, and
follow home-level `use_chezmoi` deployment. `sase init memory` remains a compatibility
alias for `sase memory init`, and `sase init config` remains a compatibility alias for
`sase config init`, `sase init repo` is an alias for `sase repo init`, and
`sase init skills` remains an alias for `sase skill init`.

## Commands

| Command                                 | Purpose                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `sase init`                             | Check config, memory, repositories, and skills; prompt once per needed initializer.               |
| `sase init -a, --all`                   | Check or initialize every registered enabled main project, continuing after project errors.       |
| `sase init -c, --check`                 | Report initialization drift without writing and exit non-zero when changes are needed.            |
| `sase init -M, --enable-project-memory` | Mark the current repository as SASE-managed before running initialization.                        |
| `sase init --yes`                       | Run every needed initializer in config, memory, repository, skills order without generic prompts. |
| `sase config init`                      | Interactively create, select, or migrate the explicit owner identity.                             |
| `sase config init --check`              | Report owner identity initialization, migration, or conflicts without writing.                    |
| `sase init config`                      | Compatibility alias for `sase config init`.                                                       |
| `sase memory`                           | Alias for `sase memory list`.                                                                     |
| `sase memory list`                      | Inspect loaded, referenced, available, and missing memory files for the current root.             |
| `sase memory agent-docs`                | Alias for `sase memory agent-docs list`.                                                          |
| `sase memory agent-docs list`           | Inspect project, home, and chezmoi `AGENTS.md` files and nearby provider instruction files.       |
| `sase memory read <path>`               | Agent-side read of one long-term memory file with an attributable audit event.                    |
| `sase memory write`                     | Create an attributable long-term memory proposal for human review.                                |
| `sase memory review`                    | List, inspect, approve, edit, or reject pending memory proposals.                                 |
| `sase memory log`                       | Summarize audited long-term memory reads.                                                         |
| `sase memory log --include proposals`   | Include proposal and review events in the memory audit surface.                                   |
| `sase memory log --path <path>`         | Show a path-level summary and matching individual read events.                                    |
| `sase memory log --id <read-id>`        | Show one full audited read event by id or unambiguous id prefix.                                  |
| `sase memory init`                      | Refresh home and SASE-managed project memory plus provider copies for existing `AGENTS.md`.       |
| `sase memory init --check`              | Report memory initialization drift without writing files.                                         |
| `sase memory init -M`                   | Mark the repository as SASE-managed, then initialize project memory.                              |
| `sase memory init -C`                   | Write memory files but skip the project git commit/pull/push path.                                |
| `sase init memory`                      | Compatibility alias for `sase memory init`.                                                       |
| `sase repo init`                        | Initialize configured sidecars, managed declarations, and `/sase/repos/` ignore rule.             |
| `sase repo init --check`                | Report sidecar, project-config, generated-guide, and ignore-rule drift without writing.           |
| `sase repo init --no-commit`            | Apply project config and ignore changes without committing or pushing them.                       |
| `sase init repo`                        | Alias for `sase repo init`.                                                                       |
| `sase skill`                            | Alias for `sase skill list`.                                                                      |
| `sase skill list`                       | Inspect generated skill sources, provider targets, and deployed-file drift without writing.       |
| `sase skill init`                       | Generate skill files; existing files require confirmation or `--force`.                           |
| `sase skill init --dry-run`             | Preview generated skill target paths without writing files.                                       |
| `sase skill init --check`               | Report generated skill-file drift without writing files.                                          |
| `sase skill init --diff`                | Show full generated skill-file diffs without writing files.                                       |
| `sase skill init --force`               | Overwrite deployed skill files without confirmation and bypass the provenance manifest guard.     |
| `sase skill init --allow-dirty`         | Deploy from uncommitted or unmerged xprompt sources; can revert other agents' deployments.        |
| `sase skill init -p <provider>`         | Deploy only one provider's generated skill files.                                                 |
| `sase skill log`                        | Summarize or inspect audited generated skill-use events.                                          |
| `sase skill use <name>`                 | Agent-side audit event recording that a generated skill was used.                                 |
| `sase init skills`                      | Compatibility alias for `sase skill init`.                                                        |

Advanced deploy controls such as `--no-commit`, `--no-push`, and `--no-apply` live on
explicit subcommands rather than the bare coordinator. Scoped `--check` flags also live
on explicit subcommands when you want to validate only memory, repository/sidecar
wiring, or generated skill files.

## Agent Documents

`sase memory agent-docs list` is the read-only inventory for agent instruction
documents: root `AGENTS.md` plus provider instruction files such as `CLAUDE.md`,
`GEMINI.md`, `QWEN.md`, and `OPENCODE.md` (each a full copy of `AGENTS.md`).

```bash
sase memory agent-docs list
```

With no subcommand, `sase memory agent-docs` defaults to `sase memory agent-docs list`.
The inventory shows project, subdirectory, home, and chezmoi-source `AGENTS.md` files,
their H1 titles, whether they look managed, short/long memory reference counts, and
nearby provider instruction file status. It never writes files; `sase memory init` is
the command that creates or refreshes these documents.

## Memory Initialization

`sase memory init` always initializes the home-level memory surface. It initializes
project-local memory only for a SASE-managed repository, and independently owns provider
instruction copies:

`sase memory init -M` is the convenience path for a repository that should be
SASE-managed: it creates or updates `sase/sase.yml` with the repository-wide marker
before loading configuration and running the normal initializer. Despite the
compatibility option name `--enable-project-memory`, this does not change ProjectSpec
lifecycle state and is independent of `sase project enable`.

- Project memory under `./sase/memory/`, including `sase/memory/README.md` and flat note
  files with `type`/`parent` frontmatter, only when the project's own `sase/sase.yml`
  contains `is_sase_managed: true`.
- Home memory under `~/sase/memory/`, or under
  `~/.local/share/chezmoi/home/sase/memory/` when `use_chezmoi: true`.
- A managed project `AGENTS.md` only with that same explicit opt-in. `amd_h1_title`
  customizes its H1; otherwise SASE derives the stable `<project> - Agent Instructions`
  title.
- Provider instruction files `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`;
  each is a byte-for-byte copy of that root's final `AGENTS.md`. Chezmoi home source
  roots use static `.md` files (not `*.md.tmpl` imports), since the inlined `AGENTS.md`
  carries no template variables. Legacy `@AGENTS.md` / `@/path/to/home/AGENTS.md` import
  shims and `*.md.tmpl` sources are still recognized and migrated to full copies.

Managed projects can override the packaged Jinja templates for `AGENTS.md`, minimal
agent instructions, `sase/memory/sase.md`, and `sase/memory/README.md` with
root-relative paths in `sase/sase.yml`. The generated `sase/memory/sase_beads.md` bead
reference is a fixed packaged asset with no override key, generated only for
SASE-managed project repositories and never for home or chezmoi-home roots. Home roots
use convention-based template files in the SASE user-config directory (or its chezmoi
source counterpart). Template variables and validation rules are listed in the
[generated templates configuration](configuration.md#generated-templates).

For a SASE-managed project, `sase memory init` inlines each short-term note's body into
Tier 1, renders Tier 2 from long-note descriptions, adds missing canonical frontmatter,
and validates reachability. Missing, false, merged-global, or `amd_h1_title`-only
configuration does not authorize any project memory or root `AGENTS.md` creation,
refresh, or validation. The retired `memory.enabled` key is not an alias. Existing
projects must replace it once with:

```yaml
is_sase_managed: true
```

Home and chezmoi-home initialization is unchanged: those roots remain managed and take
an optional title from user config (`~/.config/sase/sase.yml`, overlays, or source-side
`dot_config/sase/`).

Provider copying is the exception to project ownership. In both managed and unmanaged
projects, every readable `AGENTS.md` found with the normal project-tree pruning rules is
copied byte-for-byte to `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` beside
it. A directory with no `AGENTS.md` is untouched, including any standalone provider
files already there.

When `use_chezmoi: true`, the home files are written to the chezmoi source tree. The
command can then commit those home changes and run `chezmoi apply --force`;
`--no-commit` does not disable that home deployment path.

The generated `sase/memory/sase.md` summarizes workspace naming and linked repositories.
The generated long-term `sase/memory/sase_beads.md` note provides shared bead workflow
guidance and is listed in Tier 2 of managed agent instructions, generated for
SASE-managed project repositories only and never for home or chezmoi-home roots. A root
that no longer manages the note (for example, a home root that previously generated it)
deletes an unmodified copy on the next `sase memory init` pass; a copy a human has since
edited is left alone and keeps behaving as an ordinary long note. Project memory reads
linked-repo descriptions from the project-local `sase/sase.yml`; home memory reads them
from the global config `~/.config/sase/sase.yml`, or from the chezmoi-managed config
path when `use_chezmoi: true`. Generated memory requires agents to use `/sase_repo`
before reading or modifying any repository outside their own workspace checkout. This
rule applies to configured linked repos and sidecars, other SASE projects, and unlinked
GitHub repos even when no linked repositories are configured; the skill carries the
command grammar and workspace-selection details.

Every configured `linked_repos` entry (or its deprecated `sibling_repos` alias) must
have a non-empty `description`. Initialization fails instead of generating ambiguous
memory when a description is missing.

By default, project memory initialization runs `commit_hooks.before`, stages generated
project files, commits them with the standard memory-init commit message, pulls with
rebase, and pushes. This path does not run `commit_hooks.after`. Use
`sase memory init --check` for a read-only drift check, or
`sase memory init --no-commit` when you want to review generated project files before
committing. `--no-commit` only skips the project deploy path; home memory deployment
still follows `use_chezmoi` when it is enabled.

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

For day-to-day read/write operations, including audited reads and reviewed long-term
memory proposals, see [Memory](memory.md).

## Memory Read Audit Log

`sase memory read <memory-relative-path> -r <reason>` is the audited path for
agent-initiated long-term memory reads. The argument is relative to the selected project
or home `sase/memory/` root; the command allows `type: long` Markdown notes and rejects
`type: short` notes because short-term memory is expected to arrive through instruction
loading. The command strips one leading YAML frontmatter block from stdout and appends
`## Children` when nested long notes exist, but the audit log records only metadata such
as path, agent name, timestamp, cwd, byte count, and reason.

Every read must include a non-empty reason via `-r` or `--reason`. The command also
requires agent attribution from `SASE_AGENT_NAME`, `SASE_AGENT`, or
`SASE_ARTIFACTS_DIR/agent_meta.json`; unattributed reads fail instead of writing a log
row. Human shell users normally inspect files directly and use `sase memory review` for
promotion decisions.

`sase memory write` creates an attributable proposal under `~/.sase/projects/<project>/`
and never writes canonical memory files directly. It uses the same agent-attribution
rules as `read`; `--manual-author` is intended for tests and demos. Pass `--notify` when
you want a best-effort `memory.proposed` notification in the SASE inbox.
`sase memory review` is the human promotion path for listing, showing, approving,
editing, or rejecting those proposals.

`sase memory log` reads the project-scoped audit log from SASE state under
`~/.sase/projects/<project>/`, not from the repo. Use `--path` or `--agent` to drill
down to matching read events, `--id <read-id>` to inspect one event, and `--json` for
deterministic machine-readable output. Add `--include proposals` to include proposal and
review ledger events alongside read-log summaries.

```bash
# read requires SASE agent identity; write requires agent identity unless --manual-author is used for demos
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
sase memory review --list
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --id <read-id>
```

## Repository Initialization

`sase repo init` initializes every enabled `repos.sidecar` entry for the current managed
project. It also adds the explicit project-local plans, beads, and research declarations
when absent:

```yaml
repos:
  sidecar:
    builtin:
      plans:
        auto_clone: true
      beads:
        auto_clone: true
    custom:
      research:
        description: Durable SASE research reports and generated media.
```

Reserved roles are written under `repos.sidecar.builtin` and document sidecars under
`repos.sidecar.custom`. If `repos.sidecar` still uses the removed list form, the write
stops with an error asking you to migrate it to the two-bucket mapping first;
`sase doctor` names the target bucket for each existing entry.

An existing entry for any of those roles is preserved verbatim, including
`disabled: true`; disabling research is the project-local opt-out. The unpinned research
entry derives `<owner>/<project>--research` from the primary GitHub repository, and the
beads entry likewise derives `<owner>/<project>--beads`. The write uses SASE's
comment-preserving configuration editor. The same initializer adds `/sase/repos/` to the
tracked root `.gitignore`; those two project-file changes use the normal
commit/pull/push path unless `--no-commit` is supplied.

For each enabled sidecar, provider discovery runs before materialization. A missing
remote gets its own default-no prompt naming the visibility, provider, full repository
name, and host. Only `y` or `yes` authorizes creation; `--yes`, blank answers, EOF,
interruption, and non-interactive stdin cannot authorize it. The configured `repo:` pin
and `visibility:` are passed to the provider, and initialization fails closed if the
provider cannot honor the requested visibility.

When non-interactive bare `sase init --yes` discovers a missing sidecar remote, it
writes the project wiring, reports the missing repository, and leaves creation for a
later interactive `sase repo init`. This keeps automated onboarding and post-commit
hooks non-blocking without allowing `--yes` to authorize remote creation.

Managed projects also resolve an implicit public `<project>--agents` sidecar unless
project configuration disables it, sets `default_linked_repos: false`, or supplies an
explicit replacement. Its missing remote receives a separate, agent-specific, default-no
creation prompt; `--yes` never authorizes publishing agent history. Declining that
prompt continues initialization without the agents sidecar, while another missing
sidecar can still make initialization incomplete. Before accepting, review the
transported prompt, chat, commit, and relationship data and set a project-local
`visibility: private` override when appropriate. Publication requires the selected
overlay's complete `id.username` / `id.machine_name` identity; run `sase config init`
first to migrate a legacy top-level `machine_name`. The initialized README explains the
full project-scoped hood privacy implications, owner-sharded v2 browsing layout,
active/optional transcript behavior, and synchronization/recovery commands. Existing v1
payload remains read-only during migration. See
[Agent Hood Synchronization](agents_sidecar.md).

Reserved sidecars and the default `research` presentation preset receive illustrated
README guides and directory-map assets. Rerunning `sase repo init` upgrades a missing or
stale agents infographic while preserving the manifest-derived root index of a populated
agents sidecar. Custom sidecar roles receive a deterministic generic README using their
configured description. Initialized guide files are committed and pushed in their
respective sidecar repositories. When plans are available, the split SDD store record
records every initialized role; `research` is not required.

The beads sidecar holds the project's durable bead state at its repository root. When it
is created for a project whose bead state still lives in the plans clone,
`sase repo init` adopts that state as part of the same run: it copies the store into the
beads clone, commits it as `Import bead state from <plans-repo>@<sha>` and pushes,
writes the schema-3 store record that makes bead commands resolve to the new repository,
and only then removes `beads/` from the plans clone. `sase repo init --check` lists that
data move as a distinct planned action. Adoption is idempotent, so rerunning
initialization after a partial failure retries cleanly; see
[SDD Storage](sdd_storage.md) for the full transaction and its failure semantics.

```bash
sase repo init                    # initialize sidecars and project wiring
sase repo init --check            # preview without network probes or writes
sase repo init --diff             # show file diffs, then apply
sase repo init --no-commit        # write project config/ignore changes without committing
sase init repo                    # alias for sase repo init
```

Both apply and `--check` first read the current repository's own `sase/sase.yml` (with
root `sase.yml` as a legacy-only fallback). A missing or false `is_sase_managed` marker
makes the command an informative, successful no-op before provider work; malformed YAML
and non-boolean marker values fail safely. `sase init repo` delegates to the same
repository initializer; `sase init workspace` is no longer a public subcommand because
its ignore-rule work is part of repository initialization.

Built-in bare-git projects keep their provider-owned in-tree SDD layout. For those
projects, `sase repo init` refreshes the existing generated SDD guides while still
maintaining the managed sidecar declarations and repository ignore rule. Keep conceptual
SDD documentation in [docs/sdd.md](sdd.md) and storage-mode details in
[docs/sdd_storage.md](sdd_storage.md).

## Skill Initialization

Generated skills start as Markdown sources in a canonical `skills/` directory that set a
truthy `skill` frontmatter field — see [Skill Field](xprompt.md#skill-field).
`sase skill list` is the read-only inventory: it shows loaded skill sources, the
providers they target, and whether generated `SKILL.md` files are current, stale, or
missing. It also reports misplaced sources in a "Misplaced Sources" panel. Bare
`sase skill` shows the same dashboard.

`sase skill init` renders those sources into provider-specific `SKILL.md` files, and
exits non-zero without writing anything while any placement violation remains. Sources
include the bundled `src/sase/skills/` templates plus project, home, and plugin skill
directories. By default, generated skill files include a first-step
`sase skill use <name> --reason ...` directive so agent skill usage is attributable in
the same project audit surface as memory reads; `sase skill log` summarizes and inspects
those recorded skill-use rows. A source can set `log_skill_use: false` to omit that
directive. The usual workflow is to inspect first, preview writes, commit the source
change, and only then deploy:

```bash
sase skill list
sase skill init --dry-run
sase skill init --diff
# commit the skill source change and land it on the canonical branch first
sase skill init --force
```

Without `use_chezmoi`, generated skill files are written directly under the provider's
home-directory skill targets. When `use_chezmoi: true`, skill initialization writes
through the chezmoi-managed home tree and can commit, push, and apply those dotfile
changes. The `--no-commit`, `--no-push`, and `--no-apply` flags only affect that chezmoi
deployment sequence. `sase init skills` still works as a compatibility alias for
`sase skill init`.

### Commit Before Deploying

The chezmoi destination is a single global tree shared by every workspace, so a deploy
from a workspace whose sources are not canonical publishes content that exists in no
sase commit and can revert another agent's deployment. Two guards enforce that, and they
apply only to writing chezmoi deploys — `--check`, `--diff`, `--dry-run`, and
non-chezmoi targets are unaffected:

- **Source integrity.** The deploy is refused when `src/sase/xprompts/` has uncommitted
  changes, or when the invoking workspace's `HEAD` is not an ancestor of the canonical
  branch. The error names the offending files or the unmerged commits.
- **Provenance manifest.** Each deploy records the source commit and an xprompt-set hash
  in `.sase-skills-manifest.json` under the chezmoi source root. A deploy whose source
  commit differs from the recorded one is refused rather than allowed to move the
  destination backwards. A missing or unparsable manifest bootstraps cleanly.

So the corrected workflow is: iterate with `--diff` / `--dry-run`, commit the template
change to the sase repo, land it on the canonical branch, and deploy from that clean
merged tree.

Because of those guards, `--check` does not fail on chezmoi deploy drift it has no way
to resolve. When chezmoi deployment is enabled and generated skill files differ from
their deployed chezmoi copies, `sase init skills --check` counts those files, reports
them as a warning telling you to rerun `sase init skills` after landing, and drops them
from its action list — so the check itself passes. If a dirty or unlanded tree would
also make the real deploy refuse, that source-integrity reason is reported as a second
warning. This keeps an unrelated read-only check from either failing for drift only a
land can clear or triggering a mutating deploy as a side effect. Writing plans
(interactive onboarding and direct deploys) are unaffected, as is the deploy-side
integrity refusal. `sase validate` surfaces these warnings in its own `Warnings:` block;
see [`sase validate`](configuration.md#sase-validate).

`--allow-dirty` overrides the source-integrity guard and `--force` overrides the
manifest guard. Both are deliberate escape hatches that can revert other agents'
deployments; reach for them only when you know the destination is stale. `--force` still
records the new manifest entry.

See [XPrompt Skill Field](xprompt.md#skill-field) for the skill-source contract and
bundled skill list.
