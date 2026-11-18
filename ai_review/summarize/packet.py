import datetime
import os
import re

from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.graph import GraphService
from ai_review.analyzers.registry import AnalyzerRegistry
from ai_review.config import ReviewConfig
from ai_review.git_ops import GitOps, ReviewTarget
from ai_review.markdown import inline_code
from ai_review.security.redact import Redactor
from ai_review.summarize.changes import ChangeCollector
from ai_review.summarize.repo_guide import RepoAnalyzer, decode_source


class PacketBuilder:
    """Build supplemental review material from the scoped sources."""

    def __init__(self, repo_path: str | GitOps, cache_enabled: bool = True, cache_dir: str | None = None):
        self.git = repo_path if isinstance(repo_path, GitOps) else GitOps.at_worktree_root(repo_path)
        self.registry = AnalyzerRegistry()
        self.redactor = Redactor()
        self.cache_enabled = cache_enabled
        self.cache_dir = cache_dir

    def build_packet(
        self,
        mode: str = "working",
        base: str | None = None,
        head: str | None = None,
        max_diff_lines: int | None = None,
        include_untracked: bool = True,
        annotate_line_numbers: bool = True,
    ) -> str:
        target = self.git.review_target(base, head)
        collector = ChangeCollector.from_git(
            self.git, target, include_untracked, max_diff_lines, annotate_line_numbers,
        )
        return self.build(target, collector)

    def build(self, target: ReviewTarget, collector: ChangeCollector) -> str:
        entries = collector.entries
        changes = collector.get_markdown_summary()
        summary = collector.get_summary()
        changed = list(dict.fromkeys(entry["path"] for entry in entries))
        untracked = tuple(entry["path"] for entry in entries if entry["status"] == "??")

        risk = [f"- Sensitive code area {inline_code(path)}." for path in changed if ReviewConfig.is_risk_path(path)]
        additions = "\n".join(
            line[1:] for diff_file in collector.parse_diff() for hunk in diff_file.hunks
            for line in hunk.lines if line.startswith("+")
        )
        risk.extend(
            f"- {description}" for pattern, description in ReviewConfig.RISKY_DIFF_PATTERNS
            if re.search(pattern, additions, re.IGNORECASE)
        )

        impact = []
        context_paths = dict.fromkeys(entry["path"] for entry in entries if entry["status"] != "D")
        analysis = {}
        if target.working and changed:
            analysis = RepoAnalyzer(
                self.git.repo_path, self.cache_enabled, self.cache_dir, self.registry,
            ).analyze(extra_paths=untracked, exclude_paths=collector.excluded_paths)
            graph = GraphService()
            sources = list(dict.fromkeys([*changed, *(entry["old_path"] for entry in entries if "old_path" in entry)]))
            graph.build_from_analysis({**dict.fromkeys(sources, {}), **analysis})
            for path, targets in graph.get_impacted_files(sources, depth=2).items():
                visible = targets[:ReviewConfig.MAX_IMPACT_PER_FILE]
                context_paths.update(dict.fromkeys(visible))
                suffix = f" (+{len(targets) - len(visible)} more)" if len(targets) > len(visible) else ""
                impact.append(f"- {inline_code(path)} may affect " + ", ".join(map(inline_code, visible)) + suffix)
            for path in changed:
                context_paths.update(dict.fromkeys(graph.adj_list.get(path, [])))

        context = []
        for path in context_paths:
            analyzer = self.registry.get(path)
            if analyzer is None:
                continue
            structure = analysis.get(path, {}).get("summary") if target.working else self._branch_summary(target, path)
            if structure:
                formatted, count = self.redactor.redact(analyzer.format_summary(structure))
                collector.redaction_count += count
                if formatted:
                    context.append(f"### Structure of {inline_code(path)}\n\n" + "\n".join(
                        f"    {line}" for line in formatted.split("\n")
                    ))
            if len(context) >= ReviewConfig.MAX_CONTEXT_FILES:
                break

        generated = datetime.datetime.now(datetime.timezone.utc).isoformat()
        base = "empty tree" if target.unborn else target.baseline
        head = "working tree" if target.working else target.head
        impact_default = (
            "No downstream consumers were inferred."
            if target.working else "Inspect downstream consumers at the review head."
        )
        return "\n".join([
            "# Code Review Packet", "",
            "## Review Metadata", "",
            f"- Repository: {os.path.basename(self.git.repo_path)}",
            f"- Base: {base}",
            f"- Head: {head}",
            f"- Generated: {generated}",
            f"- Files changed: {summary['files_changed']} (+{summary['insertions']} / -{summary['deletions']})",
            f"- Untracked files: {len(untracked)}",
            f"- Redactions applied: {collector.redaction_count}",
            "",
            "## Risk Flags", "", *(risk or ["None identified."]), "",
            "## Test Signals", "",
            f"- Tests changed: {sum(ReviewConfig.is_test_path(path) for path in changed)}",
            f"- Docs changed: {sum(ReviewConfig.is_doc_path(path) for path in changed)}",
            "",
            "## Downstream Impact Analysis", "", *(impact or [impact_default]), "",
            changes, "",
            "## Architectural Context", "", "\n\n".join(context),
        ])

    def _branch_summary(self, target: ReviewTarget, path: str) -> dict | None:
        analyzer = self.registry.get(path)
        try:
            source = os.fsencode(self.git.read_blob(target.head, path))
            return analyzer.analyze_content(decode_source(path, source))
        except (RuntimeError, AnalyzerError, UnicodeError, SyntaxError, LookupError):
            return None
