# Artifact References

Artifact references are typed `@<kind>:<argument>` citations in launch prompts. They are
not xprompts: SASE resolves them late in prompt preprocessing, after xprompt expansion
and command substitution, using the project context for that prompt segment. Each
successful reference expands to prompt text, records a per-agent use row, and can
publish as a numbered Markdown reference link.

## Prompt Grammar

Use the unquoted form when the argument contains no spaces:

```text
@plan:202608/artifact_ref_contract.md
@bead:sase-js.9
@stitch:sase@f499469
```

Use quotes when the argument contains spaces:

```text
@patch:"artifact references adoption"
@file:"~/bob/Research Inbox.md"
```

Fragments such as `#L10-L20`, `#page=2`, and `#t=30` stay attached to the reference when
the target kind supports them. Inline code, fenced code, and disabled xprompt regions
stay literal. Unknown `@kind:` text remains prose; malformed or missing references for a
known kind stop launch with a diagnostic.

## Live Kinds

Canonical live categories are:

| Form                           | Meaning                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `@stitch:<sha>`                | Commit in the prompt segment's project repository                       |
| `@stitch:<repo>@<sha>`         | Commit in a named primary, linked, or sidecar repo                      |
| `@patch:<name>`                | Patch in the prompt segment's project                                   |
| `@bead:<id>`                   | Bead by full id or unambiguous shorthand                                |
| `@agent:<name>`                | Published agent page and related transcript context                     |
| `@file:<path>`                 | Allow-listed local file captured by content digest                      |
| `@file:<source>:<digest>`      | Indexed file, where source is `explicit` or `default`                   |
| `@<document-kind>:<repo-path>` | Document in a configured artifact sidecar, such as `plan` or `research` |

The built-in plans sidecar exposes `@plan:<path>` through `ref: {use: plan}`. The
`sase-research` plugin exposes `@research:<path>` for the research content sidecar.
Other artifact sidecars can add their own document kind with an inline `ref:` spec or
with `ref.use` from an installed provider plugin.

Compatibility readers preserve older persisted references. `@commit:` canonicalizes to
`@stitch:` permanently. `@plans:` parses with migration guidance to `@plan:`. Historical
`@chat:` and `@bug:` references remain archive readers and are not offered for new
authoring. The retired `#ref/<kind>:<argument>` xprompt renderer syntax is not accepted.

## Project Context

Short references resolve from the prompt segment, not from the current working
directory. A segment's leading `#git:`, `#gh:`, or other VCS workflow tag supplies the
project context. If a segment has no explicit tag, the caller's launch identity supplies
it.

Context affects ambiguity:

- `@stitch:<sha>` searches the selected project's primary repo; qualify with
  `@stitch:<repo>@<sha>` when needed.
- `@patch:<name>` searches the selected project's active Patch store, then its archive.
- A short `@bead:<suffix>` searches the selected project first, then rejects
  cross-project collisions instead of guessing.
- `@agent:<local-name>` canonicalizes to the durable global agent identity.

## Allow-Listed Files

Path-backed `@file:` references are opt-in. Configure roots in `sase.yml`:

```yaml
artifact_refs:
  file:
    roots:
      - name: bob
        path: ~/bob
        path_globs: ["**/*.md"]
```

The root name becomes the portable logical identity in published metadata. `path` must
be absolute or `~/` rooted. `path_globs` are root-relative POSIX globs with `!`
exclusions. SASE accepts regular files that stay under exactly one effective root, pass
the glob policy, and fit the configured capture size limit.

At launch, SASE reads the bytes once, hashes them with SHA-256, stores the captured
object, and expands the prompt to that immutable copy. Later source edits do not change
what the agent received.

## Provider Specs

Document artifact providers are declarative. A project can start from an installed
provider:

```yaml
repos:
  sidecar:
    custom:
      research:
        ref:
          use: research
```

or define the same policy inline:

```yaml
repos:
  sidecar:
    custom:
      design:
        ref:
          kind: design
          expansion_format:
            "the {checkout_path} file in the {sidecar_role} artifact repo"
          properties: {}
          detail: {}
          identity: {}
          inventory:
            globs: ["**/*.md", "!drafts/**"]
          publication:
            link: vcs_permalink
            referenced_by: markdown_table
```

`use` and inline fields normalize to the same spec. Scalar values replace, mappings
deep-merge, and lists replace. Missing providers fail soft during launch and surface as
`sase doctor -C config.repos` findings. A linked repo or cloned sidecar is not an
installed Python distribution; the provider package must be installed so its entry
points are visible.

## Publication

Published prompts rewrite live references as stable Markdown reference links:

```markdown
Read [@research:202608/report.md][1] and [@file:~/bob/gtd.md][2].

[1]: https://github.com/sase-org/sase--research/blob/<revision>/202608/report.md
[2]: ../../files/objects/sha256/ab/<sha256>
```

Clean repository-backed documents link to the captured revision. Dirty or untracked
documents and local files link to the captured object. Tracking does not depend on
linkability: an unlinkable reference still records a use row and remains visible in the
published prompt metadata.

Artifact repos that opt into `referenced_by: markdown_table` get a managed
`Referenced By` section at the bottom of cited Markdown documents. That section is a
projection of recorded use rows, not part of the document's semantic content version.
