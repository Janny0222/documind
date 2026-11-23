"""Page-aware chunking with exact character offsets.

- Chunks never cross a page/section boundary, so every chunk has exactly one page number.
- `char_start`/`char_end` index into the stored page text, so the preview can highlight the
  exact passage a citation points to.
- Breaks prefer paragraph ends, then sentence ends, then spaces; consecutive chunks overlap so
  a fact split across a boundary is still retrievable.
"""

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s")


@dataclass(frozen=True)
class Chunk:
    page_number: int  # 1-based
    char_start: int
    char_end: int
    content: str

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.content) // 4)


def chunk_pages(pages: list[str], *, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Need size > 0 and 0 <= overlap < size")
    chunks: list[Chunk] = []
    for number, text in enumerate(pages, start=1):
        chunks.extend(_chunk_page(text, number, size, overlap))
    return chunks


def _chunk_page(text: str, page_number: int, size: int, overlap: int) -> list[Chunk]:
    out: list[Chunk] = []
    start = _skip_space(text, 0)
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            end = _best_break(text, start, end, size)
        content = text[start:end].strip()
        if content:
            # Recompute exact offsets of the stripped content.
            lead = len(text[start:end]) - len(text[start:end].lstrip())
            c_start = start + lead
            out.append(Chunk(page_number, c_start, c_start + len(content), content))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        # Start the overlap at a word boundary so chunks don't begin mid-word.
        space = text.find(" ", nxt, end)
        start = _skip_space(text, space + 1 if space != -1 else nxt)
    return out


def _best_break(text: str, start: int, end: int, size: int) -> int:
    floor = start + int(size * 0.6)  # never produce tiny chunks just to hit a nice boundary
    para = text.rfind("\n\n", floor, end)
    if para != -1:
        return para
    sentence_end = -1
    for m in _SENTENCE_END.finditer(text, floor, end):
        sentence_end = m.end()
    if sentence_end != -1:
        return sentence_end
    space = text.rfind(" ", floor, end)
    return space if space != -1 else end


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i
