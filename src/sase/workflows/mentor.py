"""Workflow for running mentor agents on CLs."""

import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from rich.console import Console
from rich.markup import escape as _esc

from sase.ace.changespec import find_all_changespecs
from sase.ace.mentor_output import (
    MENTOR_OUTPUT_JSON_SCHEMA,
    MentorComment,
    MentorOutput,
    save_file_snapshots,
    save_mentor_output,
)
from sase.config.mentor import (
    MentorConfig,
    get_mentor_from_profile,
    get_mentor_profile_by_name,
)
from sase.llm_provider import LLMInvocationError, invoke_agent
from sase.main.query_handler import (
    execute_standalone_steps,
    expand_embedded_workflows_in_query,
)
from sase.output import print_artifact_created, print_status, print_workflow_header
from sase.core.time import generate_timestamp
from sase.artifacts import (
    create_artifacts_directory,
    finalize_sase_log,
    generate_workflow_tag,
    initialize_sase_log,
)
from sase.content import ensure_str_content
from sase.workflows.base import BaseWorkflow
from sase.workflows.utils import get_cl_name_from_branch
from sase.xprompt.output_validation import extract_structured_content
from sase.xprompt.tags import XPromptTag, get_by_tag, get_by_tag_strict
from sase.xprompt.workflow_executor_utils import render_template

log = logging.getLogger(__name__)


def _build_mentor_prompt(
    mentor: MentorConfig,
    cl_name: str,
    vcs_type: str = "hg",
    project: str | None = None,
) -> str:
    """Build the mentor prompt by resolving the #mentor xprompt workflow.

    Resolves the ``#mentor`` tagged xprompt, executes its pre-steps
    (focus area rendering), and returns the rendered prompt_part.
    The result contains embedded workflow references (``#hg``, ``#json``)
    that must be expanded by ``expand_embedded_workflows_in_query``.

    Args:
        mentor: The mentor configuration.
        cl_name: CL name passed to the embedded workflow.
        vcs_type: VCS workflow type (``"hg"`` or ``"gh"``).
        project: Optional project name for xprompt resolution.

    Returns:
        The rendered prompt with embedded workflow references.
    """
    mentor_wf = get_by_tag_strict(XPromptTag.mentor, project=project)
    if mentor_wf is None:
        raise RuntimeError(
            "No xprompt with tag 'mentor' found. "
            "Ensure src/sase/xprompts/mentor.yml is installed."
        )

    # Build input context
    focus_areas_json = json.dumps(
        [asdict(fa) for fa in mentor.focus_areas], ensure_ascii=False
    )
    schema = json.dumps(MENTOR_OUTPUT_JSON_SCHEMA, ensure_ascii=False)
    # Resolve the diff_file-tagged xprompt (e.g., #pr_diff or #cl_diff)
    diff_wf = get_by_tag(XPromptTag.diff_file, project=project)
    diff_ref = diff_wf.name if diff_wf else ""

    context: dict[str, str] = {
        "role": mentor.role,
        "focus_areas_json": focus_areas_json,
        "schema": schema,
        "cl_name": cl_name,
        "vcs_type": vcs_type,
        "diff_ref": diff_ref,
    }

    # Execute pre-prompt steps (render_focus_areas python step)
    pre_steps = mentor_wf.get_pre_prompt_steps()
    if pre_steps:
        context = execute_standalone_steps(pre_steps, context, "mentor", None)

    # Render prompt_part with context
    prompt_part_content = mentor_wf.get_prompt_part_content()
    if not prompt_part_content:
        raise RuntimeError(
            "The #mentor xprompt has no prompt_part step. "
            "Check src/sase/xprompts/mentor.yml."
        )
    return render_template(prompt_part_content, context)


def _parse_mentor_json(
    response_content: str,
    profile_name: str,
    mentor_name: str,
) -> MentorOutput | None:
    """Parse the mentor's JSON response into a MentorOutput.

    Extracts JSON from code fences in the response and validates
    the required fields.

    Args:
        response_content: The raw LLM response text.
        profile_name: Profile name for the output metadata.
        mentor_name: Mentor name for the output metadata.

    Returns:
        Parsed MentorOutput, or None if parsing fails.
    """
    try:
        data, _ = extract_structured_content(response_content)
    except Exception:
        log.warning("Failed to extract JSON from mentor response")
        return None

    if not isinstance(data, dict):
        log.warning("Mentor response is not a JSON object")
        return None

    try:
        comments = [
            MentorComment(
                focus_name=c["focus_name"],
                file_path=c["file_path"],
                line_number=c["line_number"],
                description=c["description"],
                severity=c["severity"],
            )
            for c in data.get("comments", [])
        ]
        return MentorOutput(
            mentor_name=data.get("mentor_name", mentor_name),
            profile_name=data.get("profile_name", profile_name),
            role=data.get("role", ""),
            comments=comments,
        )
    except (KeyError, TypeError) as e:
        log.warning("Failed to parse mentor JSON: %s", e)
        return None


