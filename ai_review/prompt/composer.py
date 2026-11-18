import os
import shlex
from importlib.resources import files
from itertools import chain, islice
from pathlib import Path
from textwrap import wrap

from ai_review.config import ReviewConfig
from ai_review.git_ops import DIFF_OPTIONS, GitOps, ReviewTarget
from ai_review.markdown import inline_code
from ai_review.security.redact import Redactor


class PromptComposer:
    """Compose review instructions for an agent with access to the change."""

    INDEX_LIMIT = 20
    INDEX_CHAR_LIMIT = 2000

    def _read_template(self, name: str) -> str:
        return files("ai_review.prompt").joinpath("templates", f"{name}.md").read_text(
            encoding="utf-8"
        ).strip()

    def compose(
        self,
        git: GitOps,
        target: ReviewTarget,
        entries: list[dict],
        include_untracked: bool,
        intent: tuple[str, ...] = (),
        context_files: tuple[str, ...] = (),
    ) -> str:
        scope = self._scope(git, target, entries, include_untracked)
        context = self._author_context(git, target, intent, context_files)
        brief = self._read_template("system").format(
            scope=scope, author_context=f"\n\n{context}" if context else "",
        )
        return f"{brief}\n\n{self._read_template('outcome')}"

    def _scope(
        self, git: GitOps, target: ReviewTarget, entries: list[dict], include_untracked: bool
    ) -> str:
        lines = ["## Review scope", "", f"Repository root {inline_code(git.repo_path)}.", ""]
        baseline = inline_code(target.baseline)
        if target.working:
            start = "the empty tree" if target.unborn else f"HEAD at {baseline}"
            untracked = "included" if include_untracked else "excluded"
            lines.append(f"Working tree compared with {start}. The scope includes staged and unstaged edits. "
                         f"Untracked files are {untracked}.")
            if target.unborn:
                lines.append("Confirm the repository still has no commits before reviewing.")
            else:
                lines.append("Confirm HEAD and the current files before using the path list. "
                             f"For prior decisions, see `git log -5 {target.baseline} -- <paths>`.")
        else:
            history = shlex.join(["git", "log", "--format=%h %s%n%b", f"{target.baseline}..{target.head}"])
            lines.extend([
                f"{inline_code(target.head_ref)} against {inline_code(target.base_ref)}. "
                f"Review head {inline_code(target.head)} from merge base {baseline}.",
                f"For change history, run `{history}`.",
                "Read files at either revision with `git show <commit>:<path>`. "
                "Confirm the checkout revision before running tests.",
            ])

        tracked = any(entry["status"] != "??" for entry in entries)
        if tracked:
            args = ["git", "--literal-pathspecs", "diff", *DIFF_OPTIONS, *target.diff_args, "--"]
            command = f"{shlex.join(args)} <paths>"
            wrapped = " \\\n  ".join(wrap(command, width=84, break_long_words=False, break_on_hyphens=False))
            lines.extend([
                "",
                "From the repository root, replace `<paths>` with quoted paths. "
                "Include both names when inspecting a rename.",
                "",
                "```sh",
                wrapped,
                "```",
            ])
        notes = []
        if target.working and include_untracked:
            notes.append("Read relevant untracked regular files directly.")
        notes.append("Keep sensitive files and generated output out of the review.")
        lines.extend(["", " ".join(notes)])

        index = []
        index_size = 0
        for entry in self._preview_entries(entries):
            if len(index) == self.INDEX_LIMIT:
                break
            path = inline_code(entry["path"])
            if entry.get("old_path"):
                path = f'{inline_code(entry["old_path"])} → {path}'
            row = f'- {entry["status"]} {path}'
            if index_size + len(row) > self.INDEX_CHAR_LIMIT:
                continue
            index_size += len(row)
            index.append(row)
        if index:
            lines.extend(["", "### Changed paths", "", *index])
        if len(index) < len(entries):
            hints = []
            if tracked:
                hints.append("For the full tracked list, add `--name-status` before the commits "
                             "in the diff command and omit `<paths>`.")
            if target.working and include_untracked:
                hints.append("List untracked paths with `git ls-files --others --exclude-standard`.")
            lines.extend(["", f"Showing {len(index)} of {len(entries)} entries. " + " ".join(hints)])
        elif not entries:
            lines.extend(["", "Git reported no changes in scope."])
        return "\n".join(lines)

    def _preview_entries(self, entries: list[dict]):
        if len(entries) <= self.INDEX_LIMIT:
            return iter(entries)

        # Show evidence of intended behavior and spread the remaining preview across directories.
        priority = set()
        for classify in (ReviewConfig.is_test_path, ReviewConfig.is_doc_path):
            matches = (
                index for index, entry in enumerate(entries)
                if index not in priority and entry["status"] != "D" and classify(entry["path"])
            )
            priority.update(islice(matches, 2))
        directories = set()
        for index, entry in enumerate(entries):
            directory = entry["path"].rpartition("/")[0]
            if index not in priority and directory not in directories:
                directories.add(directory)
                priority.add(index)
                if len(priority) == self.INDEX_LIMIT:
                    break
        return chain(
            (entries[index] for index in sorted(priority)),
            (entry for index, entry in enumerate(entries) if index not in priority),
        )

    def _author_context(
        self, git: GitOps, target: ReviewTarget, intent: tuple[str, ...], paths: tuple[str, ...]
    ) -> str:
        if not intent and not paths:
            return ""

        lines = ["## Author context", ""]
        redactor = Redactor()
        for note in intent:
            redacted, _ = redactor.redact(note, detect_entropy=False, literal_assignments=True)
            lines.extend(f"> {line}" for line in redacted.splitlines())
            lines.append("")
        root = Path(git.repo_path)
        for name in paths:
            absolute = Path(os.path.abspath(root / name))
            try:
                relative = absolute.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(f"Context file must be inside the repository ({name!r}).") from exc
            if ReviewConfig.should_exclude(relative):
                raise ValueError(f"Context file is excluded ({name!r}).")
            if target.working:
                if git.worktree_file(relative) is None:
                    raise ValueError(f"Context file must be a regular worktree file ({name!r}).")
            elif not git.has_regular_blob(target.head, relative):
                raise ValueError(f"Context file is unavailable at the review head as a regular file ({name!r}).")
            revision = "working tree" if target.working else "review head"
            lines.append(f"- Consult {inline_code(relative)} from the {revision}.")
        return "\n".join(lines).rstrip()

    def synthesize(self, reports: list[str]) -> str:
        return "\n\n".join([
            self._read_template("synthesis"), "## Input reports", "\n\n".join(reports),
            self._read_template("outcome"),
        ])
