"""Unit tests for the ingestion pipeline: validation, parsing, normalization, chunking."""

import itertools
from pathlib import Path

import pytest

from app.rag.chunking import chunk_pages
from app.rag.normalize import normalize_page, strip_repeated_lines
from app.rag.parsing import parse_document
from app.rag.validation import FileKind, ValidationError, validate_file
from tests.files import LOREM, make_docx, make_macro_docx, make_pdf, make_zip_bomb_docx


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ------------------------------------------------------------------ chunking


@pytest.mark.parametrize(("size", "overlap"), [(200, 0), (500, 100), (3200, 480)])
def test_chunk_offsets_are_exact_and_never_cross_pages(size: int, overlap: int) -> None:
    pages = [LOREM * 30, "Short page.", "", LOREM * 3 + "\n\n" + LOREM * 4]
    chunks = chunk_pages(pages, size=size, overlap=overlap)
    for c in chunks:
        assert pages[c.page_number - 1][c.char_start : c.char_end] == c.content
        assert 0 < len(c.content) <= size
    assert {c.page_number for c in chunks} == {1, 2, 4}  # empty page 3 yields nothing


def test_chunks_cover_the_whole_page_with_overlap() -> None:
    text = LOREM * 40
    chunks = chunk_pages([text], size=600, overlap=120)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text.rstrip())
    for a, b in itertools.pairwise(chunks):
        assert b.char_start < a.char_end, "consecutive chunks must overlap"
        assert b.char_start > a.char_start, "chunking must always make progress"


def test_chunks_prefer_sentence_boundaries() -> None:
    chunks = chunk_pages([LOREM * 20], size=500, overlap=0)
    assert all(c.content.endswith(".") for c in chunks[:-1])


def test_invalid_chunk_settings_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_pages(["x"], size=100, overlap=100)


# ------------------------------------------------------------------ normalization


def test_normalize_fixes_hyphenation_spacing_and_unicode() -> None:
    raw = "Infor-\nmation  is\u00a0here.\r\n\r\n\n\n\ufb01nal   para\x07"
    assert normalize_page(raw) == "Information is here.\n\nfinal para"


def test_repeated_headers_and_page_numbers_are_removed() -> None:
    pages = [f"ACME Corp Confidential\n\nBody text {i}.\n\nPage {i}" for i in range(1, 7)]
    cleaned = strip_repeated_lines(pages)
    assert cleaned == [f"Body text {i}." for i in range(1, 7)]


def test_short_documents_keep_their_first_lines() -> None:
    pages = ["Title\n\nBody one", "Title\n\nBody two"]
    assert strip_repeated_lines(pages) == pages


def test_three_page_document_loses_running_header_and_page_numbers() -> None:
    # Found in browser testing: a 3-page handbook kept its header and page numbers.
    pages = [f"ACME CORP - EMPLOYEE HANDBOOK\n\nSection {i} text.\n\n{i}" for i in range(1, 4)]
    assert strip_repeated_lines(pages) == [f"Section {i} text." for i in range(1, 4)]


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("notes.pdf", b"PK\x03\x04 not a pdf", "content_mismatch"),
        ("old.doc", b"\xd0\xcf\x11\xe0", "legacy_doc"),
        ("photo.png", b"\x89PNG\r\n", "unsupported_type"),
        ("empty.pdf", b"", "empty_file"),
        ("bin.txt", b"abc\x00\x01\x02def", "content_mismatch"),
        ("fake.docx", b"%PDF-1.7 hello", "content_mismatch"),
    ],
)
def test_validation_rejects_bad_files(tmp_path: Path, name: str, data: bytes, code: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_file(_write(tmp_path, name, data), name)
    assert exc.value.code == code


def test_validation_rejects_macros_and_zip_bombs(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as macro:
        validate_file(_write(tmp_path, "m.docx", make_macro_docx()), "m.docx")
    assert macro.value.code == "macros_not_allowed"
    with pytest.raises(ValidationError) as bomb:
        validate_file(_write(tmp_path, "b.docx", make_zip_bomb_docx()), "b.docx")
    assert bomb.value.code == "suspicious_archive"


def test_validation_accepts_real_files(tmp_path: Path) -> None:
    assert validate_file(_write(tmp_path, "a.pdf", make_pdf(["hi"])), "a.pdf") is FileKind.PDF
    assert (
        validate_file(_write(tmp_path, "a.docx", make_docx([("p", "hi")])), "A.DOCX")
        is FileKind.DOCX
    )
    assert validate_file(_write(tmp_path, "a.txt", "héllo".encode()), "a.txt") is FileKind.TXT
    utf16 = "hello".encode("utf-16")
    assert validate_file(_write(tmp_path, "u.txt", utf16), "u.txt") is FileKind.TXT


# ------------------------------------------------------------------ parsing


def test_pdf_pages_are_real_pages(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "h.pdf", make_pdf(["First page about notice.", "Second page about insurance."])
    )
    parsed = parse_document(path, FileKind.PDF, max_pages=10)
    assert parsed.unit == "page"
    assert len(parsed.pages) == 2
    assert "notice" in parsed.pages[0] and "insurance" in parsed.pages[1]


def test_pdf_running_header_and_page_numbers_dropped(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "h.pdf",
        make_pdf([f"Body of page {i}." for i in range(5)], header="ACME CONFIDENTIAL"),
    )
    parsed = parse_document(path, FileKind.PDF, max_pages=10)
    assert all("ACME CONFIDENTIAL" not in p for p in parsed.pages)


def test_encrypted_and_oversized_pdfs_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as enc:
        parse_document(
            _write(tmp_path, "e.pdf", make_pdf(["secret"], password="pw")),
            FileKind.PDF,
            max_pages=10,
        )
    assert enc.value.code == "encrypted_pdf"
    with pytest.raises(ValidationError) as big:
        parse_document(_write(tmp_path, "b.pdf", make_pdf(["x"] * 4)), FileKind.PDF, max_pages=3)
    assert big.value.code == "too_many_pages"


def test_docx_sections_keep_tables_in_order(tmp_path: Path) -> None:
    data = make_docx(
        [
            ("h1", "Benefits"),
            ("p", "Health insurance covers dependents."),
            ("h1", "Leave"),
            ("p", "Twenty days."),
        ],
        table=[["Plan", "Cost"], ["Gold", "$40"]],
    )
    parsed = parse_document(_write(tmp_path, "d.docx", data), FileKind.DOCX, max_pages=10)
    assert parsed.unit == "section"
    text = "\n\n".join(parsed.pages)
    assert text.index("Benefits") < text.index("Leave") < text.index("Plan | Cost")
    assert "Gold | $40" in text


def test_long_text_is_split_into_sections(tmp_path: Path) -> None:
    body = "\n\n".join(f"Paragraph {i}. " + LOREM for i in range(80))
    parsed = parse_document(
        _write(tmp_path, "t.txt", body.encode("cp1252")), FileKind.TXT, max_pages=10
    )
    assert len(parsed.pages) > 3
    assert all(len(p) < 4000 for p in parsed.pages)
