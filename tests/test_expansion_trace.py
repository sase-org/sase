"""Tests for macro expansion trace."""

from unittest.mock import patch

from sase.macro._trace import (
    ExpansionTrace,
    format_circular_ref_diagnostic,
    format_trace,
)
from sase.macro.models import Macro
from sase.macro.processor import process_macro_references


def _make_macros(snippets: dict[str, str]) -> dict[str, Macro]:
    return {
        name: Macro(name=name, content=content, source_path=f"xprompts/{name}.md")
        for name, content in snippets.items()
    }


class TestExpansionTrace:
    def test_trace_records_single_expansion(self) -> None:
        snippets = _make_macros({"greet": "Hello world"})
        trace = ExpansionTrace()
        with patch("sase.macro.processor.get_all_macros", return_value=snippets):
            result = process_macro_references("#greet", trace=trace)

        assert result == "Hello world"
        assert len(trace.records) == 1
        assert trace.records[0].name == "greet"
        assert trace.records[0].source_path == "xprompts/greet.md"
        assert trace.records[0].iteration == 0
        assert trace.total_iterations == 1

    def test_trace_records_multiple_expansions_same_iteration(self) -> None:
        snippets = _make_macros({"a": "alpha", "b": "beta"})
        trace = ExpansionTrace()
        with patch("sase.macro.processor.get_all_macros", return_value=snippets):
            result = process_macro_references("#a and #b", trace=trace)

        assert result == "alpha and beta"
        assert len(trace.records) == 2
        names = {r.name for r in trace.records}
        assert names == {"a", "b"}

    def test_trace_records_recursive_expansion(self) -> None:
        snippets = _make_macros({"outer": "begin #inner end", "inner": "CORE"})
        trace = ExpansionTrace()
        with patch("sase.macro.processor.get_all_macros", return_value=snippets):
            result = process_macro_references("#outer", trace=trace)

        assert result == "begin CORE end"
        assert len(trace.records) == 2
        assert trace.records[0].name == "outer"
        assert trace.records[0].iteration == 0
        assert trace.records[1].name == "inner"
        assert trace.records[1].iteration == 1
        assert trace.total_iterations == 2

    def test_trace_captures_args(self) -> None:
        snippets = _make_macros({"greet": "Hello {1}"})
        trace = ExpansionTrace()
        with patch("sase.macro.processor.get_all_macros", return_value=snippets):
            result = process_macro_references("#greet:world", trace=trace)

        assert result == "Hello world"
        assert trace.records[0].positional_args == ["world"]

    def test_trace_none_does_not_error(self) -> None:
        """Passing trace=None (default) should work without errors."""
        snippets = _make_macros({"x": "expanded"})
        with patch("sase.macro.processor.get_all_macros", return_value=snippets):
            result = process_macro_references("#x")
        assert result == "expanded"

    def test_no_expansions_trace(self) -> None:
        trace = ExpansionTrace()
        with patch("sase.macro.processor.get_all_macros", return_value={}):
            process_macro_references("no refs here", trace=trace)
        assert len(trace.records) == 0
        assert trace.total_iterations == 0


class TestFormatTrace:
    def test_empty_trace(self) -> None:
        trace = ExpansionTrace()
        result = format_trace(trace)
        assert "No macro references" in result

    def test_format_single_record(self) -> None:
        trace = ExpansionTrace()
        trace.add(
            iteration=0,
            name="greet",
            source_path="xprompts/greet.md",
            positional_args=[],
            named_args={},
            expanded_text="Hello world",
        )
        trace.total_iterations = 1
        result = format_trace(trace)
        assert "1 reference(s)" in result
        assert "#greet" in result
        assert "xprompts/greet.md" in result
        assert "Hello world" in result

    def test_format_with_args(self) -> None:
        trace = ExpansionTrace()
        trace.add(
            iteration=0,
            name="greet",
            source_path="config",
            positional_args=["world"],
            named_args={"style": "formal"},
            expanded_text="Hello world (formal)",
        )
        trace.total_iterations = 1
        result = format_trace(trace)
        assert "world" in result
        assert "style=formal" in result


class TestCircularRefDiagnostic:
    def test_identifies_cycle_members(self) -> None:
        trace = ExpansionTrace()
        # Simulate a cycle: #a -> #b -> #a repeated across iterations
        for i in range(20):
            trace.add(
                iteration=i,
                name="a" if i % 2 == 0 else "b",
                source_path=None,
                positional_args=[],
                named_args={},
                expanded_text="...",
            )
        result = format_circular_ref_diagnostic(trace, 100)
        assert "circular reference" in result.lower()
        # Should identify both #a and #b as cycle members
        assert "#a" in result
        assert "#b" in result

    def test_shows_recent_iterations(self) -> None:
        trace = ExpansionTrace()
        for i in range(10):
            trace.add(
                iteration=i,
                name="loop",
                source_path=None,
                positional_args=[],
                named_args={},
                expanded_text="...",
            )
        result = format_circular_ref_diagnostic(trace, 100)
        assert "Last few iterations" in result
