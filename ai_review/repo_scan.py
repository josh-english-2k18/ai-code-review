import os

from ai_review.config import ReviewConfig
from ai_review.git_ops import GitOps


class RepoScanner:
    """Discover tracked files, or walk the filesystem outside a Git repository."""

    def __init__(self, repo_path: str):
        self.git = GitOps(repo_path)

    def scan(self) -> list[str]:
        try:
            self.git._run(["rev-parse", "--is-inside-work-tree"])
        except RuntimeError:
            paths = self._walk()
        else:
            paths = self.git.tracked_files()
        return sorted(path for path in paths if not ReviewConfig.should_exclude(path))

    def _walk(self) -> list[str]:
        paths = []
        for root, dirs, files in os.walk(self.git.repo_path):
            dirs[:] = [name for name in dirs if not name.startswith(".")
                       and name not in ReviewConfig.EXCLUDED_DIR_NAMES]
            paths.extend(os.path.relpath(os.path.join(root, name), self.git.repo_path) for name in files)
        return paths
