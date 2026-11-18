import os
import subprocess
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from ai_review.config import ReviewConfig


DIFF_OPTIONS = (
    "--no-color", "--no-ext-diff", "--no-textconv", "--find-renames",
    "--ignore-submodules=none", "--submodule=short",
)
PATCH_FORMAT = (
    "--src-prefix=a/", "--dst-prefix=b/",
    "--output-indicator-new=+", "--output-indicator-old=-", "--output-indicator-context= ",
)


@dataclass(frozen=True)
class ReviewTarget:
    baseline: str
    head: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    unborn: bool = False

    @property
    def working(self) -> bool:
        return self.head is None

    @property
    def diff_args(self) -> tuple[str, ...]:
        return (self.baseline,) if self.head is None else (self.baseline, self.head)


class GitOps:
    """Read review scope and content from Git."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = str(Path(repo_path).resolve())

    @classmethod
    def at_worktree_root(cls, path: str) -> "GitOps":
        git = cls(path)
        return cls(git._run(["rev-parse", "--show-toplevel"]).removesuffix("\n"))

    def _run(self, cmd: list[str], *, stdin: bytes | None = None) -> str:
        try:
            result = subprocess.run(
                ["git", *cmd], cwd=self.repo_path, capture_output=True, input=stdin, check=True,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            )
        except subprocess.CalledProcessError as exc:
            stderr = os.fsdecode(exc.stderr).strip()
            raise RuntimeError(f"Git command failed: {stderr or ' '.join(cmd)}") from exc
        return os.fsdecode(result.stdout)

    def resolve_commit(self, ref: str) -> str:
        return self._run(["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"]).strip()

    def has_head(self) -> bool:
        try:
            self.resolve_commit("HEAD")
        except RuntimeError:
            return False
        return True

    def review_target(self, base: str | None = None, head: str | None = None) -> ReviewTarget:
        if base is not None:
            head_ref = head if head is not None else "HEAD"
            base_commit = self.resolve_commit(base)
            head_commit = self.resolve_commit(head_ref)
            baseline = self.get_merge_base(base_commit, head_commit)
            return ReviewTarget(baseline, head_commit, base, head_ref)
        if head is not None:
            raise ValueError("--head requires --base.")
        try:
            baseline = self.resolve_commit("HEAD")
        except RuntimeError as exc:
            # Git recognizes the empty tree even before the first commit.
            self._run(["symbolic-ref", "--quiet", "HEAD"])
            status = self._run(["status", "--porcelain=v2", "--branch", "--untracked-files=no"])
            if not status.startswith("# branch.oid (initial)\n"):
                raise exc
            baseline = self._run(["hash-object", "-t", "tree", "--stdin"], stdin=b"").strip()
            return ReviewTarget(baseline, unborn=True)
        return ReviewTarget(baseline)

    def get_merge_base(self, base: str, head: str) -> str:
        return self._run(["merge-base", "--", base, head]).strip()

    def diff(self, target: ReviewTarget, *options: str) -> str:
        return self._run([
            "-c", "core.quotePath=true", "-c", "diff.suppressBlankEmpty=false",
            "diff", *DIFF_OPTIONS, *PATCH_FORMAT, *options, *target.diff_args, "--",
        ])

    def tracked_files(self) -> list[str]:
        return list(dict.fromkeys(self._run(["ls-files", "-z"]).split("\0")[:-1]))

    def get_untracked_files(self) -> list[str]:
        return self._run(["ls-files", "-z", "--others", "--exclude-standard"]).split("\0")[:-1]

    def read_blob(self, revision: str, path: str) -> str:
        return self._run(["cat-file", "blob", f"{revision}:{path}"])

    def has_regular_blob(self, revision: str, path: str) -> bool:
        record = self._run(["--literal-pathspecs", "ls-tree", "-z", revision, "--", path])
        metadata, _, name = record.removesuffix("\0").partition("\t")
        return name == path and metadata.startswith(("100644 blob ", "100755 blob "))

    def worktree_file(self, path: str) -> Path | None:
        root = Path(self.repo_path)
        candidate = root / path
        try:
            if candidate.is_relative_to(root) and candidate.resolve() == candidate and candidate.is_file():
                return candidate
        except (OSError, RuntimeError):
            pass
        return None

    def change_entries(self, target: ReviewTarget) -> list[dict]:
        return self._parse_name_status_z(self.diff(target, "--name-status", "-z"))

    def review_entries(
        self, target: ReviewTarget, include_untracked: bool, *,
        tracked: list[dict] | None = None, omit_untracked: Collection[str] = (),
    ) -> list[dict]:
        entries = self.change_entries(target) if tracked is None else tracked
        if target.working and include_untracked:
            untracked = [
                {"status": "??", "path": path} for path in self.get_untracked_files()
                if path not in omit_untracked
            ]
            entries = entries + untracked
        return [
            entry for entry in entries
            if not ReviewConfig.should_exclude(entry["path"])
            and not ReviewConfig.should_exclude(entry.get("old_path", ""))
        ]

    def numstat_entries(self, target: ReviewTarget) -> list[dict]:
        fields = iter(self.diff(target, "--numstat", "-z").split("\0")[:-1])
        return [self._parse_numstat(field, fields) for field in fields]

    def diff_with_metadata(self, target: ReviewTarget) -> tuple[list[dict], list[dict], str]:
        output = self.diff(target, "--raw", "--numstat", "-z", "--patch")
        if not output:
            return [], [], ""
        # Git separates the NUL-delimited raw and numstat records from the patch with a blank field.
        metadata, separator, patch = output.partition("\0\0")
        if not separator:
            raise RuntimeError("Git did not separate the change metadata from the patch.")
        entries, stats = [], []
        fields = iter(metadata.split("\0"))
        for field in fields:
            if field.startswith(":"):
                entries.append(self._parse_change(field.rsplit(" ", 1)[-1], fields))
            else:
                stats.append(self._parse_numstat(field, fields))
        return entries, stats, patch

    def _parse_name_status_z(self, output: str) -> list[dict]:
        fields = iter(output.split("\0")[:-1])
        return [self._parse_change(status, fields) for status in fields]

    def _parse_change(self, status: str, fields: Iterator[str]) -> dict:
        path = next(fields)
        if status.startswith(("R", "C")):
            return {"status": status[0], "old_path": path, "path": next(fields)}
        return {"status": status[0], "path": path}

    def _parse_numstat(self, field: str, fields: Iterator[str]) -> dict:
        additions, deletions, path = field.split("\t", 2)
        old_path = None
        if not path:
            old_path, path = next(fields), next(fields)
        return {"additions": additions, "deletions": deletions, "path": path, "old_path": old_path}

    def get_diff(self, base=None, head=None, working=False) -> str:
        if working or base is not None or head is not None:
            return self.diff(self.review_target(base, head))
        return ""

    def get_name_status_entries(self, base=None, head=None, working=False) -> list[dict]:
        if working or base is not None or head is not None:
            return self.change_entries(self.review_target(base, head))
        return []

    def get_numstat_entries(self, base=None, head=None, working=False) -> list[dict]:
        if working or base is not None or head is not None:
            return self.numstat_entries(self.review_target(base, head))
        return []

    def list_changed_files(self, base=None, head=None, working=False) -> list[str]:
        entries = self.get_name_status_entries(base, head, working)
        paths = [entry["path"] for entry in entries]
        if working and base is None and head is None:
            paths.extend(self.get_untracked_files())
        return list(dict.fromkeys(paths))

    def list_changed_files_with_status(self, base=None, head=None, working=False) -> list[str]:
        if working or base is not None or head is not None:
            return self.diff(self.review_target(base, head), "--name-status").splitlines()
        return []

    def get_numstat(self, base=None, head=None, working=False) -> list[str]:
        if working or base is not None or head is not None:
            return self.diff(self.review_target(base, head), "--numstat").splitlines()
        return []
