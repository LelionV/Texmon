"""
Shared PDF-rendering helper used by every app's *_pdf view.

We use xhtml2pdf (pure Python, ships its own PDF writer) instead of
WeasyPrint. WeasyPrint depends on system GTK/Pango/Cairo libraries
(libgobject-2.0-0 and friends); on Windows in particular those aren't
present unless GTK is separately installed, which produces exactly the
"cannot load library 'gobject-2.0-0'" OSError this replaces. xhtml2pdf has
no such system dependency -- `pip install xhtml2pdf` is enough on any OS.

Trade-off: xhtml2pdf only understands a CSS 2.1-ish subset (no flexbox, no
grid, limited box-shadow/border-radius). templates/documents/base_document.html
was written with a table-based layout specifically so it renders correctly
under this engine.
"""

from io import BytesIO

from xhtml2pdf import pisa


def render_pdf(html_string: str) -> bytes:
    """Render an HTML string to PDF bytes. Raises RuntimeError on failure."""
    buffer = BytesIO()
    result = pisa.CreatePDF(src=html_string, dest=buffer)
    if result.err:
        raise RuntimeError(
            f"PDF generation failed ({result.err} error(s) reported by xhtml2pdf)."
        )
    return buffer.getvalue()
