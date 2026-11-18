import re
from contextlib import contextmanager
from pathlib import Path

import click

from ai_review.config import ReviewConfig


def _write(payload: str, output: Path | None = None, *, terminator: str = "\n"):
    # Preserve non-UTF-8 Git path bytes as visible escape sequences.
    payload = payload.replace("\0", r"\0").encode("utf-8", errors="backslashreplace").decode("utf-8")
    if not payload.endswith(terminator):
        payload += terminator
    if output is None:
        click.echo(payload, nl=False)
    else:
        output.write_text(payload, encoding="utf-8")


@contextmanager
def _cli_errors():
    try:
        yield
    except (RuntimeError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


def _review_options(command):
    command = click.option("--head", help="Head ref for branch comparison. Defaults to HEAD.")(command)
    command = click.option("--base", help="Compare changes from the merge base with this ref.")(command)
    command = click.option("--mode", type=click.Choice(["working"]), default="working",
                           expose_value=False, help="Review uncommitted changes when no refs are supplied.")(command)
    return click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))(command)


def _diff_options(command):
    command = click.option("--line-numbers/--no-line-numbers", default=None,
                           help="Annotate printed diffs with line numbers. Defaults to on.")(command)
    return click.option("--max-diff-lines", type=click.IntRange(min=1),
                        help=f"Limit printed diff lines. Defaults to {ReviewConfig.MAX_DIFF_LINES}.")(command)


def _scope(path, base, head):
    from ai_review.git_ops import GitOps

    if head is not None and base is None:
        raise click.UsageError("--head requires --base.")
    git = GitOps.at_worktree_root(path)
    return git, git.review_target(base, head)


def _chunk_destination(output):
    if output.is_dir() or not output.suffix:
        return output, "chunk"
    return output.parent, output.stem


def _previous_prompt_outputs(output, chunked, root):
    if chunked:
        directory, prefix = _chunk_destination(output)
        if not directory.is_dir():
            return set()
        chunk_name = re.compile(rf"{re.escape(prefix)}\.[0-9]{{2,}}\.md")
        candidates = (
            file for file in directory.iterdir()
            if chunk_name.fullmatch(file.name)
        )
    else:
        candidates = (output,)
    root = Path(root)
    paths = set()
    for candidate in candidates:
        # Resolve the directory so aliases for the repository root still match Git paths.
        path = candidate.parent.resolve() / candidate.name
        if path.is_relative_to(root):
            paths.add(path.relative_to(root).as_posix())
    return paths


@click.group()
def main():
    """Prepare a repository review centered on verifiable challenges."""


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--full", is_flag=True, help="Rebuild all structural summaries.")
@click.option("--incremental", is_flag=True, default=True, expose_value=False, help="Reuse current summaries.")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), help="Write the guide here.")
@click.option("--read-only", is_flag=True, help="Print the guide and skip cache writes.")
def analyze(path, full, output, read_only):
    """Build a structural guide from the current files."""
    from ai_review.summarize.repo_guide import RepoAnalyzer

    with _cli_errors():
        analyzer = RepoAnalyzer(path, cache_enabled=not read_only)
        data = analyzer.analyze(full=full)
        guide = analyzer.generate_guide(data)
        destination = output if output is not None else (None if read_only else path / "REPO_GUIDE.md")
        _write(guide, destination)
        if destination is not None:
            click.echo(f"Wrote {destination} after analyzing {len(data)} files.", err=True)


@main.command()
@_review_options
@_diff_options
@click.option("--include-untracked/--no-include-untracked", default=False, help="Include untracked files.")
def changes(path, base, head, max_diff_lines, line_numbers, include_untracked):
    """Print a redacted change summary and annotated diff."""
    from ai_review.summarize.changes import ChangeCollector

    with _cli_errors():
        git, target = _scope(path, base, head)
        collector = ChangeCollector.from_git(
            git, target, include_untracked, max_diff_lines, line_numbers is not False,
        )
        _write(collector.get_markdown_summary())


@main.command()
@_review_options
@_diff_options
@click.option("--include-untracked/--no-include-untracked", default=True, help="Include untracked files.")
@click.option("--read-only", is_flag=True, help="Skip cache writes.")
def packet(path, base, head, max_diff_lines, line_numbers, include_untracked, read_only):
    """Print supplemental material for an offline or limited-access review."""
    from ai_review.summarize.changes import ChangeCollector
    from ai_review.summarize.packet import PacketBuilder

    with _cli_errors():
        git, target = _scope(path, base, head)
        collector = ChangeCollector.from_git(
            git, target, include_untracked, max_diff_lines, line_numbers is not False,
        )
        _write(PacketBuilder(git, cache_enabled=not read_only).build(target, collector))


