import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class CacheStore:
    """Persist repository analysis results."""

    def __init__(self, repo_path: str, enabled: bool = True, cache_dir: str | None = None):
        self.enabled = enabled
        self.cache_dir = Path(cache_dir) if cache_dir else Path(repo_path) / ".ai_review" / "cache"
        self.cache_file = self.cache_dir / "analysis.json"

    def load(self) -> dict:
        if not self.enabled:
            return {}
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict):
        if not self.enabled:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as stream:
                temp_path = Path(stream.name)
                json.dump(data, stream, indent=2)
            os.replace(temp_path, self.cache_file)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def get_entry(self, file_path: str) -> dict | None:
        return self.load().get(file_path)

    def update_entry(self, file_path: str, data: dict):
        if self.enabled:
            cache = self.load()
            cache[file_path] = data
            self.save(cache)
