import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from ai_review.cli import main


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "ai_review.cli", *args], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "--initial-branch=main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Review Tests")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def test_default_prompt_reads_scope_and_links_intent_without_a_packet(repo):
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("base = True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    (src / "app.py").write_text("raw_sentinel = True\n")
    (repo / "decisions.md").write_text("context_sentinel\n")
    (repo / ".env.staging").write_text("hidden_sentinel\n")

    result = CliRunner().invoke(main, [
        "prompt", str(src), "--intent", "Existing overrides survive.",
        "--context-file", "decisions.md",
    ])

    assert result.exit_code == 0, result.output
    assert f"Repository root `{repo.resolve()}`" in result.output
    assert "- M `src/app.py`" in result.output
    assert "- ?? `decisions.md`" in result.output
    assert "> Existing overrides survive." in result.output
    assert "Consult `decisions.md` from the working tree" in result.output
    assert "You are an independent engineering investigator." in result.output
    assert "The author verifies each challenge against the implementation and intended behavior" in result.output
    assert "Cover the full change inventory" in result.output
    assert "Try to falsify each proposition" in result.output
    assert "**Adversarial examination.**" in result.output
    assert "**Evidence status.**" in result.output
    assert "**Preservation constraints.**" in result.output
    assert "### The redesign may have broken established answer navigation" in result.output
    assert "**Behavioral claim.** Given an answer containing a valid project-creation action" in result.output
    assert "**Intent basis.** PR #527 introduced next-step actions." in result.output
    assert "**Verification.** Construct an answer containing the real API target shape." in result.output
    assert "**Disproof conditions.** The action renders through another supported path" in result.output
    assert "**Requested change.** None." in result.output
    assert "**Unresolved questions**" in result.output
    assert "**No material challenges established**" in result.output
    assert "**Review blocked**" in result.output
    assert "Leave the design response to the author." in result.output
    assert "review packet" not in result.output.lower()
    assert "sentinel" not in result.output
    assert ".env.staging" not in result.output
    assert not (repo / ".ai_review").exists()

    tracked_only = CliRunner().invoke(main, ["prompt", str(repo), "--no-include-untracked"])
    assert tracked_only.exit_code == 0
    assert "decisions.md" not in tracked_only.output


def test_branch_review_uses_merge_base_and_review_head_when_checkout_differs(repo):
    file = repo / "service.py"
    file.write_text("def baseline(): pass\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    baseline = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-c", "feature")
    file.write_text("def from_review_head(): pass\n")
    (repo / "design.md").write_text("Keep existing behavior.\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feature")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "main")
    (repo / "main_only.md").write_text("main\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "main advances")
    file.write_text("def from_checkout(): pass\n")

    runner = CliRunner()
    args = [str(repo), "--base", "main", "--head", "feature"]
    automatic = runner.invoke(main, ["prompt", *args])
    assert automatic.exit_code == 0, automatic.output
    assert "Author context" not in automatic.output
    assert f"{baseline}..{head}" in automatic.output
    assert "baseline tests" in automatic.output

    result = runner.invoke(main, ["prompt", *args, "--context-file", "design.md"])
    assert result.exit_code == 0, result.output
    assert f"Review head `{head}` from merge base `{baseline}`" in result.output
    assert "Consult `design.md` from the review head" in result.output
    assert "main_only.md" not in result.output
    assert "from_checkout" not in result.output

    packet = runner.invoke(main, ["packet", *args, "--read-only"])
    assert packet.exit_code == 0, packet.output
    assert "    def from_review_head(): ..." in packet.output
    assert "from_checkout" not in packet.output

    missing = run_cli("prompt", *args, "--context-file", "main_only.md")
    assert missing.returncode != 0
    assert missing.stdout == ""
    assert "unavailable at the review head" in missing.stderr


def test_unborn_repository_reviews_latest_content_of_staged_file(repo):
    src = repo / "app.py"
    src.write_text("only_in_index = True\n")
    git(repo, "add", "app.py")
    src.write_text("current = True\n")

    runner = CliRunner()
    result = runner.invoke(main, ["prompt", str(repo)])
    assert result.exit_code == 0, result.output
    assert "compared with the empty tree" in result.output
    assert "- A `app.py`" in result.output

    changes = runner.invoke(main, ["changes", str(repo)])
    assert changes.exit_code == 0, changes.output
    assert "+current = True  (+L1)" in changes.output
    assert "only_in_index" not in changes.output


def test_sensitive_paths_and_renames_are_excluded_in_supplemental_outputs(repo):
    (repo / "nested").mkdir()
    (repo / "nested" / ".env.staging").write_text("hidden env fixture\n")
    (repo / "signing.pem").write_text("hidden signing fixture\n")
    (repo / 'naïve b/').mkdir()
    visible = repo / "naïve b" / 'odd\t"name.txt'
    visible.write_text("before\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "mv", "signing.pem", "looks_public.txt")
    (repo / "nested" / ".env.staging").write_text("hidden changed env fixture\n")
    visible.write_text("after\n")
    (repo / "shortcut.py").symlink_to(repo / "nested" / ".env.staging")

    runner = CliRunner()
    for args in [
        ("changes", "--include-untracked"), ("packet", "--read-only"),
        ("prompt", "--with-packet", "--read-only"),
    ]:
        result = runner.invoke(main, [*args, str(repo)])
        assert result.exit_code == 0, result.output
        assert "+after  (+L1)" in result.output
        assert "looks_public.txt" not in result.output
        assert ".env.staging" not in result.output
        assert "hidden changed env" not in result.output
        assert "not a regular worktree file" in result.output


def test_invalid_scope_fails_without_emitting_a_prompt(repo):
    head_only = run_cli("prompt", str(repo), "--head", "main")
    assert head_only.returncode == 2
    assert head_only.stdout == ""
    assert "--head requires --base" in head_only.stderr

    invalid = run_cli("prompt", str(repo), "--base", "missing")
    assert invalid.returncode != 0
    assert invalid.stdout == ""
    assert "Git command failed" in invalid.stderr


def test_synthesis_preserves_revision_citations_and_ignores_its_own_output(repo):
    revision = "a26413de755112db754b5de66bf731636652ba5f"
    (repo / "b.md").write_text("Second report\n")
    (repo / "a.md").write_text(
        f"Revision {revision}\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "The following evidence must remain visible.\n"
        "A pasted credential appeared as `password = examplepassphrase`.\n"
    )
    output = repo / "synthesis.md"
    output.write_text("stale output\n")

    result = CliRunner().invoke(main, ["synthesize-prompt", str(repo), "--output", str(output)])

    assert result.exit_code == 0, result.output
    prompt = output.read_text()
    assert f"> Revision {revision}" in prompt
    assert prompt.index("a.md") < prompt.index("b.md")
    assert prompt.index("## Input reports") < prompt.index("## Write the review")
    assert "stale output" not in prompt
    assert "same behavior, conditions, and review target" in prompt
    assert "Preserve disagreements that affect how the author should verify a challenge." in prompt
    assert "> The following evidence must remain visible." in prompt
    assert "examplepassphrase" not in prompt


def test_author_note_masks_letter_only_values_and_keeps_text_after_pem_banner(repo):
    note = (
        "Admin password = examplepassphrase.\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "Existing overrides survive."
    )

    result = CliRunner().invoke(main, ["prompt", str(repo), "--intent", note])

    assert result.exit_code == 0, result.output
    assert "examplepassphrase" not in result.output
    assert "> Admin [REDACTED: potential secret]." in result.output
    assert "> Existing overrides survive." in result.output


def test_diff_distinguishes_text_values_from_source_references_after_a_split_move(repo):
    original = repo / "secrets.json"
    original.write_text('{"original": "unrelated baseline fixture"}\n')
    source = repo / "auth.py"
    source.write_text("import service\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    git(repo, "mv", original.name, "public_config.txt")
    (repo / "public_config.txt").write_text("password = examplepassphrase\n")
    source.write_text("secret = default_session_secret\n")

    result = CliRunner().invoke(main, ["changes", str(repo)])

    assert result.exit_code == 0, result.output
    assert "| A | `public_config.txt` |" in result.output
    assert "secrets.json" not in result.output
    assert "examplepassphrase" not in result.output
    assert "+[REDACTED: potential secret]  (+L1)" in result.output
    assert "+secret = default_session_secret  (+L1)" in result.output


def test_incremental_analysis_uses_worktree_content_and_skips_deleted_files(repo):
    src = repo / "app.py"
    src.write_bytes(b"# coding: latin-1\ndef original():\n    \"\"\"caf\xe9\"\"\"\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    runner = CliRunner()
    args = ["analyze", str(repo)]
    original = runner.invoke(main, args)
    assert original.exit_code == 0, original.output
    guide = repo / "REPO_GUIDE.md"
    assert "def original()" in guide.read_text()
    cache = repo / ".ai_review/cache/analysis.json"
    cached_at = cache.stat().st_mtime_ns
    assert runner.invoke(main, args).exit_code == 0
    assert cache.stat().st_mtime_ns == cached_at

    src.write_text("def edited(): pass\n")
    edited = runner.invoke(main, args)
    assert edited.exit_code == 0, edited.output
    assert "def edited()" in guide.read_text()
    assert "def original()" not in guide.read_text()

    src.unlink()
    deleted = runner.invoke(main, args)
    assert deleted.exit_code == 0, deleted.output
    assert "app.py" not in guide.read_text()


def test_large_change_index_is_bounded_and_keeps_a_way_to_find_remaining_paths(repo):
    (repo / "examples").mkdir()
    for i in range(22):
        (repo / "examples" / f"file_{i:02d}.txt").write_text("contents\n")
    (repo / "zz_feature.py").write_text("enabled = True\n")
    (repo / "zz_design.md").write_text("Behavior contract\n")
    (repo / "test_zz_behavior.py").write_text("assert True\n")
    result = CliRunner().invoke(main, ["prompt", str(repo)])

    assert result.exit_code == 0, result.output
    assert "Showing 20 of 25 entries" in result.output
    assert "git ls-files --others --exclude-standard" in result.output
    assert "zz_design.md" in result.output
    assert "test_zz_behavior.py" in result.output
    assert "zz_feature.py" in result.output
    assert "file_21.txt" not in result.output


def test_recreated_staged_deletion_keeps_both_entries(repo):
    path = repo / "one.txt"
    path.write_text("original\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "rm", "one.txt")
    path.write_text("replacement\n")

    changes = CliRunner().invoke(main, ["changes", str(repo), "--include-untracked"])

    assert changes.exit_code == 0, changes.output
    assert "| D | `one.txt` | 0 | 1 |" in changes.output
    assert "| ?? | `one.txt` | 1 | 0 |" in changes.output
    assert "-original  (-L1)" in changes.output
    assert "+replacement  (+L1)" in changes.output


def test_file_type_change_is_counted_once(repo):
    path = repo / "one.txt"
    path.write_text("original\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    path.unlink()
    path.symlink_to("other.txt")

    result = CliRunner().invoke(main, ["changes", str(repo)])

    assert result.exit_code == 0, result.output
    assert "**Files changed**: 1" in result.output
    assert result.output.count("| T | `one.txt` | 1 | 1 |") == 1
    assert "-original  (-L1)" in result.output
    assert "+other.txt  (+L1)" in result.output


def test_broken_head_fails_instead_of_reviewing_against_an_empty_tree(repo):
    (repo / ".git/refs/heads/main").write_text("f" * 40 + "\n")

    result = run_cli("prompt", str(repo))

    assert result.returncode != 0
    assert result.stdout == ""
    assert "bad object HEAD" in result.stderr


def test_review_context_rejects_symlinks_in_a_branch(repo):
    (repo / "README.md").write_text("Design")
    (repo / "context.md").symlink_to("README.md")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    result = run_cli("prompt", str(repo), "--base", "main", "--context-file", "context.md")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "regular file" in result.stderr


def test_previous_prompt_output_does_not_enter_the_next_review(repo):
    output = repo / "review.md"
    output.write_text("Previous output sentinel.\n")
    (repo / "change.txt").write_text("New code\n")
    runner = CliRunner()

    result = runner.invoke(main, ["prompt", str(repo), "--with-packet", "--read-only", "--output", str(output)])

    assert result.exit_code == 0, result.output
    prompt = output.read_text()
    assert "change.txt" in prompt
    assert "review.md" not in prompt
    assert "Previous output sentinel" not in prompt


def test_chunked_output_uses_an_existing_directory_with_a_suffix(repo):
    output = repo / "review.v1"
    output.mkdir()
    chunk = output / "chunk.01.md"
    chunk.write_text("Previous output sentinel.\n")
    (output / "change.txt").write_text("New code\n")

    result = CliRunner().invoke(main, ["prompt", str(repo), "--chunked", "--read-only", "--output", str(output)])

    assert result.exit_code == 0, result.output
    prompt = chunk.read_text()
    assert "review.v1/change.txt" in prompt
    assert "chunk.01.md" not in prompt
    assert "Previous output sentinel" not in prompt


def test_untracked_insertions_include_lines_omitted_from_the_preview(repo):
    (repo / "many.txt").write_text("preview line\n" * 405)
    (repo / "large.txt").write_text("x" * 1_000_001)

    result = CliRunner().invoke(main, ["changes", str(repo), "--include-untracked"])

    assert result.exit_code == 0, result.output
    assert "| ?? | `many.txt` | 405 | 0 |" in result.output
    assert "| ?? | `large.txt` | - | 0 |" in result.output
    assert "**Untracked files with unknown insertions**: 1" in result.output
    assert "@@ -0,0 +1,400 @@" in result.output
    assert "[file truncated, 5 lines omitted]" in result.output


def test_sensitive_rename_cannot_reappear_through_downstream_context(repo):
    source = repo / "service.py"
    source.write_text("def contract(): return 1\n")
    excluded = repo / "credentials"
    excluded.mkdir()
    (excluded / "module.py").write_text('"""Private context fixture."""\nfrom service import contract\n')
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "mv", "credentials/module.py", "analysis_only.py")
    source.write_text("def contract(): return 2\n")

    packet = CliRunner().invoke(main, ["packet", str(repo), "--read-only"])

    assert packet.exit_code == 0, packet.output
    assert "service.py" in packet.output
    assert "analysis_only.py" not in packet.output
    assert "Private context fixture" not in packet.output


def test_nul_chunk_stream_escapes_nul_bytes_from_forced_text_diffs(repo):
    (repo / ".gitattributes").write_text("source.txt diff\n")
    source = repo / "source.txt"
    source.write_bytes(b"old\x00value\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    source.write_bytes(b"new\x00value\n")

    result = run_cli("prompt", str(repo), "--chunked", "--chunk-separator", "nul", "--read-only")

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("\x00")
    assert result.stdout.count("\x00") == 1
    assert r"+new\0value" in result.stdout
