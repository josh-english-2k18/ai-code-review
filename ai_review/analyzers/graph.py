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
        
        for file_path, data in analysis_data.items():
            summary = data.get("summary", {})
            # C files use "includes"; Python/JS use "imports"
            imports = summary.get("imports", []) or summary.get("includes", [])
            resolved_imports = self._resolve_imports(file_path, imports, analysis_data.keys())
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

    def _resolve_imports(self, current_file: str, imports: List[str], all_files: Set[str]) -> List[str]:
        """Maps import symbols/strings back to repository file paths."""
        resolved = set()
        file_set = set(all_files)
        is_c_file = current_file.endswith((".c", ".h"))

        for imp in imports:
            if not imp:
                continue

            # --- C/H include resolution ---
            if is_c_file:
                resolved.update(
                    self._resolve_c_include(current_file, imp, file_set)
                )
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
                    if path in file_set:
                        resolved.add(path)
                continue

            # Relative paths (JS/TS)
            if imp.startswith("."):
                base_dir = os.path.dirname(current_file)
                base = os.path.normpath(os.path.join(base_dir, imp))
                candidates.extend(self._candidate_paths(base))
            else:
                # Python-style module path
                imp_path = imp.replace(".", "/")
                candidates.extend(self._candidate_paths(imp_path))

            for path in candidates:
                if path in file_set:
                    resolved.add(path)

        return sorted(resolved)

    def _candidate_paths(self, base: str) -> List[str]:
        if os.path.splitext(base)[1]:
            return [base]
        extensions = [".ts", ".tsx", ".js", ".jsx", ".py"]
        candidates = []
        for ext in extensions:
            candidates.append(f"{base}{ext}")
        for ext in extensions:
            candidates.append(os.path.join(base, f"index{ext}"))
        for ext in [".py"]:
            candidates.append(os.path.join(base, f"__init__{ext}"))
        return candidates

    def _resolve_c_include(self, current_file: str, include: str, all_files: Set[str]) -> List[str]:
        """Resolve a C ``#include "header.h"`` to repo file paths.

        Search strategy (mirrors typical ``-I`` flag order):
        1. Same directory as the including file.
        2. Common project include dirs (``src/``, ``include/``, ``src/interface/``).
        3. Anywhere in the repo matching the basename.

        System includes (``<...>``) are ignored — they don't map to repo files.
        """
        if include.startswith("<"):
            return []

        basename = os.path.basename(include)
        include_dir = os.path.dirname(current_file)
        resolved: List[str] = []

        # 1. Relative to including file
        rel = os.path.normpath(os.path.join(include_dir, include))
        if rel in all_files:
            resolved.append(rel)

        # 2. Common project-level include directories
        common_dirs = ["src", "include", "src/interface", "src/common",
                       "nsc-sim/include", "qemu/patches/common"]
        for d in common_dirs:
            candidate = os.path.normpath(os.path.join(d, include))
            if candidate in all_files:
                resolved.append(candidate)

        # 3. Basename match anywhere (fallback for flat layouts)
        if not resolved:
            for f in all_files:
                if f.endswith("/" + basename) or f == basename:
                    resolved.append(f)

        return sorted(set(resolved))

    def _bfs_reachable(self, start_node: str, max_depth: int) -> List[str]:
        """Find nodes reachable in reverse graph (downstream consumers) up to max_depth."""
        if start_node not in self.reverse_adj_list:
            return []
            
        visited = {start_node}
        queue = [(start_node, 0)]
        reachable = []
        
        while queue:
            node, depth = queue.pop(0)
            if depth >= max_depth:
                continue
                
            for neighbor in self.reverse_adj_list.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    reachable.append(neighbor)
                    queue.append((neighbor, depth + 1))
        
        return reachable
