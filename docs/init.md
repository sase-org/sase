# Initialization

SASE initialization commands create or refresh durable files that agents and companion tools rely on. Bare `sase init`
checks the current project and home setup first, then either reports that everything is current or shows the
initializers that need attention:

```bash
sase init -c       # report drift without writing
sase init          # prompt before each needed initializer
sase init --yes    # run every needed initializer in order
```

The coordinator plans in registry order: memory, SDD, then skills. Planning is read-only. In non-interactive shells,
bare `sase init` reports drift and exits non-zero instead of prompting; use `sase init --yes` when you want an
unattended apply run.

Explicit subcommands are still available when you need narrower control:

```bash
sase memory init --no-commit
sase memory init --check
sase memory list
sase init sdd
sase init sdd --check
sase init skills --dry-run
```

`sase memory init --no-commit` is usually the safest first run because it writes the generated files but skips the
project git commit/pull/push path. It is not a dry run: it can still write project files, write home memory, and follow
home-level `use_chezmoi` deployment. `sase init memory` remains a compatibility alias for `sase memory init`.

## Commands

| Command                          | Purpose                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------- |
| `sase init`                      | Check memory, SDD, and skills; prompt once per needed initializer in interactive shells. |
| `sase init -c, --check`          | Report initialization drift without writing and exit non-zero when changes are needed.   |
| `sase init --yes`                | Run every needed initializer in memory, SDD, skills order without prompting.             |
| `sase memory`                    | Alias for `sase memory list`.                                                            |
| `sase memory list`               | Inspect loaded, referenced, available, and missing memory files for the current root.    |
| `sase memory init`               | Create or refresh project/home memory roots and provider instruction shims.              |
| `sase memory init --check`       | Report memory initialization drift without writing files.                                |
| `sase memory init -C`            | Write memory files but skip the project git commit/pull/push path.                       |
| `sase init memory`               | Compatibility alias for `sase memory init`.                                              |
| `sase init sdd`                  | Alias for `sase sdd init`; refreshes generated SDD README files and the directory map.   |
| `sase init sdd --check`          | Report SDD generated-file drift without writing files.                                   |
| `sase init skills`               | Generate skill files; existing files require confirmation or `--force`.                  |
| `sase init skills --dry-run`     | Preview generated skill target paths without writing files.                              |
| `sase init skills --force`       | Generate and overwrite deployed skill files without confirmation.                        |
| `sase init skills -p <provider>` | Deploy only one provider's generated skill files.                                        |

Advanced deploy controls such as `--no-commit`, `--no-push`, and `--no-apply` live on explicit subcommands rather than
the bare coordinator. Scoped `--check` flags also live on explicit subcommands when you want to validate only memory or
only SDD generated files.

## Memory Initialization

`sase memory init` initializes both project-local and home-level memory surfaces:

- Project memory under `./memory/`, including `memory/README.md`, `memory/short/sase.md`, and `memory/long/`.
- Home memory under `~/memory/`, or under `~/.local/share/chezmoi/home/` when `use_chezmoi: true`.
- A minimal `AGENTS.md` when one does not already exist.
- Provider shims `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` containing `@AGENTS.md`.

When `use_chezmoi: true`, the home files are written to the chezmoi source tree. The command can then commit those home
changes and run `chezmoi apply --force`; `--no-commit` does not disable that home deployment path.

The generated `memory/short/sase.md` summarizes workspace naming and sibling repositories. Project memory reads sibling
repo descriptions from the project-local `./sase.yml`; home memory reads them from the global config
`~/.config/sase/sase.yml`, or from the chezmoi-managed config path when `use_chezmoi: true`. Generated memory
distinguishes static-path siblings (`workspace.strategy: none`) from numbered-workspace siblings, lists the direct path
for static siblings, and includes `sase workspace open` instructions only when at least one configured sibling uses
numbered workspace resolution.

Every configured `sibling_repos` entry must have a non-empty `description`. Initialization fails instead of generating
ambiguous memory when a description is missing.

By default, project memory initialization runs the configured precommit command, stages generated project files, commits
them with the standard memory-init commit message, pulls with rebase, and pushes. Use `sase memory init --check` for a
read-only drift check, or `sase memory init --no-commit` when you want to review generated project files before
committing. `--no-commit` only skips the project deploy path; home memory deployment still follows `use_chezmoi` when it
is enabled.

Memory validation is reachability-based: Markdown files under `memory/short/` and `memory/long/` must be reachable from
`AGENTS.md` directly or through transitive `@memory/...` or `memory/...` references. Unreferenced memory files make the
command fail so important agent context is not silently ignored.

## Memory Context List

`sase memory list`, or bare `sase memory`, renders a read-only dashboard for the current directory. It reports:

- `loaded` files reached by transitive `@...` references from instruction roots such as `AGENTS.md` and provider shims.
- `referenced` files mentioned by plain `memory/...` text from loaded context. These are visible in the dashboard, but
  their contents are not loaded unless another `@...` edge reaches them.
- `available` files present under `memory/short/` or `memory/long/` that the current launch context does not reach.
- `missing` referenced memory paths that do not exist.

The dashboard includes approximate local token estimates. It reports discoverable long-term sources, but it does not
generate prompt-dependent `.sase/memory/` files; those are written only during an agent launch when keyword-tagged
long-term memory matches the prompt.

## SDD Initialization

`sase init sdd` is an alias for `sase sdd init`. It creates or refreshes generated SDD guide files and
`sdd/assets/sdd-directory-map.png` for either a project root or an SDD root:

```bash
sase init sdd
sase init sdd --check
sase init sdd --path ./sdd
```

Keep conceptual SDD documentation in [docs/sdd.md](sdd.md). The files generated by `sase init sdd` are intentionally
short project-local guides and are safe to overwrite. Use `--check` to compare the generated files without rewriting
them.

## Skill Initialization

`sase init skills` renders loaded xprompts marked with a `skill` frontmatter field into provider-specific `SKILL.md`
files. Sources include bundled skill xprompts and user/runtime xprompt catalog entries. Run a dry run first when adding
or changing skill sources:

```bash
sase init skills --dry-run
sase init skills --force
```

Without `use_chezmoi`, generated skill files are written directly under the provider's home-directory skill targets.
When `use_chezmoi: true`, skill initialization writes through the chezmoi-managed home tree and can commit, push, and
apply those dotfile changes. The `--no-commit`, `--no-push`, and `--no-apply` flags only affect that chezmoi deployment
sequence.

See [XPrompt Skill Field](xprompt.md#skill-field) for the skill-source contract and bundled skill list.
