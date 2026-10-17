<!-- generated, do not edit; source: sase/memory/glossary/*.md (tools/render_glossary ABBR_TERMS; run just fix to regenerate) -->
*[project]: A sase project is a named unit of work registered with SASE.
*[workspace]: A sase workspace is a numbered clone of a project's primary repo, managed by the workspace store and tracked in that project's registry.json.
*[agent]: A sase agent is an agent session or a single agent that does not belong to a session.
*[prompt]: A prompt is the text SASE hands to a provider to start an agent turn.
*[macro]: A macro is a reusable prompt triggered with #name in agent prompts.
*[Patch]: A Patch is SASE's local unit of change.
*[bead]: A bead is one tracked work item in SASE's git-native issue tracker.
*[plan]: A plan is a persisted, approved artifact recording the intent behind agent work.
*[TUI]: The TUI is SASE's terminal interface for running agents and reviewing results.
*[epic]: An epic is an executable multi-phase plan run with sase bead work.
*[gate]: A sase gate is a durable, command-backed request for one user decision, created when work must pause for the user.
*[monitor]: A sase monitor is a monitor turn that runs one long command under a detached supervisor, so the command outlives the agent that started it.
*[stitch]: A stitch is the lightweight ordered change record inside a Patch's STITCHES: section.
