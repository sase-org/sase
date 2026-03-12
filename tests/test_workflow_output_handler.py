"""Tests for WorkflowOutputHandler methods using Rich console capture."""

from io import StringIO

from inline_snapshot import snapshot
from rich.console import Console

from sase.xprompt.workflow_output import (
    LoopInfo,
    ParentStepContext,
    WorkflowOutputHandler,
)


def _make_handler() -> tuple[WorkflowOutputHandler, StringIO]:
    """Create handler with a StringIO-backed console for output capture."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    handler = WorkflowOutputHandler(console=console)
    return handler, buf


class TestOnWorkflowStart:
    def test_displays_workflow_info(self) -> None:
        handler, buf = _make_handler()
        handler.on_workflow_start("my_workflow", {"x": 1, "y": "hello"}, 3)
        output = buf.getvalue()
        assert "my_workflow" in output
        assert 'x=1, y="hello"' in output
        assert "3" in output

    def test_truncates_long_inputs(self) -> None:
        handler, buf = _make_handler()
        long_inputs = {f"key_{i}": f"value_{i}" for i in range(20)}
        handler.on_workflow_start("wf", long_inputs, 1)
        output = buf.getvalue()
        assert "..." in output

    def test_empty_inputs(self) -> None:
        handler, buf = _make_handler()
        handler.on_workflow_start("wf", {}, 1)
        output = buf.getvalue()
        assert "(none)" in output


class TestOnStepStart:
    def test_basic_step(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_start("my_step", "bash", step_index=0, total_steps=3)
        output = buf.getvalue()
        assert "Step 1/3" in output
        assert "my_step" in output
        assert "bash" in output

    def test_with_condition(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_start(
            "cond_step",
            "python",
            0,
            1,
            condition="x > 0",
            condition_result=True,
        )
        output = buf.getvalue()
        assert "x > 0" in output
        assert "true" in output

    def test_with_condition_false(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_start(
            "cond_step",
            "python",
            0,
            1,
            condition="x > 0",
            condition_result=False,
        )
        output = buf.getvalue()
        assert "false" in output

    def test_with_loop_info(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="for", items=["a", "b", "c"])
        handler.on_step_start("loop_step", "bash", 0, 1, loop_info=loop)
        output = buf.getvalue()
        assert "3 items" in output

    def test_with_parent_step_context(self) -> None:
        handler, buf = _make_handler()
        ctx = ParentStepContext(step_index=1, total_steps=5)
        handler.on_step_start("sub", "python", 2, 3, parent_step_context=ctx)
        output = buf.getvalue()
        assert "Step 2c/5" in output


class TestOnStepIteration:
    def test_displays_iteration_info(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_iteration("s", 1, 3, {"item": "alpha"})
        output = buf.getvalue()
        assert "1/3" in output
        assert "alpha" in output


class TestOnStepComplete:
    def test_shows_completion(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output=None, duration=1.23)
        output = buf.getvalue()
        assert "Completed" in output
        assert "1.23s" in output

    def test_with_dict_output(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output={"key": "val"}, duration=0.5)
        output = buf.getvalue()
        assert "Output" in output

    def test_with_list_output(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output=[1, 2, 3], duration=0.1)
        output = buf.getvalue()
        assert "Output" in output

    def test_with_string_output(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output="result text", duration=0.1)
        output = buf.getvalue()
        assert "Output" in output

    def test_calculates_duration_from_start_time(self) -> None:
        handler, buf = _make_handler()
        handler._step_start_time = 1000.0
        # duration=None triggers time.time() calculation, but output just needs "Completed"
        handler.on_step_complete("s", output=None, duration=2.0)
        output = buf.getvalue()
        assert "Completed" in output

    def test_with_data_key_output(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output={"_data": {"inner": 1}}, duration=0.1)
        output = buf.getvalue()
        assert "Output" in output

    def test_with_raw_key_output(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_complete("s", output={"_raw": "raw content"}, duration=0.1)
        output = buf.getvalue()
        assert "Output" in output


class TestOnStepSkip:
    def test_shows_skip(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_skip("s", reason="condition false")
        output = buf.getvalue()
        assert "Skipped" in output
        assert "condition false" in output

    def test_skip_no_reason(self) -> None:
        handler, buf = _make_handler()
        handler.on_step_skip("s")
        output = buf.getvalue()
        assert "Skipped" in output


class TestOnRepeatIteration:
    def test_shows_iteration(self) -> None:
        handler, buf = _make_handler()
        handler.on_repeat_iteration("s", 2, 5, True)
        output = buf.getvalue()
        assert "2/5" in output
        assert "True" in output


class TestOnParallelStart:
    def test_shows_parallel_info(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_start("p", ["step_a", "step_b"])
        output = buf.getvalue()
        assert "2 steps" in output
        assert "step_a" in output


class TestOnParallelStepComplete:
    def test_success(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_step_complete("p", "sub", output="ok", error=None)
        output = buf.getvalue()
        assert "sub" in output

    def test_error(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_step_complete("p", "sub", output=None, error="boom")
        output = buf.getvalue()
        assert "boom" in output

    def test_long_output_truncated(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_step_complete("p", "sub", output="x" * 60, error=None)
        output = buf.getvalue()
        assert "..." in output


class TestOnParallelComplete:
    def test_success(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_complete("p", {"a": 1, "b": 2}, errors=None)
        output = buf.getvalue()
        assert "2 results" in output

    def test_with_errors(self) -> None:
        handler, buf = _make_handler()
        handler.on_parallel_complete("p", {}, errors=["err1", "err2"])
        output = buf.getvalue()
        assert "2 error" in output


class TestOnWorkflowComplete:
    def test_shows_completion(self) -> None:
        handler, buf = _make_handler()
        handler.on_workflow_complete(None, total_duration=5.67)
        output = buf.getvalue()
        assert "completed successfully" in output
        assert "5.67s" in output

    def test_no_duration(self) -> None:
        handler, buf = _make_handler()
        handler._workflow_start_time = None
        handler.on_workflow_complete(None, total_duration=None)
        output = buf.getvalue()
        assert "completed successfully" in output


class TestOnWorkflowFailed:
    def test_shows_failure(self) -> None:
        handler, buf = _make_handler()
        handler.on_workflow_failed("something went wrong", total_duration=1.5)
        output = buf.getvalue()
        assert "failed" in output
        assert "something went wrong" in output
        assert "1.5" in output

    def test_no_duration(self) -> None:
        handler, buf = _make_handler()
        handler._workflow_start_time = None
        handler.on_workflow_failed("err", total_duration=None)
        output = buf.getvalue()
        assert "err" in output


class TestPrintLoopInfo:
    def test_for_loop(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="for", items=["x", "y"])
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "2 items" in output

    def test_repeat_loop(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="repeat", max_iterations=10)
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "repeat" in output
        assert "10" in output

    def test_while_loop(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="while", max_iterations=5)
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "while" in output
        assert "5" in output

    def test_for_loop_long_items_truncated(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="for", items=list(range(100)))
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "..." in output

    def test_repeat_no_max(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="repeat")
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "repeat" in output

    def test_while_no_max(self) -> None:
        handler, buf = _make_handler()
        loop = LoopInfo(loop_type="while")
        handler._print_loop_info(loop)
        output = buf.getvalue()
        assert "while" in output
