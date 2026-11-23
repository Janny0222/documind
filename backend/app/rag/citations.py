"""Citation verification and the streaming follow-ups splitter.

The model writes markers like [S2]. Only markers that point at a source we actually retrieved
for *this* answer survive; anything else (hallucinated [S9], made-up formats) is removed from the
text before it's stored. The UI therefore never shows a citation that doesn't map to a real chunk.
"""

import re
from dataclasses import dataclass

from app.rag.prompts import FOLLOW_UPS_MARKER, NOT_FOUND
from app.rag.retrieval import RetrievedChunk

# [S1] or [S1, S2] or [S1; S3]
_GROUP = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_ANY_MARKER = re.compile(r"\[\s*S\d+[^\]]*\]")


@dataclass
class VerifiedAnswer:
    text: str
    used: list[tuple[str, RetrievedChunk]]  # (marker, chunk) in order of first use
    invalid_markers: int
    not_found: bool


def verify_citations(raw: str, sources: list[RetrievedChunk]) -> VerifiedAnswer:
    valid = {f"S{i}": c for i, c in enumerate(sources, start=1)}
    used: dict[str, RetrievedChunk] = {}
    invalid = 0

    def replace_group(m: re.Match[str]) -> str:
        nonlocal invalid
        kept = []
        for marker in re.split(r"\s*[,;]\s*", m.group(1)):
            if marker in valid:
                kept.append(f"[{marker}]")
                used.setdefault(marker, valid[marker])
            else:
                invalid += 1
        return "".join(kept)  # normalized: [S1, S2] -> [S1][S2]

    text = _GROUP.sub(replace_group, raw)

    def drop_malformed(m: re.Match[str]) -> str:
        nonlocal invalid
        if re.fullmatch(r"\[S\d+\]", m.group(0)):
            return m.group(0)
        invalid += 1
        return ""

    text = _ANY_MARKER.sub(drop_malformed, text)
    # Tidy spaces left by removed markers.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text).strip()
    not_found = text.startswith(NOT_FOUND[:30]) and not used
    return VerifiedAnswer(text, list(used.items()), invalid, not_found)


class FollowUpSplitter:
    """Streams answer text but holds back the follow-ups section, which arrives after a marker
    line. Text that *might* be the start of the marker is buffered until it's certain."""

    def __init__(self) -> None:
        self.answer = ""
        self._tail = ""
        self._suggestions_raw: str | None = None

    def feed(self, delta: str) -> str:
        if self._suggestions_raw is not None:
            self._suggestions_raw += delta
            return ""
        buf = self._tail + delta
        idx = buf.find(FOLLOW_UPS_MARKER)
        if idx != -1:
            visible, self._suggestions_raw = buf[:idx], buf[idx + len(FOLLOW_UPS_MARKER) :]
            self._tail = ""
        else:
            # Keep back the longest suffix that is a prefix of the marker.
            keep = 0
            for n in range(min(len(FOLLOW_UPS_MARKER) - 1, len(buf)), 0, -1):
                if FOLLOW_UPS_MARKER.startswith(buf[-n:]):
                    keep = n
                    break
            visible, self._tail = buf[: len(buf) - keep], buf[len(buf) - keep :]
        self.answer += visible
        return visible

    def finish(self) -> tuple[str, list[str]]:
        """Returns (remaining visible text, follow-up questions)."""
        rest = self._tail if self._suggestions_raw is None else ""
        self.answer += rest
        self._tail = ""
        suggestions = []
        for line in (self._suggestions_raw or "").splitlines():
            q = line.strip().lstrip("-*0123456789. ").strip()
            if 5 <= len(q) <= 200:
                suggestions.append(q)
        return rest, suggestions[:3]