@main.command()
@_review_options
@click.option("--intent", multiple=True, metavar="TEXT", help="Author notes on intended behavior. Repeatable.")
@click.option("--context-file", multiple=True, metavar="PATH", help="Point to a file at the review target. Repeatable.")
@click.option("--include-untracked/--no-include-untracked", default=True, help="Include untracked files in working mode.")
@click.option("--output", type=click.Path(path_type=Path), help="Write the prompt to a file.")
@click.option("--with-packet", is_flag=True, help="Attach a supplemental packet for limited-access agents.")
@click.option("--chunked", is_flag=True, help="Attach supplemental material in separate chunks.")
@click.option("--chunk-separator", type=click.Choice(["divider", "nul"]), default="divider", help="Chunk separator.")
@click.option("--read-only", is_flag=True, help="Skip cache writes when attaching a packet.")
@_diff_options
def prompt(path, base, head, intent, context_file, include_untracked, output, with_packet,
           chunked, chunk_separator, read_only, max_diff_lines, line_numbers):
    """Write a concise, read-in-place brief for a reviewing agent."""
    from ai_review.prompt.composer import PromptComposer

    with _cli_errors():
        git, target = _scope(path, base, head)
        omit_untracked = (
            _previous_prompt_outputs(output, chunked, git.repo_path)
            if output is not None and target.working and include_untracked else ()
        )
        with_packet = with_packet or chunked or max_diff_lines is not None or line_numbers is not None
        collector = None
        if with_packet:
            from ai_review.summarize.changes import ChangeCollector

            collector = ChangeCollector.from_git(
                git, target, include_untracked, max_diff_lines, line_numbers is not False,
                omit_untracked=omit_untracked,
            )

        entries = collector.entries if collector is not None else git.review_entries(
            target, include_untracked, omit_untracked=omit_untracked,
        )
        brief = PromptComposer().compose(git, target, entries, include_untracked, intent, context_file)
        if collector is not None:
            from ai_review.summarize.packet import PacketBuilder

            material = PacketBuilder(git, cache_enabled=not read_only).build(target, collector)
            if chunked:
                _write_chunked(brief, material, output, chunk_separator)
                return
            brief += "\n\n" + material
        _write(brief, output)
        if output is not None:
            click.echo(f"Wrote {output}.", err=True)


def _write_chunked(brief, material, output, separator):
    from ai_review.prompt.chunker import PromptChunker

    chunks = PromptChunker().chunk_packet(material)
    if output is not None:
        destination, prefix = _chunk_destination(output)
        destination.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks, 1):
        prompt_text = f"{brief}\n\n{chunk}"
        if len(chunks) > 1:
            prompt_text += ("\n\nThis excerpt covers part of the change. Record what you inspected "
                            "and use the checkout to fill material gaps.")
        if output is not None:
            _write(prompt_text, destination / f"{prefix}.{i:02d}.md")
        elif separator == "nul":
            _write(prompt_text, terminator="\0")
        else:
            if i > 1:
                click.echo("\n" + "=" * 40 + "\n")
            _write(prompt_text)

    if output is not None:
        click.echo(f"Wrote {len(chunks)} prompt(s) to {destination}.", err=True)


@main.command()
@click.argument("reviews_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), help="Write the synthesis prompt here.")
def synthesize_prompt(reviews_dir, output):
    """Ask an agent to reconcile review challenges from Markdown reports."""
    from ai_review.markdown import inline_code
    from ai_review.prompt.composer import PromptComposer
    from ai_review.security.redact import Redactor

    with _cli_errors():
        reports = []
        redactor = Redactor()
        for path in sorted(reviews_dir.glob("*.md")):
            if path.is_symlink() or not path.is_file() or (output and path.resolve() == output.resolve()):
                continue
            report, _ = redactor.redact(
                path.read_text(encoding="utf-8"), detect_entropy=False, literal_assignments=True,
            )
            quoted = "\n".join(f"> {line}" for line in report.splitlines())
            reports.append(f"### Report {inline_code(path.name)}\n\n{quoted}")
        if not reports:
            raise click.ClickException("No Markdown review reports found.")
        _write(PromptComposer().synthesize(reports), output)
        if output is not None:
            click.echo(f"Wrote {output}.", err=True)


if __name__ == "__main__":
    main()
