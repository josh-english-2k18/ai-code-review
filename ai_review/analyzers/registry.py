from __future__ import annotations

from typing import Dict, Iterable, Optional

from ai_review.analyzers.types import AnalyzerProtocol
from ai_review.analyzers.js_heuristic import JSHeuristicAnalyzer
from ai_review.analyzers.js_treesitter import TreeSitterJSAnalyzer
from ai_review.analyzers.c_treesitter import CTreeSitterAnalyzer
from ai_review.analyzers.python_ast import PythonAnalyzer
from ai_review.analyzers.errors import AnalyzerError


class AnalyzerRegistry:
    """Registry for language-specific analyzers."""

    def __init__(self):
        self._by_ext: Dict[str, AnalyzerProtocol] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register([".py"], PythonAnalyzer())

        # Prefer tree-sitter if available; fallback to regex heuristics.
        try:
            self.register([".js", ".jsx"], TreeSitterJSAnalyzer("javascript"))
            self.register([".ts", ".tsx"], TreeSitterJSAnalyzer("typescript"))
        except AnalyzerError:
            self.register([".js", ".jsx", ".ts", ".tsx"], JSHeuristicAnalyzer())

        # C/C++ headers via tree-sitter
        try:
            self.register([".c", ".h"], CTreeSitterAnalyzer())
        except AnalyzerError:
            pass  # tree-sitter-c not installed; C files treated as opaque

    def register(self, extensions: Iterable[str], analyzer: AnalyzerProtocol):
        for ext in extensions:
            self._by_ext[ext] = analyzer

    def get(self, file_path: str) -> Optional[AnalyzerProtocol]:
        for ext, analyzer in self._by_ext.items():
            if file_path.endswith(ext):
                return analyzer
        return None
