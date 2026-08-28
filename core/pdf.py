"""
Shared PDF-rendering helper used by every app's *_pdf view.

Uses Playwright with Chromium to render HTML/CSS into PDF.

Playwright provides consistent, modern HTML/CSS rendering across
Windows development environments and Linux-based production
environments such as Render.
"""

from playwright.sync_api import sync_playwright


def render_pdf(html_string: str, base_url: str | None = None) -> bytes:
    """Render an HTML string to PDF bytes. Raises RuntimeError on failure."""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            page = browser.new_page()

            if base_url:
                page.goto(base_url, wait_until="networkidle")

            else:
                page.set_content(
                    html_string,
                    wait_until="networkidle",
                )

            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={
                    "top": "15mm",
                    "right": "12mm",
                    "bottom": "15mm",
                    "left": "12mm",
                },
            )

            browser.close()

            return pdf_bytes

    except Exception as exc:
        raise RuntimeError(f"PDF generation failed: {exc}") from exc