def _find_changespec_by_name(cl_name: str) -> tuple[str | None, str | None]:
    """Find a ChangeSpec by name across all project files.

    Args:
        cl_name: The CL name to search for.

    Returns:
        Tuple of (project_file_path, project_name) if found, (None, None) otherwise.
    """
    all_changespecs = find_all_changespecs()
    for cs in all_changespecs:
        if cs.name == cl_name:
            # Extract project name from file path
            # Path format: ~/.sase/projects/<project>/<project>.gp
            project_name = os.path.basename(os.path.dirname(cs.file_path))
            return cs.file_path, project_name
    return None, None


class MentorWorkflow(BaseWorkflow):
    """A workflow for running mentor agents on CLs."""

    def __init__(
        self,
        profile_name: str,
        mentor_name: str,
        cl_name: str | None = None,
        timestamp: str | None = None,
        who: str | None = None,
    ) -> None:
        """Initialize the mentor workflow.

        Args:
            profile_name: Name of the profile containing the mentor.
            mentor_name: Name of the mentor to use.
            cl_name: CL name to work on (defaults to current branch name).
            timestamp: Timestamp for chat file naming (YYmmdd_HHMMSS format).
            who: Optional identifier for the mentor run.
        """
        self.profile_name = profile_name
        self.mentor_name = mentor_name
        self.cl_name = cl_name
        self._timestamp = timestamp
        self._who = who
        self.response_path: str | None = None
        self.comment_count: int = 0
        self._mentor: MentorConfig | None = None
        self._console = Console()

    @property
    def name(self) -> str:
        """Return the name of this workflow."""
        return "mentor"

    @property
    def description(self) -> str:
        """Return a description of what this workflow does."""
        return f"Run mentor '{self.mentor_name}' on a CL"

    def run(self) -> bool:
        """Run the mentor workflow."""
        # Resolve CL name
        resolved_cl_name = self.cl_name or get_cl_name_from_branch()
        if not resolved_cl_name:
            print_status(
                "Error: Could not determine CL name. Use --cl to specify.", "error"
            )
            return False

        # Load profile and mentor config
        profile = get_mentor_profile_by_name(self.profile_name)
        if not profile:
            print_status(
                f"Error: Profile '{self.profile_name}' not found in "
                "~/.config/sase/sase.yml",
                "error",
            )
            return False

        self._mentor = get_mentor_from_profile(profile, self.mentor_name)
        if not self._mentor:
            available = [m.mentor_name for m in profile.mentors]
            print_status(
                f"Error: Mentor '{self.mentor_name}' not found in profile "
                f"'{self.profile_name}'. Available mentors: {', '.join(available)}",
                "error",
            )
            return False

        # Find the ChangeSpec and its project
        project_file, project = _find_changespec_by_name(resolved_cl_name)
        if not project_file or not project:
            print_status(
                f"Error: ChangeSpec '{resolved_cl_name}' not found in any project file.",
                "error",
            )
            return False

        # Detect VCS type for the project
        from sase.workspace_provider import detect_workflow_type

        vcs_type = detect_workflow_type(project_file)

        # Generate workflow tag
        workflow_tag = generate_workflow_tag()
        print_workflow_header(f"mentor-{self.mentor_name}", workflow_tag)

        # Save current directory
        original_dir = os.getcwd()

        try:
            # Generate timestamp if not provided (interactive mode)
            if self._timestamp is None:
                self._timestamp = generate_timestamp()

            # Create artifacts directory using the same timestamp as the agent suffix
            # This ensures the Agents tab can find the prompt file
            artifacts_dir = create_artifacts_directory(
                f"mentor-{self.mentor_name}",
                project_name=Path(project_file).parent.name,
                timestamp=self._timestamp,
            )
            print_status(f"Created artifacts directory: {artifacts_dir}", "success")

            # Initialize the sase.md log
            initialize_sase_log(
                artifacts_dir, f"mentor-{self.mentor_name}", workflow_tag
            )

            # Build prompt via #mentor xprompt workflow
            print_status("Building mentor prompt...", "progress")
            prompt = _build_mentor_prompt(
                self._mentor, resolved_cl_name, vcs_type, project=project
            )

            # Expand embedded workflows (#hg for VCS context, #json for output format)
            expanded_prompt, post_workflows = expand_embedded_workflows_in_query(
                prompt, artifacts_dir
            )

            print_status(f"Running mentor '{self.mentor_name}'...", "progress")
            try:
                response = invoke_agent(
                    expanded_prompt,
                    agent_type=f"mentor-{self.mentor_name}",
                    model_tier="large",
                    iteration=1,
                    workflow_tag=workflow_tag,
                    artifacts_dir=artifacts_dir,
                    workflow=f"mentor-{self.mentor_name}",
                    timestamp=self._timestamp,
                    branch_or_workspace=resolved_cl_name,
                )
            except LLMInvocationError as e:
                from langchain_core.messages import AIMessage

                response = AIMessage(content=str(e))
            response_content = ensure_str_content(response.content)

            # Execute post-steps from embedded workflows (#json validation)
            for ewf_result in post_workflows:
                ewf_result.context["_prompt"] = expanded_prompt
                ewf_result.context["_response"] = response_content
                ewf_result.context["_start_timestamp"] = self._timestamp
                ewf_result.context["cl_name"] = resolved_cl_name
                try:
                    execute_standalone_steps(
                        ewf_result.post_steps,
                        ewf_result.context,
                        f"mentor-{self.mentor_name}-embedded",
                        artifacts_dir,
                    )
                except Exception as step_error:
                    print(f"Warning: Some embedded workflow steps failed: {step_error}")
                    import traceback

                    traceback.print_exc()

            # Check for empty response (indicates silent failure like permission issues)
            response_text = response.content
            if isinstance(response_text, str):
                response_text = response_text.strip()
            if not response_text:
                print_status(
                    f"Error: Mentor '{self.mentor_name}' returned empty response. "
                    "This may indicate a permission issue with ~/.sase/chats/",
                    "error",
                )
                return False

            # Save response
            self.response_path = os.path.join(artifacts_dir, "mentor_response.txt")
            with open(self.response_path, "w") as f:
                f.write(response_content)
            print_artifact_created(self.response_path)

            # Parse structured JSON output and save
            mentor_output = _parse_mentor_json(
                response_content, self.profile_name, self.mentor_name
            )
            if mentor_output is not None:
                self.comment_count = len(mentor_output.comments)
                save_mentor_output(
                    resolved_cl_name,
                    self.profile_name,
                    self.mentor_name,
                    self._timestamp,
                    mentor_output,
                )
                # Snapshot files referenced by comments for fast review
                if mentor_output.comments:
                    unique_paths = {c.file_path for c in mentor_output.comments}
                    file_contents: dict[str, str] = {}
                    for fp in unique_paths:
                        try:
                            full_path = os.path.join(os.getcwd(), fp)
                            with open(
                                full_path, encoding="utf-8", errors="replace"
                            ) as fh:
                                file_contents[fp] = fh.read()
                        except OSError:
                            log.debug("Could not snapshot %s for mentor review", fp)
                    if file_contents:
                        rev = ""
                        try:
                            rev = subprocess.run(
                                ["git", "rev-parse", "HEAD"],
                                capture_output=True,
                                text=True,
                                check=True,
                            ).stdout.strip()
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            pass
                        save_file_snapshots(
                            resolved_cl_name,
                            self.profile_name,
                            self.mentor_name,
                            self._timestamp,
                            rev,
                            file_contents,
                        )

                print_status(
                    f"Mentor produced {self.comment_count} comment(s)", "success"
                )
            else:
                log.warning(
                    "Could not parse structured JSON from mentor response; "
                    "raw response saved to %s",
                    self.response_path,
                )

            print_status("Mentor workflow complete!", "success")
            finalize_sase_log(
                artifacts_dir, f"mentor-{self.mentor_name}", workflow_tag, True
            )

            return True

        except KeyboardInterrupt:
            self._console.print(
                "\n[yellow]Mentor workflow interrupted (Ctrl+C)[/yellow]"
            )
            return False
        except Exception as e:
            self._console.print(f"[red]Mentor workflow crashed: {_esc(str(e))}[/red]")
            return False
        finally:
            os.chdir(original_dir)


def main() -> NoReturn:
    """Main entry point for the mentor workflow."""
    import argparse

    parser = argparse.ArgumentParser(description="Run mentor workflow")
    parser.add_argument(
        "mentor_spec",
        help="Profile and mentor name in format 'profile:mentor' (e.g., 'code:comments')",
    )
    parser.add_argument(
        "--cl", dest="cl_name", help="CL name (defaults to branch name)"
    )
    args = parser.parse_args()

    # Parse profile:mentor format
    if ":" not in args.mentor_spec:
        print(
            f"Error: mentor_spec must be in format 'profile:mentor', "
            f"got '{args.mentor_spec}'",
            file=sys.stderr,
        )
        sys.exit(1)
    profile_name, mentor_name = args.mentor_spec.split(":", 1)

    workflow = MentorWorkflow(
        profile_name=profile_name,
        mentor_name=mentor_name,
        cl_name=args.cl_name,
    )
    success = workflow.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
