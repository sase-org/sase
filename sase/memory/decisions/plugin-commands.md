---
keyword: Plugins May Mount Top-Level Commands
aliases:
  - plugin commands
  - sase_commands
  - command plugins
summary:
  Plugins may mount top-level `sase <name>` commands through `sase_commands`; listen's
  standalone-only stance is superseded.
---

**Claim.** Plugins may mount top-level `sase <name>` commands through the
metadata-declared `sase_commands` entry-point group, with sase-listen's `sase listen` as
the first consumer. This supersedes the `plan:202610/sase_listen.md` stance that
sase-listen stays a standalone tool rather than a sase plugin: sase-listen keeps its
standalone `sase-listen` binary and never imports sase, and additionally ships
`sase listen` through the generic mechanism.

**Why.** Users look in `sase -h` first and expect one CLI; a standalone-only listen
leaves help, completion, doctor, and install lifecycle split across two tools. Rejected
alternatives: grafting listen's argparse subtree into sase's parser (both CLIs use
`add_subparsers(dest="command")`, so grafting breaks dispatch), and a sase-specific
listen integration (every future command plugin would need its own wiring). The accepted
split is that the plugin parses, via its own `main(argv, prog)`, while sase owns
everything around the command: discovery, name reservation, collisions, help,
completion, cache freshness, install lifecycle, and diagnostics. Plugin subtrees are
exempt from sase's CLI rules ([[cli_rules.md]]).

**Cost.** A frozen adapter contract (`main`, `build_parser`, optional `SUMMARY` and
`SASE_COMMAND_API`), a pre-argparse dispatch fast path on unknown root words, and the
permanent `SASE_DISABLE_PLUGIN_COMMANDS` operational switch.

**Reopens when.** A second command plugin proves the contract wrong — for example a
command that cannot live behind `main(argv, prog)` — not from a preference for bespoke
per-plugin wiring.
