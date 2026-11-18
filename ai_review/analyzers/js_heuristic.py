import re
from typing import Dict, Any

from ai_review.config import ReviewConfig
from ai_review.analyzers.types import JSSummary, JSFunctionSummary

class JSHeuristicAnalyzer:
    """Uses regex-based heuristics to extract structure from JS/TS files."""

    # Patterns for common JS/TS constructs
    CLASS_PATTERN = re.compile(r'class\s+([A-Za-z0-9_$]+)')
    FUNCTION_PATTERN = re.compile(
        r'(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)'
    )
    ARROW_FUNC_PATTERN = re.compile(
        r'(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*'
        r'(?:async\s+)?(?:\(([^)]*)\)|([A-Za-z_$][A-Za-z0-9_$]*))\s*=>'
    )
    INTERFACE_PATTERN = re.compile(r'interface\s+([A-Za-z0-9_$]+)')
    TYPE_PATTERN = re.compile(r'\btype\s+([A-Za-z0-9_$]+)\s*=')
    ENUM_PATTERN = re.compile(r'\benum\s+([A-Za-z0-9_$]+)\b')
    IMPORT_PATTERN = re.compile(r'(?:import|from)\s+[\'"](.+?)[\'"]')
    EXPORT_SYMBOL_PATTERN = re.compile(
        r'export\s+(?:default\s+)?(?:async\s+)?'
        r'(?:class|function|const|let|var|interface|type|enum)\s+([A-Za-z0-9_$]+)'
    )
    EXPORT_NAMED_PATTERN = re.compile(r'export\s*{\s*([^}]+)\s*}')

    def analyze_content(self, content: str) -> JSSummary:
        """Extract classes, functions, and interfaces using regex."""
        summary: JSSummary = {
            "classes": self.CLASS_PATTERN.findall(content),
            "functions": [],
            "interfaces": self.INTERFACE_PATTERN.findall(content),
            "types": self.TYPE_PATTERN.findall(content),
            "enums": self.ENUM_PATTERN.findall(content),
            "imports": self.IMPORT_PATTERN.findall(content),
            "exports": [],
        }

        # Combine standard and arrow functions
        for name, args in self.FUNCTION_PATTERN.findall(content):
            summary["functions"].append(JSFunctionSummary(name=name, args=args.strip()))
        
        for name, args, single in self.ARROW_FUNC_PATTERN.findall(content):
            summary["functions"].append(JSFunctionSummary(name=name, args=single or args.strip()))

        summary["exports"] = self._scan_exports(content)
        return summary

    def _scan_exports(self, content: str) -> list[str]:
        exports = set(self.EXPORT_SYMBOL_PATTERN.findall(content))
        for group in self.EXPORT_NAMED_PATTERN.findall(content):
            for raw in group.split(","):
                name = re.split(r"\s+as\s+", raw.strip())[-1]
                if name:
                    exports.add(name)
        return sorted(exports)

    def format_summary(self, summary: Dict[str, Any]) -> str:
        """Format the JS/TS summary into a compressed markdown-like string."""
        lines = []
        
        imports = summary.get("imports", [])
        if imports:
            display_imports = imports[: ReviewConfig.MAX_IMPORTS_IN_SUMMARY]
            lines.append(f"imports: {', '.join(display_imports)}")
            if len(imports) > len(display_imports):
                lines.append(f"imports: ... (+{len(imports) - len(display_imports)} more)")

        for interface in summary.get("interfaces", []):
            lines.append(f"interface {interface} {{ ... }}")

        for alias in summary.get("types", []):
            lines.append(f"type {alias} = ...")

        for enum_name in summary.get("enums", []):
            lines.append(f"enum {enum_name} {{ ... }}")
        
        for cls in summary.get("classes", []):
            lines.append(f"class {cls} {{ ... }}")
        
        for func in summary.get("functions", []):
            lines.append(f"function {func['name']}({func['args']}): ...")

        exports = summary.get("exports", [])
        if exports:
            lines.append(f"exports: {', '.join(exports)}")
            
        return "\n".join(lines)
