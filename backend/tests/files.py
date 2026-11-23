"""Builds real test documents on the fly (no binary fixtures in the repo)."""

import io
import zipfile

import docx
import pymupdf


def make_pdf(pages: list[str], *, password: str | None = None, header: str | None = None) -> bytes:
    doc = pymupdf.open()
    for i, text in enumerate(pages, start=1):
        page = doc.new_page()
        if header:
            page.insert_text((72, 40), header)
        if text:
            page.insert_textbox(pymupdf.Rect(72, 72, 540, 760), text, fontsize=11)
        if header:
            page.insert_text((290, 800), str(i))  # page number footer
    out = io.BytesIO()
    if password:
        doc.save(
            out,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=password + "-owner",
            user_pw=password,
        )
    else:
        doc.save(out)
    doc.close()
    return out.getvalue()


def make_docx(blocks: list[tuple[str, str]], table: list[list[str]] | None = None) -> bytes:
    """blocks: (style, text) where style is 'h1' or 'p'."""
    d = docx.Document()
    for style, text in blocks:
        if style == "h1":
            d.add_heading(text, level=1)
        else:
            d.add_paragraph(text)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def make_macro_docx() -> bytes:
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(make_docx([("p", "hello")]))) as src,
        zipfile.ZipFile(out, "w") as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("word/vbaProject.bin", b"\x00" * 64)
    return out.getvalue()


def make_zip_bomb_docx() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/padding.xml", b"\x00" * (20 * 1024 * 1024))  # compresses ~1000:1
    return out.getvalue()


LOREM = (
    "The employee handbook explains benefits, leave and conduct. "
    "Employees give thirty days written notice before resigning. "
    "Managers give sixty days notice. Health insurance covers dependents. "
)
