"""Text normalization. Paragraphs stay separated by a blank line ("\\n\\n"); everything else is
single-spaced, so chunk boundaries and character offsets are predictable."""

import re
import unicodedata
from collections import Counter

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_SPACES = re.compile(r"[ \t\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
_DIGITS = re.compile(r"\d+")


def normalize_page(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # "infor-\nmation" -> "information"
    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
        para = _SPACES.sub(" ", para.replace("\n", " ")).strip()
        if para:
            paragraphs.append(para)
    return "\n\n".join(paragraphs)


def strip_repeated_lines(
    pages: list[str], *, min_pages: int = 3, threshold: float = 0.6
) -> list[str]:
    """Removes running headers/footers: a first/last paragraph that repeats (ignoring digits,
    e.g. page numbers) on at least `threshold` of the pages."""
    if len(pages) < min_pages:
        return pages

    def key(paragraph: str) -> str:
        return _DIGITS.sub("#", paragraph.strip().lower())

    edges: Counter[str] = Counter()
    split_pages = [[p for p in page.split("\n\n") if p.strip()] for page in pages]
    for paras in split_pages:
        edge_keys = {key(paras[0]), key(paras[-1])} if paras else set()
        edges.update(edge_keys)
    repeated = {k for k, n in edges.items() if n >= threshold * len(pages) and len(k) < 200}
    if not repeated:
        return pages

    cleaned = []
    for paras in split_pages:
        if paras and key(paras[0]) in repeated:
            paras = paras[1:]
        if paras and key(paras[-1]) in repeated:
            paras = paras[:-1]
        cleaned.append("\n\n".join(paras))
    return cleaned
