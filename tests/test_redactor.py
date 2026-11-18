from ai_review.security.redact import Redactor


def test_redact_counts_and_labels():
    redactor = Redactor()
    text = "api_key=abcdefghijklmnopqrstuvwxyz123456 token=abcd1234abcd1234abcd1234"
    redacted, count = redactor.redact(text)

    assert count >= 2
    assert "[REDACTED: potential secret]" in redacted


def test_redact_no_false_positive_on_plain_text():
    redactor = Redactor()
    text = "hello world"
    redacted, count = redactor.redact(text)

    assert redacted == text
    assert count == 0


def test_redact_multiline_keys_quoted_values_and_bearer_headers():
    text = (
        '{"password": "short value!"}\n'
        "Authorization: Bearer abc.def.ghi\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "lowentropy fixture\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
        "visible"
    )
    redacted, count = Redactor().redact(text)

    assert count == 3
    assert all(secret not in redacted for secret in ["short value!", "abc.def.ghi", "lowentropy"])
    assert redacted.count("\n") == text.count("\n")
    assert redacted.endswith("visible")


def test_assignments_keep_expressions_and_mask_secret_values():
    text = (
        "token = user.token\n"
        "password = hash_password(password)\n"
        "secret = default_session_secret\n"
        'password = "short value!"\n'
        "password=hidden123\n"
    )

    redacted, count = Redactor().redact(text, detect_entropy=False)

    assert count == 2
    assert redacted.splitlines()[:3] == text.splitlines()[:3]
    assert "short value!" not in redacted
    assert "hidden123" not in redacted


def test_entropy_keeps_source_references_with_or_without_spaces():
    text = "secret = default_session_secret\nsecret=default_session_secret"

    assert Redactor().redact(text) == (text, 0)


def test_private_key_footer_must_match_the_begin_banner():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
        "sample content\n"
        "-----END RSA PRIVATE KEY-----\n"
        "after"
    )

    redacted, count = Redactor().redact(text)

    assert count == 1
    assert "sample content" not in redacted
    assert redacted.count("\n") == text.count("\n")
    assert redacted.endswith("after")


def test_unclosed_key_in_prose_preserves_text_and_redacts_key_shaped_lines():
    banner = "-----BEGIN RSA PRIVATE KEY-----"
    payload = "A" * 62 + "=="
    text = (
        f"{banner}\nA later finding remains visible.\n"
        f">{banner}\n> {payload}\nThe final finding remains visible."
    )

    redacted, count = Redactor().redact(text, detect_entropy=False)

    assert count == 1
    assert payload not in redacted
    assert redacted.startswith(f"{banner}\nA later finding remains visible.")
    assert redacted.endswith("The final finding remains visible.")
    assert redacted.count("\n") == text.count("\n")
