import ast
import os
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from itertools import islice
from typing import Iterator, List, Dict, Any, Optional, Tuple

from ai_review.config import ReviewConfig
from ai_review.git_ops import GitOps, ReviewTarget
from ai_review.markdown import inline_code
from ai_review.security.redact import Redactor


def _decode_git_path(path: str) -> str:
    if path.startswith('"'):
        return os.fsdecode(ast.literal_eval("b" + path))
    return path


def _diff_blocks(text: str) -> Iterator[Tuple[str, str, List[str]]]:
    """Read file paths before hunks or redaction can alter the patch."""
    quoted_path = r'"(?:[^"\\]|\\.)*"'
    for block in re.split(r"(?m)^diff --git ", text)[1:]:
        header, *body = block.removesuffix("\n").split("\n")
        lines = ["diff --git " + header, *body]
        old_path = new_path = ""
        for line in body:
            if line.startswith("@@ "):
                break
            if line.startswith(("rename from ", "copy from ")):
                old_path = _decode_git_path(line.split(" ", 2)[2])
            if line.startswith(("rename to ", "copy to ")):
                new_path = _decode_git_path(line.split(" ", 2)[2])
        if not old_path or not new_path:
            # Git leaves spaces unquoted, including a possible literal " b/" in a path.
            # When paths differ, Git supplies rename/copy headers above.
            pair = re.fullmatch(rf'({quoted_path}|a/.+) ({quoted_path}|b/.+)', header)
            for boundary in re.finditer(r" b/", header):
                before, after = header[:boundary.start()], header[boundary.start() + 1:]
                if before[2:] == after[2:]:
                    old_path = new_path = before[2:]
                    break
            else:
                if pair:
                    old_path, new_path = (_decode_git_path(part)[2:] for part in pair.groups())
        yield old_path, new_path, lines


