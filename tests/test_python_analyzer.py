import pytest

from ai_review.analyzers.python_ast import PythonAnalyzer
from ai_review.analyzers.errors import AnalyzerError


def test_python_analyzer_top_level_only():
    source = """
import os

def top_level(a, b):
    return a + b

class Foo:
    def method(self):
        return 1

    def nested(self):
        def inner():
            return 2
        return inner()
"""
    analyzer = PythonAnalyzer()
    summary = analyzer.analyze_content(source)

    functions = [fn["name"] for fn in summary["functions"]]
    assert functions == ["top_level"]

    classes = [cls["name"] for cls in summary["classes"]]
    assert classes == ["Foo"]


def test_python_analyzer_invalid_syntax():
    analyzer = PythonAnalyzer()
    with pytest.raises(AnalyzerError):
        analyzer.analyze_content("def bad(:\n")


def test_python_relative_imports_and_async_signatures():
    from ai_review.analyzers.graph import GraphService

    analyzer = PythonAnalyzer()
    summary = analyzer.analyze_content(
        "from ..shared import Client\nfrom . import helper\n"
        "async def lookup(item, /, *, exact=False, **options): pass\n"
    )
    graph = GraphService()
    graph.build_from_analysis({
        "pkg/sub/api.py": {"summary": summary},
        "pkg/shared.py": {},
        "pkg/sub/helper.py": {},
    })

    assert graph.adj_list["pkg/sub/api.py"] == ["pkg/shared.py", "pkg/sub/helper.py"]
    assert "async def lookup(item, /, *, exact=..., **options)" in analyzer.format_summary(summary)


def test_module_imports_do_not_fall_back_to_package_initializers():
    from ai_review.analyzers.graph import GraphService

    analyzer = PythonAnalyzer()
    graph = GraphService()
    graph.build_from_analysis({
        "__init__.py": {},
        ".py": {},
        "helper.py": {},
        "pkg/__init__.py": {},
        "app.py": {"summary": analyzer.analyze_content("import os, json, pkg.missing")},
        "consumer.py": {"summary": analyzer.analyze_content("import app, helper")},
        "package_consumer.py": {"summary": analyzer.analyze_content("from pkg import missing")},
    })

    assert graph.adj_list["app.py"] == []
    assert graph.adj_list["consumer.py"] == ["app.py", "helper.py"]
    assert graph.adj_list["package_consumer.py"] == ["pkg/__init__.py"]
    assert graph.get_impacted_files(["__init__.py"], depth=2) == {}
