from ai_review.summarize.changes import ChangeCollector


def test_annotated_diff_line_numbers():
    diff = """diff --git a/file.txt b/file.txt
index 1111111..2222222 100644
--- a/file.txt
+++ b/file.txt
@@ -1,2 +1,3 @@
 line1
-line2
+line2 updated
+line3
"""
    collector = ChangeCollector(diff, annotate_line_numbers=True)
    annotated = collector.get_annotated_diff()

    assert " line1  (L1)" in annotated
    assert "-line2  (-L2)" in annotated
    assert "+line2 updated  (+L2)" in annotated
    assert "+line3  (+L3)" in annotated


def test_prefix_like_source_lines_count_and_advance_line_numbers():
    diff = """diff --git a/file b/file
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
--- removed
+++ added
 next
"""
    collector = ChangeCollector(diff, max_diff_lines=5)
    assert collector.get_summary()["insertions"] == 1
    assert collector.get_summary()["deletions"] == 1
    assert "--- removed  (-L1)" in collector.get_annotated_diff()
    assert "+++ added  (+L1)" in collector.get_annotated_diff()
    assert " next  (L2)" in collector.get_annotated_diff()
    assert "Diff truncated**: 2 lines omitted" in collector.get_markdown_summary()


def test_chunk_boundary_balances_diff_fences():
    from ai_review.prompt.chunker import PromptChunker

    packet = "First\n```diff\n" + "+A long added line\n" * 4 + "```\nLast"
    chunks = PromptChunker(max_tokens=10).chunk_packet(packet)

    assert len(chunks) > 1
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert sum(chunk.count("+A long added line") for chunk in chunks) == 4


def test_bounded_preview_caps_the_hunk_index_and_long_lines(monkeypatch):
    from ai_review.config import ReviewConfig

    monkeypatch.setattr(ReviewConfig, "MAX_DIFF_PREVIEW_CHARS", 120)
    monkeypatch.setattr(ReviewConfig, "MAX_HUNK_INDEX", 1)
    diff = (
        "diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -1,0 +1 @@\n"
        "+" + "long line " * 50 + "\n@@ -300,0 +302 @@\n+next\n"
    )

    report = ChangeCollector(diff).get_markdown_summary()

    assert "Diff truncated**: 3 lines omitted" in report
    assert "Hunk index truncated, 1 hunks omitted" in report
    assert "long line" not in report
    assert "**Insertions**: 2" in report


def test_redaction_preserves_diff_metadata_prefixes_and_citations():
    revision = "8435f7b3031572a3dc7ec384118347cf884a89d5"
    value = "abcdef1234567890zzzzz"
    diff = (
        f"diff --git a/file b/file\nindex {revision}..{revision} 100644\n"
        f"--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+token={value}\n"
    )

    report = ChangeCollector(diff).get_markdown_summary()

    assert f"index {revision}..{revision}" in report
    assert "+[REDACTED: potential secret]  (+L1)" in report
    assert value not in report


def test_private_key_banner_quoted_in_code_keeps_later_changes_visible():
    diff = """diff --git a/test_auth.py b/test_auth.py
--- /dev/null
+++ b/test_auth.py
@@ -0,0 +1 @@
+assert "-----BEGIN RSA PRIVATE KEY-----" in blob
diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1 +1 @@ def authenticate(user):
-return None
+return authenticate(user)
"""

    report = ChangeCollector(diff).get_markdown_summary()

    assert '+assert "-----BEGIN RSA PRIVATE KEY-----" in blob  (+L1)' in report
    assert "+return authenticate(user)  (+L1)" in report
    assert "@@ -1 +1 @@ def authenticate(user):" in report


def test_open_private_key_stops_at_its_diff_side_and_hunk():
    diff = """diff --git a/service.py b/service.py
--- a/service.py
+++ b/service.py
@@ -1,2 +1 @@
------BEGIN RSA PRIVATE KEY-----
-sample content
+token = user.token
@@ -12 +11 @@ def authenticate(user):
-return None
+return authenticate(user)
"""

    report = ChangeCollector(diff).get_markdown_summary()

    assert "sample content" not in report
    assert "-[REDACTED: potential secret]  (-L2)" in report
    assert "+token = user.token  (+L1)" in report
    assert "+return authenticate(user)  (+L11)" in report

    truncated = ChangeCollector(diff, max_diff_lines=6).get_markdown_summary()
    assert "sample content" not in truncated
    assert "-[REDACTED: potential secret]  (-L2)" in truncated
