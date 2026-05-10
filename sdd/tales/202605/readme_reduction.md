---
create_time: 2026-05-09 20:59:18
status: done
prompt: sdd/prompts/202605/readme_reduction.md
---
# Plan: Reduce README to a concise project front door

## Goal

Replace the current long README with a short, attention-grabbing overview that tells readers what sase is, why it
exists, which agents it supports, how to get started, and where to continue reading. The README should point readers to
https://sase.sh/ for extensive documentation instead of duplicating the docs site.

## Proposed Shape

1. Keep the project title and status badges.
2. Open with a tight product statement: sase orchestrates coding agents into tracked, repeatable engineering workflows.
3. Keep the overview image because it provides a quick visual anchor.
4. Replace the long vision, feature, architecture, CLI, concept, project structure, development, and documentation
   sections with short sections:
   - "Why sase" with 3-5 bullets focused on coordination pain: scheduling, status, repeatable prompts/workflows,
     workspaces, review/commit flow.
   - "Works with your agents" as a compact list/table of supported providers.
   - "Core pieces" with one-line explanations of ACE, AXE, XPrompt, ChangeSpecs, SDD/Beads, and plugins.
   - "Quick start" with minimal install/run commands.
   - "Keep reading" with links to https://sase.sh/ and the most important hosted guides.
5. Preserve local contributor essentials, but keep them compact:
   - Requirements.
   - Development command list.
   - Rust core note.
6. Compress acknowledgements to short attribution paragraphs and links; remove long explanatory essays and embedded
   paper images from README because those belong on the docs site.

## Content Boundaries

- Do not try to maintain a full CLI command reference in README; link to hosted docs instead.
- Do not duplicate the detailed architecture diagram or project tree.
- Do not remove the `docs/` references entirely; provide local paths as a fallback for contributors browsing the repo.
- Avoid adding new factual claims that are not already supported by the current README or docs navigation.

## Verification

1. Check the rendered Markdown by reading the final README top-to-bottom.
2. Confirm the README is substantially shorter than 610 lines and still includes the primary setup commands.
3. Run `just check` after the file change, per repo memory, unless blocked by environment issues.
