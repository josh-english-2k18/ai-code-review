import re
import math
from typing import List

class Redactor:
    """Detects and redacts secrets and sensitive information from text."""

    SECRET_PATTERNS = [
        r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[\w-]{20,}',
        r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']?[\w-]{8,}',
        r'(?i)(token|bearer)\s*[=:]\s*["\']?[\w-]{20,}',
        r'-----BEGIN [A-Z]+ PRIVATE KEY-----',
        r'(?i)aws[_-]?(access[_-]?key|secret)',
    ]
    ENTROPY_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
    ENTROPY_THRESHOLD = 4.5

    def __init__(self):
        self.patterns = [re.compile(p) for p in self.SECRET_PATTERNS]

    def redact(self, text: str) -> tuple[str, int]:
        """Replace detected secrets with redaction labels."""
        redacted_text = text
        total = 0
        for pattern in self.patterns:
            redacted_text, count = pattern.subn('[REDACTED: potential secret]', redacted_text)
            total += count
        redacted_text, extra = self._redact_high_entropy(redacted_text)
        total += extra
        return redacted_text, total

    def _redact_high_entropy(self, text: str) -> tuple[str, int]:
        matches = list(self.ENTROPY_TOKEN_PATTERN.finditer(text))
        if not matches:
            return text, 0

        redacted = []
        last = 0
        count = 0
        for match in matches:
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
