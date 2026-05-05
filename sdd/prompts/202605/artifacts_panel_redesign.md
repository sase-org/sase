---
plan: sdd/legends/202605/artifacts_panel_redesign.md
---
 Can you help me improve the new artifacts panel? I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

- **Directories**: Directories should only ever be considered artifacts if they contain other non-directory artifacts.
  EXCEPTION: The root (/) directory.
- **Files**: All file artifacts should have one of the following types associated with them: plan, diff, chat, project,
  prompt, misc (catch-all). These should be treated as distict, unrelated types (ex: "file(project)" is a different type
  than "file(chat)" or "file(misc)").
- **1. Upgrade the left pane from “list of links” to “relationship navigator.”**: See the
  sdd/research/202505/artifact_graph_navigation_ui.md file for context. Make sure every row fits on one line either by
  compressing the line contents a bit (keep it readable) or by allowing the left panel to expand to be larger (up to 50%
  of the panel) if necessary.
- **2. Add a persistent “where am I?” header.**: See the sdd/research/202505/artifact_graph_navigation_ui.md file for
  context.
- **3. Split local filtering and global search.**: See the sdd/research/202505/artifact_graph_navigation_ui.md file for
  context.
- **5. Add group paging and “show more.”**: See the sdd/research/202505/artifact_graph_navigation_ui.md file for
  context. Let's go with a 10-row max for each group.
- **Apostrophe Keymap**: Add support for using the "'" keymap for row navigation. See how this keymap works on other
  tabs / panels for context.
- **Visual Artifact Indicators**: Add visual artifact indicators to the "CLs" tab and "Agents" tab. This should look the
  same across both tabs and should list the number of linked artifacts, grouped by type.
- **Pretty Colors**: The artifacts panel is currently black-and-white. We should add lots of useful color and really
  strive to make this panel beautiful!
- **Fix Performance**: The startup time increased from ~1s to ~2.5s on this machine for `sase ace`. This is
  unacceptable. I suspect this maybe has something to do with the fact that we index artifacts too much (perhaps on
  every startup)? New artifacts should always be indexed automatically, but it is fine to make existing users sync
  manually (e.g. via a CLI command). They should only need to do this once (since any new artifact after that will be
  automatically indexed).

This is a very large piece of work that should be split into multiple epics. I'll let you decide how many epics to
create, but keep in mind that each epic will be later split into multiple phases that will each be completed by a
distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

