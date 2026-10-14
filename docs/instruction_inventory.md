# Instruction Inventory

Every surface where an agent can load instructions, with its disposition for the
memory-built instruction migration (E1–E5). Counts verified 2026-10-06 with
`git ls-files`, `ls ~`, and `sase repo open` (read-only; no other repo was modified).

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

Sase nested scopes (15 more files) are split below: each scope's `AGENTS.md` is
hand-written, with 4 byte-identical shims projected beside it by `sase memory init`.

| Project              | Paths                 | Files | Disposition                                  | Owning epic                   |
| -------------------- | --------------------- | ----- | -------------------------------------------- | ----------------------------- |
| sase `demos/tapes/`  | `AGENTS.md` + 4 shims | 5     | `AGENTS.md` `repo-owned`; shims `projection` | E2 (bundle migration decides) |
| sase `src/sase/ace/` | `AGENTS.md` + 4 shims | 5     | `AGENTS.md` `repo-owned`; shims `projection` | E2 (bundle migration decides) |
| sase `tools/`        | `AGENTS.md` + 4 shims | 5     | `AGENTS.md` `repo-owned`; shims `projection` | E2 (bundle migration decides) |

## Hand-written (12, plus one README-only repo)

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

| Surface                       | Mechanism                                                                                                                                | Disposition | Owning epic |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ----------- |
| Codex shadow-home `AGENTS.md` | Per-run allowlist `$CODEX_HOME`: no SASE `AGENTS.md` when `codex_explicit_instructions` is on; sqlite state is never linked (`sase-11s`) | `done` (E3) | E3          |

No other provider config points at `~/AGENTS.md`: Grok receives `--rules` explicitly,
Claude loads natively, and the `~/AGENTS.md` read in `instructions/run_index.py` is the
scoreboard's own expected-H1 lookup, not delivery.
