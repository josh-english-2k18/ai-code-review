import math
import re
from pathlib import PurePath


class Redactor:
    """Detects and redacts secrets and sensitive information from text."""

    _CREDENTIAL_FIELD = (
        r"\b(?:api[_-]?key|secret|password|passwd|pwd|token|bearer|"
        r"aws[_-]?(?:access[_-]?key(?:[_-]?id)?|secret(?:[_-]?access[_-]?key)?))"
        r"""["']?[ \t]*[=:][ \t]*"""
    )
    _QUOTED = r""" "(?:\\.|[^"\\\r\n])*" | '(?:\\.|[^'\\\r\n])*' """
    _BARE = r"[a-z0-9_+/=-]{8,}"
    _VALUE_END = r"(?=$|[\s,;}`\]]|[.!?](?=$|[\s,;}`\]]))"
    ASSIGNMENT = re.compile(
        rf"{_CREDENTIAL_FIELD}(?:{_QUOTED}|(?=[a-z0-9_+/=-]*[0-9+/=-]){_BARE}{_VALUE_END})",
        re.IGNORECASE | re.VERBOSE,
    )
    TEXT_ASSIGNMENT = re.compile(
        rf"{_CREDENTIAL_FIELD}(?:{_QUOTED}|{_BARE}{_VALUE_END})",
        re.IGNORECASE | re.VERBOSE,
    )
    SOURCE_REFERENCE = re.compile(
        _CREDENTIAL_FIELD + r"(?P<name>[a-z_]\w*(?:\.[a-z_]\w*)+|[a-z]+(?:_[a-z]+)+)\b",
        re.IGNORECASE,
    )
    BEARER = re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._+/=-]{8,}")
    PRIVATE_KEY_BEGIN = re.compile(
        r"-----BEGIN (?P<kind>(?:[A-Z0-9]+ )*PRIVATE KEY)-----[ \t]*(?=\r?$)", re.MULTILINE,
    )
    PRIVATE_KEY_PAYLOAD = re.compile(
        r"(?:\r?\n(?:[ \t]*\r?\n)*[ \t]*(?:>[ \t]*)*"
        r"(?:[A-Za-z0-9+/]{16,}={0,2}|(?:Proc-Type|DEK-Info):[^\r\n]*)[ \t]*(?=\r?$))+",
        re.MULTILINE,
    )
    TEXT_SUFFIXES = {
        ".cfg", ".conf", ".ini", ".json", ".md", ".properties",
        ".rst", ".toml", ".txt", ".yaml", ".yml",
    }
    LABEL = "[REDACTED: potential secret]"
    ENTROPY_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
    ENTROPY_THRESHOLD = 3.5

    @classmethod
    def is_text_path(cls, path: str) -> bool:
        return PurePath(path).suffix.lower() in cls.TEXT_SUFFIXES

    def redact(
        self, text: str, *, detect_entropy: bool = True,
        literal_assignments: bool = False, truncated_key: bool = False,
    ) -> tuple[str, int]:
        """Replace detected secrets with redaction labels."""
        redacted_text, total = self._redact_private_keys(text, truncated_key)
        assignment = self.TEXT_ASSIGNMENT if literal_assignments else self.ASSIGNMENT
        for pattern in (assignment, self.BEARER):
            redacted_text, count = pattern.subn(self.LABEL, redacted_text)
            total += count
        if detect_entropy:
            redacted_text, extra = self._redact_high_entropy(
                redacted_text, preserve_references=not literal_assignments,
            )
            total += extra
        return redacted_text, total

    def _redact_private_keys(self, text: str, truncated_key: bool) -> tuple[str, int]:
        starts = list(self.PRIVATE_KEY_BEGIN.finditer(text))
        redacted = []
        last = 0
        count = 0
        for index, begin in enumerate(starts):
            limit = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            footer = f"-----END {begin['kind']}-----"
            footer_start = text.find(footer, begin.end(), limit)
            if footer_start >= 0:
                end = footer_start + len(footer)
            elif truncated_key:
                # The caller has bounded this text to a single side of a diff hunk.
                end = limit
            else:
                payload = self.PRIVATE_KEY_PAYLOAD.match(text, begin.end(), limit)
                if payload is None:
                    continue
                end = payload.end()

            redacted.append(text[last:begin.start()])
            redacted.append(re.sub(r"[^\r\n]+", self.LABEL, text[begin.start():end]))
            last = end
            count += 1
        if count == 0:
            return text, 0
        redacted.append(text[last:])
        return "".join(redacted), count

    def _redact_high_entropy(self, text: str, *, preserve_references: bool) -> tuple[str, int]:
        references = set()
        if preserve_references:
            for ref in self.SOURCE_REFERENCE.finditer(text):
                references.update(match.span() for match in self.ENTROPY_TOKEN_PATTERN.finditer(
                    text, ref.start(), ref.end("name"),
                ))

        redacted = []
        last = 0
        count = 0
        for match in self.ENTROPY_TOKEN_PATTERN.finditer(text):
            if match.span() in references:
                continue
            token = match.group(0)
            if self._entropy(token) >= self.ENTROPY_THRESHOLD:
                redacted.append(text[last:match.start()])
                redacted.append('[REDACTED: high entropy]')
                last = match.end()
                count += 1
        if count == 0:
            return text, 0
        redacted.append(text[last:])
        return "".join(redacted), count

    def _entropy(self, token: str) -> float:
        if not token:
            return 0.0
        freq = {}
        for ch in token:
            freq[ch] = freq.get(ch, 0) + 1
        entropy = 0.0
        length = len(token)
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)
        return entropy
