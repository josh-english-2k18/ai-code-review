class PromptChunker:
    """Split supplemental material at line boundaries, preserving Markdown fences."""

    def __init__(self, max_tokens: int = 15000):
        self.max_chars = max_tokens * 4

    def chunk_packet(self, packet_md: str) -> list[str]:
        if len(packet_md) <= self.max_chars:
            return [packet_md]

        chunks = []
        lines = []
        size = 0
        fence = ""
        for line in packet_md.split("\n"):
            next_fence = fence
            if not fence and line.startswith("```"):
                next_fence = line
            elif fence and line.rstrip() == "```":
                next_fence = ""

            reserve_close = 4 if next_fence else 0
            line_size = len(line) + 1
            has_content = lines and lines != [fence]
            if has_content and size + line_size + reserve_close > self.max_chars and line.rstrip() != "```":
                if fence:
                    lines.append("```")
                chunks.append("\n".join(lines))
                lines = [fence] if fence else []
                size = len(fence) + 1 if fence else 0

            lines.append(line)
            size += line_size
            fence = next_fence

        if fence:
            lines.append("```")
        chunks.append("\n".join(lines))
        return [f"## Packet Chunk {i} of {len(chunks)}\n\n{chunk}" for i, chunk in enumerate(chunks, 1)]
