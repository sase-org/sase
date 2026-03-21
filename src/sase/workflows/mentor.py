"""Workflow for running mentor agents on CLs."""

import os
import sys
from pathlib import Path
from typing import NoReturn

from rich.markup import escape as _esc

from sase.ace.changespec import find_all_changespecs
from sase.sase_utils import generate_timestamp
from sase.llm_provider import LLMInvocationError, invoke_agent
from sase.main.query_handler import (
    execute_standalone_steps,
    expand_embedded_workflows_in_query,
)
from sase.mentor_config import (
    MentorConfig,
    get_mentor_from_profile,
    get_mentor_profile_by_name,
)
from rich.console import Console
from sase.rich_utils import print_artifact_created, print_status, print_workflow_header
from sase.shared_utils import (
    create_artifacts_directory,
    ensure_str_content,
    finalize_sase_log,
    generate_workflow_tag,
    initialize_sase_log,
)
from sase.workflows.base import BaseWorkflow
from sase.workflows.utils import get_cl_name_from_branch
from sase.xprompt import process_xprompt_references


def _build_mentor_prompt(
    mentor: MentorConfig,
    cl_name: str,
    mentor_name: str,
    vcs_type: str = "hg",
) -> str:
    """Build the mentor prompt with VCS workspace management prepended.

    Args:
        mentor: The mentor configuration.
        cl_name: CL name passed to the embedded workflow.
        mentor_name: Name of the specific mentor (used in workflow label).
        vcs_type: VCS workflow type (``"hg"`` or ``"gh"``).

    Returns:
        The complete prompt with ``#<vcs_type>:<cl_name>`` prepended and
        xprompt references expanded.
    """
    expanded = process_xprompt_references(mentor.prompt)
    label = f"mentor({mentor_name})"
    return f'#{vcs_type}({cl_name}, workflow_label="{label}")\n\n{expanded}'


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
            who: Optional identifier for who is creating the proposal (e.g., "mentor:name").
        """
        self.profile_name = profile_name
        self.mentor_name = mentor_name
        self.cl_name = cl_name
        self._timestamp = timestamp
        self._who = who
        self.response_path: str | None = None
        self.proposal_id: str | None = None
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

            # Build and run prompt
            print_status("Building mentor prompt...", "progress")
            prompt = _build_mentor_prompt(
                self._mentor, resolved_cl_name, self.mentor_name, vcs_type
            )

            # Expand embedded workflows (like #propose from #p expansion)
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

            # Execute post-steps from embedded workflows
            for ewf_result in post_workflows:
                ewf_result.context["_prompt"] = expanded_prompt
                ewf_result.context["_response"] = response_content
                if self._who:
                    ewf_result.context["who"] = self._who
                ewf_result.context["_start_timestamp"] = self._timestamp
                # Propagate cl_name so #propose targets the correct ChangeSpec
                # even if the workspace branch was renamed (split/revert).
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

                # Extract proposal_id from propose step output
                # (runs even if later steps like 'report' failed)
                create_result = ewf_result.context.get("propose", {})
                if isinstance(create_result, dict) and create_result.get("success") in (
                    True,
                    "true",
                ):
                    self.proposal_id = create_result.get("proposal_id")

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
