import pytest

from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.js_heuristic import JSHeuristicAnalyzer
from ai_review.analyzers.js_treesitter import TreeSitterJSAnalyzer


@pytest.mark.parametrize("engine", ["heuristic", "tree-sitter"])
def test_js_exported_declarations_and_arrow_arguments(engine):
    if engine == "tree-sitter":
        try:
            analyzer = TreeSitterJSAnalyzer("tsx")
        except AnalyzerError:
            pytest.skip("Compatible tree-sitter bindings are unavailable")
    else:
        analyzer = JSHeuristicAnalyzer()

    source = (
        "// café\nexport async function greet(name) { return name }\n"
        "export const render = data => <p>{data}</p>\n"
        "export {render as example};"
    )
    summary = analyzer.analyze_content(source)
    formatted = analyzer.format_summary(summary)

    assert "function greet(name): ..." in formatted
    assert "function render(data): ..." in formatted
    assert "exports: example, greet, render" in formatted
