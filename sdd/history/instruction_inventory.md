# Instruction Inventory

This page records the instruction-file inventory used to plan the memory-built
instruction migration. The repository and home counts below are a **historical inventory
begun on 2026-10-06 and updated during E3 acceptance**, not a live inventory of your
installation. Run `sase instructions list` to inspect your current files, and
`sase instructions verify` to compare recorded intent with loads observable in provider
session records. Unobservable loads are marked `◌`.

## Current delivery

For root calls with an artifacts directory, Claude, Codex, Grok, and Muse use
per-invocation bundles by default when preparation succeeds. Claude also delivers a
separate helper bundle when supported; Codex helpers inherit the root bundle.
Antigravity, OpenCode, and Qwen still use native discovery. Generated root files and
provider shims remain in this repository; explicit delivery suppresses native duplicates
according to each adapter's capabilities rather than deleting those files.

For channels, fallback behavior, and diagnostic commands, start with
[Instruction Bundles](../../docs/instruction_bundles.md). The E1–E5 labels and
dispositions below refer to internal migration phases, not a setup sequence for users or
proof that files have been removed.

Dispositions: `migrate` (replaced by memory-built per-invocation delivery), `projection`
(generated copy of another committed source), `repo-owned` (hand-written, stays),
`deferred` (decided by a later epic).

## Generated, memory-backed (40)

`migrate`. These render from `sase/memory/` through `sase memory init`, which also
copies every project-tree `AGENTS.md` to the provider shims beside it. E3 delivers
per-invocation bundles and suppresses SASE-owned root and home files at runtime; the
files stay committed until E4 (project) and E5 (home).

| Project           | Paths                                                                     | Files                   | Disposition | Owning epic      |
| ----------------- | ------------------------------------------------------------------------- | ----------------------- | ----------- | ---------------- |
| sase (root scope) | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`           | 5, byte-identical shims | `migrate`   | E3 (removal E4)  |
| home              | `~/AGENTS.md`, `~/CLAUDE.md`, `~/GEMINI.md`, `~/QWEN.md`, `~/OPENCODE.md` | 5                       | `migrate`   | E5 (delivery E3) |
| bob-cli           | root `AGENTS.md` + 4 shims                                                | 5                       | `migrate`   | E5               |
| actstat           | root `AGENTS.md` + 4 shims                                                | 5                       | `migrate`   | E5               |
| job               | root `AGENTS.md` + 4 shims                                                | 5                       | `migrate`   | E5               |

Sase nested scopes were 15 more files at the E3 inventory: each scope's `AGENTS.md` was
hand-written, with 4 byte-identical shims projected beside it by `sase memory init`. E4
(`nested_guides = fold`) moved those guides into `sase/memory/tools.md`,
`sase/memory/ace.md`, and `sase/memory/demos.md`, and deleted the nested instruction
files.

| Project              | Paths                              | Files | Disposition                  | Owning epic      |
| -------------------- | ---------------------------------- | ----- | ---------------------------- | ---------------- |
| sase `demos/tapes/`  | folded into `sase/memory/demos.md` | 0     | folded into reference memory | E4 nested-guides |
| sase `src/sase/ace/` | folded into `sase/memory/ace.md`   | 0     | folded into reference memory | E4 nested-guides |
| sase `tools/`        | folded into `sase/memory/tools.md` | 0     | folded into reference memory | E4 nested-guides |

## Hand-written (historical inventory)

`repo-owned`. These stay; no migration epic rewrites another repo's docs.

| Repo                    | Paths                                                                 | Count | Owning epic  |
| ----------------------- | --------------------------------------------------------------------- | ----- | ------------ |
| sase-core               | `AGENTS.md`, `CLAUDE.md` (`@AGENTS.md`), `GEMINI.md` (`@./AGENTS.md`) | 3     | none (stays) |
| sase-telegram           | `AGENTS.md`, `CLAUDE.md`                                              | 2     | none (stays) |
| sase-listen             | `AGENTS.md`, `CLAUDE.md`                                              | 2     | none (stays) |
| sase-research-artifacts | `AGENTS.md`, `CLAUDE.md`                                              | 2     | none (stays) |
| sase-github             | `CLAUDE.md`                                                           | 1     | none (stays) |
| sase-nvim               | no tracked instruction files (`README.md` is the instruction surface) | 0     | none (stays) |

Note: the epic plan expected 2 instruction files in every plugin repo, but sase-nvim has
none tracked — only `README.md`. Nothing to migrate there.

## Config-based discovery surfaces

| Surface                       | Mechanism                                                                                                                                                                                                                                                                    | Disposition                                 | Owning epic |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ----------- |
| Codex shadow-home `AGENTS.md` | Per-run allowlist `$CODEX_HOME`; SQLite state is never linked (`sase-11s`). With `codex_explicit_instructions` disabled, `~/AGENTS.md` is linked when no global file wins (`_codex_home.py`). With the flag enabled, SASE-owned global copies and that fallback are omitted. | `done` (E3); fallback limitation documented | E3          |

Claude's explicit path excludes exact SASE-owned root and home files. Nested instruction
files are no longer present in this repository after E4 folded those guides into
reference memory; Codex disables native project-document loading across a managed
project for explicit invocations. Grok uses `--rules`; Muse uses a prompt prefix. See
[provider behavior](../../docs/instruction_bundles.md#provider-behavior-at-a-glance) and
the [Codex fallback limitation](../../docs/llms.md#codex-instruction-delivery).
