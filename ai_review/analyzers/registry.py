from __future__ import annotations

from typing import Dict, Iterable, Optional

from ai_review.analyzers.types import AnalyzerProtocol
from ai_review.analyzers.js_heuristic import JSHeuristicAnalyzer
from ai_review.analyzers.python_ast import PythonAnalyzer
from ai_review.analyzers.errors import AnalyzerError


class AnalyzerRegistry:
    """Registry for language-specific analyzers."""

    JS_GRAMMARS = {".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "tsx"}

    def __init__(self):
        self._by_ext: Dict[str, AnalyzerProtocol] = {}
        self._by_grammar: Dict[str, AnalyzerProtocol] = {}
        self.register([".py"], PythonAnalyzer())

    def register(self, extensions: Iterable[str], analyzer: AnalyzerProtocol):
        for ext in extensions:
            self._by_ext[ext] = analyzer

    def get(self, file_path: str) -> Optional[AnalyzerProtocol]:
        for ext, analyzer in self._by_ext.items():
            if file_path.endswith(ext):
                return analyzer
        _, dot, extension = file_path.rpartition(".")
        grammar = self.JS_GRAMMARS.get(dot + extension)
        if grammar is None:
            return None
        if grammar not in self._by_grammar:
            from ai_review.analyzers.js_treesitter import TreeSitterJSAnalyzer

            try:
                self._by_grammar[grammar] = TreeSitterJSAnalyzer(grammar)
            except AnalyzerError:
                self._by_grammar[grammar] = JSHeuristicAnalyzer()
        return self._by_grammar[grammar]
