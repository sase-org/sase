# SASE Blog Series

SASE, short for **Structured Agentic Software Engineering**, uses **agentic software engineering** to mean software work
where AI agents operate inside durable engineering systems: plans, work queues, review records, tests, commits,
dependencies, and handoffs. The SASE Blog Series explains why that coordination layer matters and how SASE implements
it.

The canonical essays live on the [SASE Blog](../blog/index.md). This page is the series hub: it lists the published
posts and points readers at the current product guides for further reading.

## The Series

The SASE Blog Series begins with [00], the argument for durable orchestration around coding-agent work, then moves to
[01], the 15-minute hands-on path for installing SASE and launching a safe first run. Later posts will cover reusable
prompts, background automation, planning, review state, mobile control, editor integration, and the roadmap.

| Post                                                                                                 | Status               |
| ---------------------------------------------------------------------------------------------------- | -------------------- |
| [\[00\] Why Coding Agents Need Orchestration](../blog/posts/why-coding-agents-need-orchestration.md) | Published 2026-05-08 |
| [\[01\] Hello, SASE: Your First 15 Minutes](../blog/posts/hello-sase-your-first-15-minutes.md)       | Published 2026-05-10 |

The remaining series entries are forthcoming. Until each one is published, the public site keeps the draft pages out of
the navigation, generated archive, RSS feed, search index, and sitemap.

## Reader Paths

Alongside the series, the current product guides make each concept concrete:

- [15-minute quickstart](../blog/posts/hello-sase-your-first-15-minutes.md) for the practical install, readiness, and
  first-run path.
- [ACE TUI](../ace.md) for the interactive control surface.
- [Spec-Driven Development](../sdd.md) for plans, epics, legends, and executable phase work.
- [ChangeSpecs](../change_spec.md) for reviewable CL/PR-sized work records.
- [Beads](../beads.md) for issue-like work items, dependency ordering, and multi-agent epic execution.
- [XPrompts](../xprompt.md) for reusable prompt templates and workflow packaging.
- [GitHub](https://github.com/sase-org/sase) for source, issues, and implementation details.

## Publishing Notes

The blog is the canonical publishing surface for SASE essays. Unpublished drafts keep their stable slugs, frontmatter
dates, and categories in the repository, but only published entries are linked from the public site, RSS feed, search
index, and generated archive pages.
