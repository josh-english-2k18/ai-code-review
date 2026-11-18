import json
import re


def inline_code(value: str, *, table_cell: bool = False) -> str:
    """Display a path or code fragment without breaking its Markdown container."""
    escaped = json.dumps(value, ensure_ascii=False)[1:-1]
    escaped = escaped.encode("utf-8", errors="backslashreplace").decode("utf-8")
    if table_cell:
        escaped = escaped.replace("|", r"\|")
    runs = re.findall(r"`+", escaped)
    fence = "`" * (max(map(len, runs), default=0) + 1)
    if runs or escaped != escaped.strip():
        return f"{fence} {escaped} {fence}"
    return f"{fence}{escaped}{fence}"
