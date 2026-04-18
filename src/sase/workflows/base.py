from abc import ABC, abstractmethod


class BaseWorkflow(ABC):
    """Base class for all SASE workflows."""

    @abstractmethod
    def run(self) -> int:
        """
        Run the workflow.

        Returns:
            int: 0 (or truthy bool) on success, non-zero on failure. Subclasses
                 may return a richer ``IntEnum`` (e.g. ``RunResult``).
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this workflow."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a description of what this workflow does."""
        pass
