"""C/H analyzer using tree-sitter for structural extraction.

Extracts: #include directives, function definitions (with qualifiers and
params), struct/union/enum declarations, typedefs, and preprocessor macros.
Produces a ``CSummary`` that plugs into the same packet pipeline as
``PythonSummary`` / ``JSSummary``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.types import CSummary, CFunctionSummary
from ai_review.config import ReviewConfig

try:
    import tree_sitter
    import tree_sitter_c as _tsc

    _C_LANGUAGE = tree_sitter.Language(_tsc.language())
except Exception:  # pragma: no cover - optional dependency
    _C_LANGUAGE = None


class CTreeSitterAnalyzer:
    """Uses tree-sitter to extract structure from C/H files."""

    def __init__(self) -> None:
        if _C_LANGUAGE is None:
            raise AnalyzerError(
                "tree-sitter / tree-sitter-c is not installed"
            )
        self.parser = tree_sitter.Parser(_C_LANGUAGE)

    # ------------------------------------------------------------------
    # AnalyzerProtocol
    # ------------------------------------------------------------------

    def analyze_content(self, content: str) -> CSummary:
        """Parse *content* and return a structural summary."""
        try:
            tree = self.parser.parse(content.encode("utf-8"))
        except Exception as exc:
            raise AnalyzerError("Failed to parse C content") from exc

        summary: CSummary = {
            "includes": [],
            "functions": [],
            "structs": [],
            "enums": [],
            "typedefs": [],
            "macros": [],
        }

        self._walk_children(content, tree.root_node, summary)

        return summary

    def format_summary(self, summary: Dict[str, Any]) -> str:
        """Format the C summary into a compressed markdown-like string."""
        lines: List[str] = []

        includes = summary.get("includes", [])
        if includes:
            display = includes[: ReviewConfig.MAX_IMPORTS_IN_SUMMARY]
            lines.append(f"includes: {', '.join(display)}")
            if len(includes) > len(display):
                lines.append(
                    f"includes: ... (+{len(includes) - len(display)} more)"
                )

        for macro in summary.get("macros", []):
            lines.append(f"#define {macro}")

        for td in summary.get("typedefs", []):
            lines.append(f"typedef ... {td};")

        for enum in summary.get("enums", []):
            lines.append(f"enum {enum} {{ ... }}")

        for struct in summary.get("structs", []):
            lines.append(f"struct {struct} {{ ... }}")

        for func in summary.get("functions", []):
            qual = func.get("qualifiers", "")
            ret = func.get("return_type", "")
            prefix = f"{qual} {ret}".strip()
            lines.append(f"{prefix} {func['name']}({func['params']})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal tree walking
    # ------------------------------------------------------------------

    def _walk_children(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        """Walk immediate children, recursing into preprocessor blocks."""
        for child in node.children:
            self._visit_top_level(content, child, summary)

    def _visit_top_level(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        ntype = node.type

        # Recurse into preprocessor conditional blocks
        if ntype in (
            "preproc_ifdef",
            "preproc_ifndef",
            "preproc_if",
            "preproc_else",
            "preproc_elif",
        ):
            self._walk_children(content, node, summary)
            return

        if ntype == "preproc_include":
            self._extract_include(content, node, summary)

        elif ntype == "preproc_def":
            name = _child_text(content, node.child_by_field_name("name"))
            if name:
                summary["macros"].append(name)

        elif ntype == "preproc_function_def":
            name = _child_text(content, node.child_by_field_name("name"))
            if name:
                params = _child_text(
                    content, node.child_by_field_name("parameters")
                )
                summary["macros"].append(
                    f"{name}({params})" if params else name
                )

        elif ntype == "function_definition":
            self._extract_function(content, node, summary)

        elif ntype == "declaration":
            self._extract_declaration(content, node, summary)

        elif ntype == "type_definition":
            self._extract_typedef(content, node, summary)

        elif ntype == "struct_specifier":
            name = _first_child_of_type(content, node, "type_identifier")
            if name:
                summary["structs"].append(name)

        elif ntype == "enum_specifier":
            name = _first_child_of_type(content, node, "type_identifier")
            if name:
                summary["enums"].append(name)

    def _extract_include(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        for child in node.children:
            if child.type == "string_literal":
                path = _child_text(content, child)
                if path:
                    summary["includes"].append(path.strip('"'))
            elif child.type == "system_lib_string":
                path = _child_text(content, child)
                if path:
                    summary["includes"].append(path)

    def _extract_function(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        qualifiers: List[str] = []
        return_parts: List[str] = []

        declarator = None
        for child in node.children:
            if child.type == "function_declarator":
                declarator = child
            elif child.type == "storage_class_specifier":
                qualifiers.append(_child_text(content, child) or "")
            elif child.type == "type_qualifier":
                qualifiers.append(_child_text(content, child) or "")
            elif child.type == "compound_statement":
                pass  # body — skip
            elif child.type in (
                "primitive_type",
                "sized_type_specifier",
                "type_identifier",
                "struct_specifier",
                "enum_specifier",
            ):
                return_parts.append(_child_text(content, child) or "")
            elif child.type == "pointer_declarator":
                # e.g. static void *func(...)
                declarator = _find_child_type(child, "function_declarator")
                return_parts.append("*")

        if declarator is None:
            return

        name = _first_child_of_type(content, declarator, "identifier")
        params_node = _first_child_node_of_type(declarator, "parameter_list")
        params = _child_text(content, params_node) or "()"
        params = params.strip("()")

        summary["functions"].append(
            CFunctionSummary(
                name=name or "<anonymous>",
                params=params,
                return_type=" ".join(return_parts).strip(),
                qualifiers=" ".join(qualifiers).strip(),
            )
        )

    def _extract_declaration(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        """Handle top-level ``declaration`` nodes (forward-declared
        functions, extern declarations, etc.)."""
        text = _child_text(content, node) or ""
        # Forward-declared functions have a function_declarator child
        func_decl = _find_child_type(node, "function_declarator")
        if func_decl is not None:
            # This is a function prototype / forward declaration
            qualifiers: List[str] = []
            return_parts: List[str] = []
            for child in node.children:
                if child.type == "storage_class_specifier":
                    qualifiers.append(_child_text(content, child) or "")
                elif child.type in (
                    "primitive_type",
                    "sized_type_specifier",
                    "type_identifier",
                    "struct_specifier",
                ):
                    return_parts.append(_child_text(content, child) or "")

            name = _first_child_of_type(content, func_decl, "identifier")
            params_node = _first_child_node_of_type(
                func_decl, "parameter_list"
            )
            params = _child_text(content, params_node) or "()"
            params = params.strip("()")

            summary["functions"].append(
                CFunctionSummary(
                    name=name or "<anonymous>",
                    params=params,
                    return_type=" ".join(return_parts).strip(),
                    qualifiers=" ".join(qualifiers).strip(),
                )
            )

    def _extract_typedef(
        self, content: str, node: Any, summary: CSummary
    ) -> None:
        """Handle ``type_definition`` nodes — typedef struct/enum/scalar."""
        # The last type_identifier child is the typedef name
        typedef_name: Optional[str] = None
        inner_struct: Optional[str] = None
        inner_enum: Optional[str] = None

        for child in node.children:
            if child.type == "type_identifier":
                typedef_name = _child_text(content, child)
            elif child.type == "struct_specifier":
                tag = _first_child_of_type(content, child, "type_identifier")
                if tag:
                    inner_struct = tag
            elif child.type == "enum_specifier":
                tag = _first_child_of_type(content, child, "type_identifier")
                if tag:
                    inner_enum = tag

        if inner_struct:
            summary["structs"].append(inner_struct)
        elif inner_enum:
            summary["enums"].append(inner_enum)

        if typedef_name:
            summary["typedefs"].append(typedef_name)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _child_text(content: str, node: Any) -> Optional[str]:
    """Return the text of *node* using ``node.text`` (correct inside
    preprocessor blocks where byte offsets can be shifted)."""
    if node is None:
        return None
    # node.text returns bytes and is accurate even inside #ifdef/#else
    if hasattr(node, "text") and node.text is not None:
        return node.text.decode("utf-8", errors="replace")
    return content[node.start_byte : node.end_byte]


def _find_child_type(node: Any, target_type: str) -> Any:
    """Recursively find the first descendant of *target_type*."""
    for child in node.children:
        if child.type == target_type:
            return child
        found = _find_child_type(child, target_type)
        if found is not None:
            return found
    return None


def _first_child_node_of_type(node: Any, target_type: str) -> Any:
    """Return the first direct child with the given type, or None."""
    for child in node.children:
        if child.type == target_type:
            return child
    return None


def _first_child_of_type(
    content: str, node: Any, target_type: str
) -> Optional[str]:
    """Return the text of the first direct child with the given type."""
    child = _first_child_node_of_type(node, target_type)
    return _child_text(content, child)
