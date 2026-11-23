"""Text extraction. Output is a list of "pages":
- PDF: real pages (page numbers are exact and safe to cite).
- DOCX/TXT: Word and text files have no stable pages, so we create *sections* at headings or
  every ~3000 characters. Citations say "section N", never an invented page number.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.rag.normalize import normalize_page, strip_repeated_lines
from app.rag.validation import FileKind, ValidationError, decode_text

SECTION_TARGET_CHARS = 3000


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[str]
    unit: Literal["page", "section"]

    @property
    def total_chars(self) -> int:
        return sum(len(p) for p in self.pages)


def parse_document(path: Path, kind: FileKind, *, max_pages: int) -> ParsedDocument:
    if kind is FileKind.PDF:
        return _parse_pdf(path, max_pages)
    if kind is FileKind.DOCX:
        return ParsedDocument(_sections(_docx_blocks(path)), "section")
    return ParsedDocument(_sections(_text_blocks(decode_text(path))), "section")


# ------------------------------------------------------------------ PDF


def _parse_pdf(path: Path, max_pages: int) -> ParsedDocument:
    import pymupdf  # imported lazily: ~50 MB, only needed by the worker

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ValidationError(
            "corrupt_file", "This PDF appears to be damaged and can't be opened."
        ) from exc
    with doc:
        if doc.needs_pass:
            raise ValidationError(
                "encrypted_pdf",
                "This PDF is password-protected. Remove the password and upload it again.",
            )
        if doc.page_count > max_pages:
            raise ValidationError(
                "too_many_pages", f"This PDF has {doc.page_count} pages; the limit is {max_pages}."
            )
        pages = []
        for index in range(doc.page_count):
            page = doc[index]
            # "blocks" keeps paragraphs together; sort=True gives natural reading order.
            blocks = page.get_text("blocks", sort=True)
            paragraphs = [b[4].replace("\n", " ") for b in blocks if b[6] == 0]  # 0 = text block
            pages.append("\n\n".join(paragraphs))
    pages = strip_repeated_lines(pages)
    return ParsedDocument([normalize_page(p) for p in pages], "page")


# ------------------------------------------------------------------ DOCX / TXT


@dataclass(frozen=True)
class _Block:
    text: str
    is_heading: bool = False


def _docx_blocks(path: Path) -> Iterator[_Block]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ValidationError("corrupt_file", "This Word document appears to be damaged.") from exc

    # Walk the body in document order so tables stay next to the text that introduces them.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, document)
            text = para.text.strip()
            if text:
                style = (para.style.name if para.style is not None else "") or ""
                yield _Block(text, is_heading=style.lower().startswith(("heading", "title")))
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                # merged cells repeat their text; drop consecutive duplicates
                deduped = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
                if deduped:
                    yield _Block(" | ".join(deduped))


def _text_blocks(text: str) -> Iterator[_Block]:
    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        para = " ".join(para.split("\n")).strip()
        if para:
            # Markdown-ish headings in plain text help sectioning too.
            yield _Block(para.lstrip("#").strip(), is_heading=para.startswith("#"))


def _sections(blocks: Iterator[_Block]) -> list[str]:
    sections: list[list[str]] = [[]]
    size = 0
    for block in blocks:
        starts_new = sections[-1] and (
            size >= SECTION_TARGET_CHARS or (block.is_heading and size >= SECTION_TARGET_CHARS // 2)
        )
        if starts_new:
            sections.append([])
            size = 0
        sections[-1].append(block.text)
        size += len(block.text) + 2
    return [normalize_page("\n\n".join(s)) for s in sections if s]
