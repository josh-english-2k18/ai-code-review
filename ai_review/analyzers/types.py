from __future__ import annotations

from typing import List, Optional, Protocol, TypedDict


class PythonFunctionSummary(TypedDict):
    name: str
    args: List[str]
    docstring: Optional[str]
    is_async: bool


class PythonClassSummary(TypedDict):
    name: str
    docstring: Optional[str]
    methods: List[PythonFunctionSummary]


class PythonSummary(TypedDict):
    classes: List[PythonClassSummary]
    functions: List[PythonFunctionSummary]
    docstring: Optional[str]
    imports: List[str]
    from_imports: List[str]


class JSFunctionSummary(TypedDict):
    name: str
    args: str


class JSSummary(TypedDict):
    classes: List[str]
    functions: List[JSFunctionSummary]
    interfaces: List[str]
    types: List[str]
    enums: List[str]
    imports: List[str]
    exports: List[str]


class AnalyzerProtocol(Protocol):
    def analyze_content(self, content: str) -> dict:
        ...

    def format_summary(self, summary: dict) -> str:
        ...
