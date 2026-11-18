from __future__ import annotations

from typing import Optional

from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.js_heuristic import JSHeuristicAnalyzer
from ai_review.analyzers.types import JSSummary, JSFunctionSummary

try:
    from tree_sitter_languages import get_parser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    get_parser = None


class TreeSitterJSAnalyzer(JSHeuristicAnalyzer):
    """Uses tree-sitter to extract structure from JS/TS files."""

    def __init__(self, language: str = "javascript"):
        if get_parser is None:
            raise AnalyzerError("tree_sitter_languages is not installed")
        self.language = language
        try:
            self.parser = get_parser(language)
        except (TypeError, ValueError, OSError, AttributeError) as exc:
            raise AnalyzerError(f"Cannot load tree-sitter grammar for {language}") from exc

    def analyze_content(self, content: str) -> JSSummary:
        try:
            source = content.encode("utf-8")
            tree = self.parser.parse(source)
        except Exception as exc:
            raise AnalyzerError("Failed to parse JS/TS content") from exc

        summary: JSSummary = {
            "classes": [],
            "functions": [],
            "interfaces": [],
            "types": [],
            "enums": [],
            "imports": [],
            "exports": [],
        }

        root = tree.root_node

        for node in root.children:
            if node.type in ("export_statement", "import_statement"):
                module = _child_text(source, node.child_by_field_name("source"))
                if module:
                    summary["imports"].append(module[1:-1])
            if node.type == "export_statement":
                node = node.child_by_field_name("declaration") or node
            if node.type == "class_declaration":
                name = _child_text(source, node.child_by_field_name("name"))
                if name:
                    summary["classes"].append(name)
            elif node.type in ("function_declaration", "generator_function_declaration"):
                summary["functions"].append(_function_summary(source, node))
            elif node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in node.children:
                    if declarator.type == "variable_declarator":
                        func = _variable_function(source, declarator)
                        if func:
                            summary["functions"].append(func)
            elif node.type == "interface_declaration":
                name = _child_text(source, node.child_by_field_name("name"))
                if name:
                    summary["interfaces"].append(name)
            elif node.type == "type_alias_declaration":
                name = _child_text(source, node.child_by_field_name("name"))
                if name:
                    summary["types"].append(name)
            elif node.type == "enum_declaration":
                name = _child_text(source, node.child_by_field_name("name"))
                if name:
                    summary["enums"].append(name)

        summary["exports"] = self._scan_exports(content)
        return summary


def _child_text(content: bytes, node) -> Optional[str]:
    if node is None:
        return None
    return content[node.start_byte:node.end_byte].decode("utf-8")


def _function_summary(content: bytes, node) -> JSFunctionSummary:
    name = _child_text(content, node.child_by_field_name("name")) or "<anonymous>"
    params = node.child_by_field_name("parameters")
    args = _child_text(content, params) or "()"
    return JSFunctionSummary(name=name, args=args.removeprefix("(").removesuffix(")"))


def _variable_function(content: bytes, declarator) -> Optional[JSFunctionSummary]:
    name_node = declarator.child_by_field_name("name")
    value_node = declarator.child_by_field_name("value")
    if name_node is None or value_node is None:
        return None
    if value_node.type not in ("arrow_function", "function"):
        return None
    name = _child_text(content, name_node) or "<anonymous>"
    params = value_node.child_by_field_name("parameters") or value_node.child_by_field_name("parameter")
    args = _child_text(content, params) or "()"
    return JSFunctionSummary(name=name, args=args.removeprefix("(").removesuffix(")"))
