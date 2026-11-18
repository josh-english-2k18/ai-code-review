from collections.abc import Collection
from hashlib import sha256
from io import BytesIO
from tokenize import detect_encoding

from ai_review.analyzers.errors import AnalyzerError
from ai_review.analyzers.registry import AnalyzerRegistry
from ai_review.cache.store import CacheStore
from ai_review.markdown import inline_code
from ai_review.repo_scan import RepoScanner
from ai_review.security.redact import Redactor


def decode_source(path: str, source: bytes) -> str:
    encoding = detect_encoding(BytesIO(source).readline)[0] if path.endswith(".py") else "utf-8-sig"
    return source.decode(encoding)


class RepoAnalyzer:
    """Build structural summaries from the source actually being analyzed."""

    def __init__(
        self,
        repo_path: str,
        cache_enabled: bool = True,
        cache_dir: str | None = None,
        registry: AnalyzerRegistry | None = None,
    ):
        self.scanner = RepoScanner(repo_path)
        self.cache = CacheStore(self.scanner.git.repo_path, enabled=cache_enabled, cache_dir=cache_dir)
        self.registry = registry if registry is not None else AnalyzerRegistry()

    def analyze(
        self, full: bool = False, extra_paths: tuple[str, ...] = (), *,
        exclude_paths: Collection[str] = (),
    ) -> dict:
        all_files = sorted(set(self.scanner.scan()).union(extra_paths).difference(exclude_paths))
        cache_data = {} if full else self.cache.load()
        new_cache = {}
        for path in all_files:
            file = self.scanner.git.worktree_file(path)
            if file is None:
                continue
            analyzer = self.registry.get(path)
            if analyzer is None:
                new_cache[path] = {"type": "generic"}
                continue

            try:
                source = file.read_bytes()
            except OSError:
                continue
            fingerprint = f"4:{type(analyzer).__name__}:{sha256(source).hexdigest()}"
            cached = cache_data.get(path)
            if isinstance(cached, dict) and cached.get("hash") == fingerprint:
                new_cache[path] = cached
                continue

            try:
                summary = analyzer.analyze_content(decode_source(path, source))
            except (AnalyzerError, UnicodeError, SyntaxError, LookupError) as exc:
                new_cache[path] = {"hash": fingerprint, "error": str(exc)}
            else:
                new_cache[path] = {"hash": fingerprint, "summary": summary, "type": "structural"}

        # Explicit untracked paths belong to this review only.
        extras = set(extra_paths)
        persistent = {path: entry for path, entry in new_cache.items() if path not in extras}
        if full or persistent != cache_data:
            self.cache.save(persistent)
        return new_cache

    def generate_guide(self, analysis_data: dict) -> str:
        lines = ["# Repository Structural Guide", ""]
        redactor = Redactor()
        for path, data in sorted(analysis_data.items()):
            analyzer = self.registry.get(path)
            if analyzer and "summary" in data:
                summary, _ = redactor.redact(analyzer.format_summary(data["summary"]))
                if summary:
                    lines.extend([f"## File: {inline_code(path)}", ""])
                    lines.extend(f"    {line}" for line in summary.split("\n"))
                    lines.append("")
        return "\n".join(lines)
