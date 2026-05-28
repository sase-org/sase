---
description: Find new medium-to-long article recommendations with a multi-runtime research pass.
input:
  topic:
    type: text
    description: Reading request or topic to search for.
  notes:
    type: text
    default: |
      - ~/org/agent_ref.zo
      - ~/org/ai_ref.zo
      - ~/org/claude_code_ref.zo
      - ~/org/gemini_cli_ref.zo
      - ~/org/xprompt_ref.zo
    description: Reference note files whose existing URLs and titles should be excluded.
xprompts:
  _article_search_agent:
    content: |
      Can you recommend recent, medium-to-long articles that I would likely enjoy reading for this request?

      {{ topic }}

      Read the reference note files below first:

      {{ notes }}

      Treat every URL and title already present in those notes as off-limits, including entries marked unread. Search the
      current web for fresh, high-quality articles that match the request and are not already in those notes.

      Return a ranked list of recommendations. For each item, include the title, link, publication date when available,
      publisher or author when useful, and a short relevance rationale. Prefer substantive essays, engineering writeups,
      surveys, papers with readable HTML, or long-form posts over short announcements.
---

%name:reads.gem-@

%model:gemini/gemini-3.1-pro-preview

%g:read

#{{ "_" }}article_search_agent

---

%name:reads.cld-@

%model:claude/opus

%g:read

#{{ "_" }}article_search_agent

---

%name:reads.cdx-@

%model:codex/gpt-5.5

%g:read

#{{ "_" }}article_search_agent

---

%name:reads.final-@

%wait:reads.gem-@

%wait:reads.cld-@

%wait:reads.cdx-@

%g:read

The three article-search agents have finished. Their chat transcript paths are available here:

{% raw %}{{ wait_chats }}{% endraw %}

Read those transcripts first, then consolidate their recommendations for this request:

{{ topic }}

The reference notes that were used as the exclusion list were:

{{ notes }}

Deduplicate recommendations by URL and by title. Rank the final list using both consensus across the three agents and
your own judgement about fit, freshness, depth, and usefulness. It is fine to favor a strong single-agent find over a
weaker consensus item.

Return a final ranked reading list. For each item, include the title, link, publication date when available, which
agents recommended it, and a concise reason it is worth reading. Call out any near-duplicates or candidates you exclude
because they appear to already be in the reference notes.
