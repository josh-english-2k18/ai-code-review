import ast
from typing import Dict, Any

from ai_review.config import ReviewConfig
from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.types import PythonSummary, PythonFunctionSummary, PythonClassSummary


class PythonAnalyzer:
    """Analyzes Python files using AST to extract structural information."""

    def analyze_content(self, content: str) -> PythonSummary:
        """Extract classes, functions, and docstrings from Python source."""
        try:
            tree = ast.parse(content)
        except (SyntaxError, ValueError) as exc:
            raise AnalyzerError("Failed to parse AST") from exc

        summary: PythonSummary = {
            "classes": [],
            "functions": [],
            "docstring": ast.get_docstring(tree),
            "imports": [],
            "from_imports": [],
        }

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                summary["classes"].append(self._analyze_class(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                summary["functions"].append(self._analyze_function(node))
            elif isinstance(node, ast.Import):
                for name in node.names:
                    summary["imports"].append(name.name)
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                prefix = module + "." if node.module else module
                for name in node.names:
                    imported = f"{prefix}{name.name}"
                    summary["imports"].append(imported)
                    summary["from_imports"].append(imported)

        return summary

    def _analyze_class(self, node: ast.ClassDef) -> PythonClassSummary:
        return PythonClassSummary(
            name=node.name,
            docstring=ast.get_docstring(node),
            methods=[
                self._analyze_function(n)
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ],
        )

    def _analyze_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> PythonFunctionSummary:
        positional_only = len(node.args.posonlyargs)
        positional = [*node.args.posonlyargs, *node.args.args]
        first_default = len(positional) - len(node.args.defaults)
        args = [
            f"{arg.arg}=..." if index >= first_default else arg.arg
            for index, arg in enumerate(positional)
        ]
        if positional_only:
            args.insert(positional_only, "/")
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        elif node.args.kwonlyargs:
            args.append("*")
        args.extend(
            f"{arg.arg}=..." if default is not None else arg.arg
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
        )
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        return PythonFunctionSummary(
            name=node.name,
            args=args,
            docstring=ast.get_docstring(node),
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )

    def format_summary(self, summary: Dict[str, Any]) -> str:
        """Format the AST summary into a compressed markdown-like string."""
        lines = []
        imports = summary.get("imports", [])
        if imports:
            display_imports = imports[: ReviewConfig.MAX_IMPORTS_IN_SUMMARY]
            lines.append(f"imports: {', '.join(display_imports)}")
            if len(imports) > len(display_imports):
                lines.append(f"imports: ... (+{len(imports) - len(display_imports)} more)")

        if summary.get("docstring"):
            lines.append(f"\"\"\"{summary['docstring']}\"\"\"")

        for cls in summary["classes"]:
            lines.append(f"class {cls['name']}:")
            if cls["docstring"]:
                lines.append(f"    \"\"\"{cls['docstring']}\"\"\"")
            for method in cls["methods"]:
                lines.append(f"    {self._format_function(method)}")

        for func in summary["functions"]:
            lines.append(self._format_function(func))

        return "\n".join(lines)

    def _format_function(self, function: PythonFunctionSummary) -> str:
        prefix = "async def" if function.get("is_async") else "def"
        return f"{prefix} {function['name']}({', '.join(function['args'])}): ..."
