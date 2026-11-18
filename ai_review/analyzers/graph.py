from collections import deque
from typing import Dict, List, Set, Any
import os

from ai_review.config import ReviewConfig

class GraphService:
    """Manages the directed graph of module dependencies."""

    def __init__(self):
        self.adj_list: Dict[str, List[str]] = {}
        self.reverse_adj_list: Dict[str, List[str]] = {}

    def build_from_analysis(self, analysis_data: Dict[str, Any]):
        """Build the graph from repository analysis data."""
        self.adj_list = {}
        self.reverse_adj_list = {}
        
        all_files = set(analysis_data)
        for file_path, data in analysis_data.items():
            summary = data.get("summary", {})
            imports = summary.get("imports", [])
            from_imports = set(summary.get("from_imports", []))
            resolved_imports = self._resolve_imports(file_path, imports, from_imports, all_files)
            self.adj_list[file_path] = resolved_imports
            
            for imp in resolved_imports:
                if imp not in self.reverse_adj_list:
                    self.reverse_adj_list[imp] = []
                self.reverse_adj_list[imp].append(file_path)

    def get_impacted_files(self, changed_files: List[str], depth: int = 1) -> Dict[str, List[str]]:
        """Identify downstream files impacted by changes in specified files."""
        impact = {}
        for f in changed_files:
            impacted = self._bfs_reachable(f, depth)
            if impacted:
                impact[f] = impacted
        return impact

    def _resolve_imports(
        self, current_file: str, imports: List[str], from_imports: Set[str], all_files: Set[str],
    ) -> List[str]:
        """Maps import symbols/strings back to repository file paths."""
        resolved = set()
        is_python = current_file.endswith(".py")
        for imp in imports:
            if not imp:
                continue

            if is_python:
                resolved.update(self._resolve_python_import(current_file, imp, all_files, imp in from_imports))
                continue

            candidates = []
            # Handle alias-based imports
            alias_match = False
            for alias, replacement in ReviewConfig.IMPORT_ALIASES.items():
                if imp.startswith(alias):
                    alias_match = True
                    tail = imp[len(alias):]
                    if alias == "@nilo/":
                        parts = tail.split("/", 1)
                        package = parts[0]
                        subpath = parts[1] if len(parts) > 1 else "index"
                        base = os.path.normpath(os.path.join(replacement, package, "src", subpath))
                    else:
                        base = os.path.normpath(os.path.join(replacement, tail))
                    candidates.extend(self._candidate_paths(base))
            if alias_match:
                for path in candidates:
                    if path in all_files:
                        resolved.add(path)
                continue

            if imp.startswith("."):
                base_dir = os.path.dirname(current_file)
                base = os.path.normpath(os.path.join(base_dir, imp))
                candidates.extend(self._candidate_paths(base))
            else:
                candidates.extend(self._candidate_paths(imp))
            for path in candidates:
                if path in all_files:
                    resolved.add(path)

        return sorted(resolved)

    def _resolve_python_import(
        self, current_file: str, imp: str, all_files: Set[str], from_import: bool,
    ) -> Set[str]:
        module = imp.lstrip(".")
        level = len(imp) - len(module)
        parent = os.path.dirname(current_file) if level else ""
        for _ in range(1, level):
            if not parent:
                return set()
            parent = os.path.dirname(parent)
        base = os.path.join(parent, module.replace(".", "/"))
        candidates = {base + ".py", os.path.join(base, "__init__.py")}
        matches = candidates & all_files
        if matches or not from_import:
            return matches

        parent = os.path.dirname(base)
        candidates = {os.path.join(parent, "__init__.py")}
        if parent:
            candidates.add(parent + ".py")
        return candidates & all_files

    def _candidate_paths(self, base: str) -> List[str]:
        extensions = [".ts", ".tsx", ".js", ".jsx", ".py"]
        candidates = [base]
        for ext in extensions:
            candidates.append(f"{base}{ext}")
        for ext in extensions:
            candidates.append(os.path.join(base, f"index{ext}"))
        for ext in [".py"]:
            candidates.append(os.path.join(base, f"__init__{ext}"))
        return candidates

    def _bfs_reachable(self, start_node: str, max_depth: int) -> List[str]:
        """Find nodes reachable in reverse graph (downstream consumers) up to max_depth."""
        if start_node not in self.reverse_adj_list:
            return []
            
        visited = {start_node}
        queue = deque([(start_node, 0)])
        reachable = []
        
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
                
            for neighbor in self.reverse_adj_list.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    reachable.append(neighbor)
                    queue.append((neighbor, depth + 1))
        
        return reachable