@dataclass
class DiffHunk:
    header: str
    old_start: Optional[int] = None
    new_start: Optional[int] = None
    lines: List[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

@dataclass
class DiffFile:
    path: str
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    status: str = "M"
    hunks: List[DiffHunk] = field(default_factory=list)
    additions: int | None = 0
    deletions: int = 0
    is_binary: bool = False
    rename_from: Optional[str] = None
    rename_to: Optional[str] = None

class ChangeCollector:
    """Collects and structures changes from git diffs."""

    def __init__(
        self,
        diff_text: str,
        file_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
        numstat: Optional[Dict[str, Dict[str, Any]]] = None,
        max_diff_lines: Optional[int] = None,
        annotate_line_numbers: bool = True,
    ):
        self.diff_text = diff_text
        self.file_statuses = file_statuses or {}
        self.numstat = numstat or {}
        self.max_diff_lines = max_diff_lines or ReviewConfig.MAX_DIFF_LINES
        self.annotate_line_numbers = annotate_line_numbers
        self.entries: list[dict] = []
        self.excluded_paths: set[str] = set()
        self._blocks: list[tuple[str, str, list[str]]] | None = None
        self._untracked_counts: dict[str, int | None] = {}
        self._files: List[DiffFile] | None = None
        self._annotated_diff: Optional[str] = None
        self.redaction_count: int = 0

    @classmethod
    def from_git(
        cls,
        git: GitOps,
        target: ReviewTarget,
        include_untracked: bool,
        max_diff_lines: int | None,
        annotate_line_numbers: bool,
        *,
        omit_untracked: Collection[str] = (),
    ) -> "ChangeCollector":
        tracked, stats, diff = git.diff_with_metadata(target)
        entries = git.review_entries(
            target, include_untracked, tracked=tracked, omit_untracked=omit_untracked,
        )
        statuses = {entry["path"]: entry for entry in entries if entry["status"] != "??"}
        numstat = {}
        for entry in stats:
            path = entry["path"]
            if path not in statuses:
                continue
            if ReviewConfig.should_exclude(entry["old_path"] or ""):
                continue
            additions, deletions = entry["additions"], entry["deletions"]
            binary = "-" in (additions, deletions)
            numstat[path] = {
                "additions": None if binary else int(additions),
                "deletions": None if binary else int(deletions),
                "is_binary": binary,
            }
        blocks = [
            (old_path, new_path, lines)
            for old_path, new_path, lines in _diff_blocks(diff)
            if old_path and new_path and new_path in statuses
            and not ReviewConfig.should_exclude(old_path)
            and not ReviewConfig.should_exclude(new_path)
        ]
        untracked_counts = {}
        for entry in entries:
            if entry["status"] == "??":
                path = entry["path"]
                lines, untracked_counts[path] = _untracked_diff(git, path)
                blocks.append((path, path, lines))
        patch = "\n".join("\n".join(lines) for _, _, lines in blocks)
        collector = cls(patch, statuses, numstat, max_diff_lines, annotate_line_numbers)
        collector.entries = entries
        collector.excluded_paths = {entry["path"] for entry in tracked}.difference(statuses)
        collector._blocks = blocks
        collector._untracked_counts = untracked_counts
        return collector

    def parse_diff(self) -> List[DiffFile]:
        """Parse unified diff into structured file/hunk objects."""
        if self._files is not None:
            return self._files

        self._files = []
        blocks = self._blocks if self._blocks is not None else _diff_blocks(self.diff_text)
        self._blocks = None
        type_changes = {}
        for old_path, new_path, lines in blocks:
            current = DiffFile(path=new_path or "unknown", old_path=old_path, new_path=new_path)
            current_hunk = None
            for line in lines[1:]:
                if line.startswith("@@ "):
                    old_start, new_start = self._parse_hunk_header(line)
                    current_hunk = DiffHunk(header=line, old_start=old_start, new_start=new_start)
                    current.hunks.append(current_hunk)
                elif current_hunk is not None:
                    current_hunk.lines.append(line)
                    if line.startswith("+"):
                        current_hunk.additions += 1
                        current.additions += 1
                    elif line.startswith("-"):
                        current_hunk.deletions += 1
                        current.deletions += 1
                elif line.startswith("new file mode"):
                    current.status = "A"
                elif line == "untracked file":
                    current.status = "??"
                elif line.startswith("deleted file mode"):
                    current.status = "D"
                elif line.startswith(("rename from ", "copy from ")):
                    current.status = "R" if line.startswith("rename") else "C"
                    current.rename_from, current.rename_to = old_path, new_path
                elif line.startswith(("Binary files ", "GIT binary patch")):
                    current.is_binary = True
            status = self.file_statuses.get(current.path, {}).get("status")
            if status == "T" and current.status != "??":
                # Git emits a deletion and addition as separate patches for one type change.
                existing = type_changes.setdefault(current.path, current)
                if existing is not current:
                    existing.hunks.extend(current.hunks)
                    existing.additions += current.additions
                    existing.deletions += current.deletions
                    existing.is_binary |= current.is_binary
                    continue
            if current.status == "??" and current.path in self._untracked_counts:
                current.additions = self._untracked_counts[current.path]
            self._files.append(current)

        self._apply_statuses()
        self._apply_numstat()
        self._add_missing_from_statuses()
        return self._files

    def _apply_statuses(self):
        if not self.file_statuses:
            return
        for diff_file in self._files:
            if diff_file.status == "??":
                continue
            status = self.file_statuses.get(diff_file.path)
            if not status:
                continue
            diff_file.status = status.get("status", diff_file.status)
            if status.get("old_path"):
                diff_file.rename_from = status["old_path"]
                diff_file.rename_to = diff_file.path

    def _apply_numstat(self):
        if not self.numstat:
            return
        for diff_file in self._files:
            if diff_file.status == "??":
                continue
            stats = self.numstat.get(diff_file.path)
            if not stats:
                continue
            diff_file.additions = stats.get("additions", diff_file.additions)
            diff_file.deletions = stats.get("deletions", diff_file.deletions)
            diff_file.is_binary = stats.get("is_binary", diff_file.is_binary)

    def _add_missing_from_statuses(self):
        present = {diff_file.path for diff_file in self._files if diff_file.status != "??"}
        for path, status in self.file_statuses.items():
            if path in present:
                continue
            diff_file = DiffFile(path=path, status=status.get("status", "M"))
            diff_file.rename_from = status.get("old_path")
            diff_file.rename_to = path if diff_file.rename_from else None
            stats = self.numstat.get(path)
            if stats:
                diff_file.additions = stats.get("additions", 0)
                diff_file.deletions = stats.get("deletions", 0)
                diff_file.is_binary = stats.get("is_binary", False)
            self._files.append(diff_file)

    def get_markdown_summary(self) -> str:
        """Generate a markdown summary of the changes including diff hunks."""
        files = self.parse_diff()
        summary = self.get_summary()
        if not summary["files_changed"]:
            return "No changes detected."

        redactor = Redactor()
        preview, omitted_lines = self._preview_lines()
        redacted, self.redaction_count = _redact_diff_lines(preview, redactor)
        if self.annotate_line_numbers:
            redacted = list(self._annotate_lines(redacted))
        if omitted_lines:
            redacted.append(f"... [diff truncated, {omitted_lines} lines omitted]")
        md = [
            "## Change Overview",
            f"- **Files changed**: {summary['files_changed']}",
            f"- **Insertions**: {summary['insertions']}",
            f"- **Deletions**: {summary['deletions']}",
        ]

        if self.annotate_line_numbers:
            md.append("- **Line numbers**: additions `(+Lx)`, deletions `(-Lx)`, context `(Lx)`")

        if summary["binary_files"]:
            md.append(f"- **Binary files**: {len(summary['binary_files'])}")
        if summary["unknown_insertions"]:
            md.append(f"- **Untracked files with unknown insertions**: {summary['unknown_insertions']}")
        if omitted_lines:
            md.append(f"- **Diff truncated**: {omitted_lines} lines omitted")

        md.extend([
            "",
            "## File Summary",
            "",
            "| Status | File | + | - |",
            "| --- | --- | --- | --- |",
        ])

        for f in summary["files"]:
            status = f["status"]
            path = f["path"]
            if f.get("rename_from"):
                path = f"{f['rename_from']} → {path}"
            additions = f["additions"] if f["additions"] is not None else "-"
            deletions = f["deletions"] if f["deletions"] is not None else "-"
            md.append(f"| {status} | {inline_code(path, table_cell=True)} | {additions} | {deletions} |")

        hunk_rows = list(islice(self._hunk_rows(files), ReviewConfig.MAX_HUNK_INDEX))
        if hunk_rows:
            md.extend([
                "",
                "## Hunk Index",
                "",
                "| File | Hunk Header |",
                "| --- | --- |",
            ])
            for path, header in hunk_rows:
                safe_header, count = redactor.redact(header, literal_assignments=redactor.is_text_path(path))
                self.redaction_count += count
                path_cell = inline_code(path, table_cell=True)
                header_cell = inline_code(safe_header, table_cell=True)
                md.append(f"| {path_cell} | {header_cell} |")
            omitted_hunks = sum(len(diff_file.hunks) for diff_file in files) - len(hunk_rows)
            if omitted_hunks:
                md.extend(["", f"_Hunk index truncated, {omitted_hunks} hunks omitted._"])

        md.extend([
            "",
            "## Changes",
            "",
        ])

        md.append("```diff")
        md.extend(redacted)
        md.append("```")

        return "\n".join(md)

    def _preview_lines(self) -> tuple[list[str], int]:
        if not self.diff_text:
            return [], 0
        diff = self.diff_text.removesuffix("\n")
        end = len(diff)
        if end > ReviewConfig.MAX_DIFF_PREVIEW_CHARS:
            end = max(diff.rfind("\n", 0, ReviewConfig.MAX_DIFF_PREVIEW_CHARS), 0)
        lines = diff[:end].split("\n", self.max_diff_lines) if end else []
        if len(lines) > self.max_diff_lines:
            lines.pop()
        return lines, diff.count("\n") + 1 - len(lines)

    def _hunk_rows(self, files: List[DiffFile]) -> Iterator[Tuple[str, str]]:
        for diff_file in files:
            for hunk in diff_file.hunks:
                yield diff_file.path, hunk.header

    def get_summary(self) -> Dict[str, Any]:
        files = self.parse_diff()
        total_additions = 0
        total_deletions = 0
        file_rows = []
        binary_files = []
        unknown_insertions = 0

        for diff_file in files:
            additions = diff_file.additions
            deletions = diff_file.deletions
            if diff_file.is_binary:
                additions = None
                deletions = None
                binary_files.append(diff_file.path)
            else:
                if additions is None:
                    unknown_insertions += 1
                else:
                    total_additions += additions
                total_deletions += diff_file.deletions

            file_rows.append({
                "path": diff_file.path,
                "status": diff_file.status,
                "additions": additions,
                "deletions": deletions,
                "is_binary": diff_file.is_binary,
                "rename_from": diff_file.rename_from,
                "rename_to": diff_file.rename_to,
            })

        return {
            "files_changed": len(files),
            "insertions": total_additions,
            "deletions": total_deletions,
            "files": sorted(file_rows, key=lambda row: row["path"]),
            "binary_files": binary_files,
            "unknown_insertions": unknown_insertions,
        }

    def get_annotated_diff(self) -> str:
        if self._annotated_diff is not None:
            return self._annotated_diff
        if not self.annotate_line_numbers or not self.diff_text:
            self._annotated_diff = self.diff_text
            return self._annotated_diff

        lines = self.diff_text.removesuffix("\n").split("\n")
        self._annotated_diff = "\n".join(self._annotate_lines(lines))
        return self._annotated_diff

    def _annotate_lines(self, lines: list[str]) -> Iterator[str]:
        old_line = None
        new_line = None
        for line in lines:
            if line.startswith("@@ "):
                old_line, new_line = self._parse_hunk_header(line)
            elif line.startswith("diff --git "):
                old_line = new_line = None
            elif new_line is not None and old_line is not None:
                if line.startswith("+"):
                    line += f"  (+L{new_line})"
                    new_line += 1
                elif line.startswith("-"):
                    line += f"  (-L{old_line})"
                    old_line += 1
                elif line.startswith(" "):
                    line += f"  (L{new_line})"
                    old_line += 1
                    new_line += 1
            yield line

    def _parse_hunk_header(self, header: str) -> Tuple[Optional[int], Optional[int]]:
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
        if not match:
            return None, None
        old_start = int(match.group(1))
        new_start = int(match.group(3))
        return old_start, new_start


def _redact_diff_lines(lines: list[str], redactor: Redactor) -> tuple[list[str], int]:
    # A hunk can end in the middle of a key. Redact its body independently of later hunks.
    blocks = iter(_diff_blocks("\n".join(lines)))
    positions = []
    count = 0
    in_hunk = False
    literal_sides = (False, False)
    for index, line in enumerate(lines):
        if line.startswith(("diff --git ", "@@ ")):
            count += _redact_hunk(lines, positions, redactor, literal_sides)
            positions = []
            in_hunk = line.startswith("@@ ")
            if not in_hunk:
                old_path, new_path, _ = next(blocks)
                literal_sides = (redactor.is_text_path(old_path), redactor.is_text_path(new_path))
            else:
                boundary = line.find(" @@", 3)
                if boundary >= 0:
                    offset = boundary + 3
                    title, matches = redactor.redact(
                        line[offset:], literal_assignments=any(literal_sides),
                    )
                    lines[index] = line[:offset] + title
                    count += matches
        elif in_hunk and line.startswith(("+", "-", " ")):
            positions.append(index)
    count += _redact_hunk(lines, positions, redactor, literal_sides)
    return lines, count


def _redact_hunk(
    lines: list[str], positions: list[int], redactor: Redactor, literal_sides: tuple[bool, bool],
) -> int:
    if not positions:
        return 0

    split_sides = literal_sides[0] != literal_sides[1]
    if any("-----BEGIN " in lines[index] for index in positions):
        prefixes = {lines[index][0] for index in positions}
        split_sides |= {"+", "-"} <= prefixes
    sides = [(positions, literal_sides[0])]
    if split_sides:
        sides = [
            ([index for index in positions if lines[index][0] != prefix], literals)
            for prefix, literals in zip(("+", "-"), literal_sides)
        ]

    replacements = {}
    count = 0
    for side, literals in sides:
        source = "\n".join(lines[index][1:] for index in side)
        safe, matches = redactor.redact(source, literal_assignments=literals, truncated_key=True)
        if not matches:
            continue
        count += matches
        for index, value in zip(side, safe.split("\n")):
            if value != lines[index][1:]:
                existing = replacements.get(index, value)
                replacements[index] = value if existing == value else redactor.LABEL
    for index, value in replacements.items():
        lines[index] = lines[index][0] + value
    return count


def _untracked_diff(git: GitOps, path: str) -> tuple[list[str], int | None]:
    old, new = ('"' + repr(os.fsencode(prefix + path))[2:-1].replace('"', r'\"') + '"'
                for prefix in ("a/", "b/"))
    header = [f"diff --git {old} {new}", "untracked file"]
    file = git.worktree_file(path)
    if file is None:
        return [*header, "Untracked contents omitted (not a regular worktree file)."], None
    try:
        with file.open("rb") as stream:
            data = stream.read(ReviewConfig.MAX_UNTRACKED_BYTES + 1)
    except OSError:
        return [*header, "Untracked contents omitted (file is unavailable)."], None
    if ReviewConfig.is_binary_path(path) or b"\0" in data:
        return [*header, f"Binary files /dev/null and {new} differ"], None
    if len(data) > ReviewConfig.MAX_UNTRACKED_BYTES:
        return [*header, "Untracked contents omitted (file exceeds the byte limit)."], None
    lines = data.decode("utf-8", errors="replace").removesuffix("\n").split("\n") if data else []
    visible = lines[:ReviewConfig.MAX_UNTRACKED_LINES]
    if visible:
        header.extend(["--- /dev/null", f"+++ {new}", f"@@ -0,0 +1,{len(visible)} @@"])
        header.extend(f"+{line}" for line in visible)
    if len(lines) > len(visible):
        header.append(f"... [file truncated, {len(lines) - len(visible)} lines omitted]")
    return header, len(lines)
