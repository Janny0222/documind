"""Upload validation by *content*, not by the filename or the browser's Content-Type.

A file is accepted only if its bytes match the type its extension claims:
- PDF:  starts with %PDF-
- DOCX: a real OOXML zip (word/document.xml), no macros, not a zip bomb
- TXT:  decodes as text (no binary NUL bytes)
Legacy .doc and anything else is rejected with a message that tells the user what to do.
"""

import zipfile
from enum import StrEnum
from pathlib import Path

from charset_normalizer import from_path


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


MIME = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.TXT: "text/plain",
}
EXTENSIONS = {".pdf": FileKind.PDF, ".docx": FileKind.DOCX, ".txt": FileKind.TXT}

# Zip-bomb guards for DOCX: total uncompressed size and compression ratio.
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_DOCX_RATIO = 100


class ValidationError(Exception):
    """A file the user can fix (wrong type, encrypted, too big...). `message` is shown as-is."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def kind_from_filename(filename: str) -> FileKind:
    suffix = Path(filename).suffix.lower()
    if suffix == ".doc":
        raise ValidationError(
            "legacy_doc", "Old .doc files aren't supported. Save it as .docx or PDF and try again."
        )
    kind = EXTENSIONS.get(suffix)
    if kind is None:
        raise ValidationError("unsupported_type", "Only PDF, DOCX and TXT files are supported.")
    return kind


def validate_file(path: Path, filename: str) -> FileKind:
    kind = kind_from_filename(filename)
    with path.open("rb") as f:
        head = f.read(8192)
    if not head:
        raise ValidationError("empty_file", "This file is empty.")

    if kind is FileKind.PDF:
        if b"%PDF-" not in head[:1024]:
            raise ValidationError("content_mismatch", "This file is named .pdf but isn't a PDF.")
    elif kind is FileKind.DOCX:
        _validate_docx(path)
    # NUL bytes mean binary data - unless it's UTF-16 text (which starts with a BOM).
    elif b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValidationError(
            "content_mismatch", "This file is named .txt but contains binary data."
        )
    return kind


def _validate_docx(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValidationError(
            "content_mismatch", "This file is named .docx but isn't a Word document."
        )
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise ValidationError(
                    "content_mismatch", "This file is named .docx but isn't a Word document."
                )
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise ValidationError(
                    "macros_not_allowed",
                    "Documents with macros aren't accepted. Save as a plain .docx.",
                )
            content_types = (
                zf.read("[Content_Types].xml") if "[Content_Types].xml" in names else b""
            )
            if b"macroEnabled" in content_types:
                raise ValidationError(
                    "macros_not_allowed",
                    "Documents with macros aren't accepted. Save as a plain .docx.",
                )
            total = sum(i.file_size for i in zf.infolist())
            compressed = sum(i.compress_size for i in zf.infolist()) or 1
            if total > MAX_DOCX_UNCOMPRESSED or total / compressed > MAX_DOCX_RATIO:
                raise ValidationError(
                    "suspicious_archive",
                    "This document's contents are unusually large and can't be processed.",
                )
    except zipfile.BadZipFile as exc:
        raise ValidationError("corrupt_file", "This Word document appears to be damaged.") from exc


def decode_text(path: Path) -> str:
    best = from_path(path).best()
    if best is None:
        raise ValidationError("unreadable_text", "This text file's encoding couldn't be detected.")
    return str(best)
