import base64
import mimetypes
import os

from django.conf import settings
from django.template.loader import render_to_string

from masters.models import CompanyInfo


def get_logo_base64():
    """
    Return the company logo as a Base64 data URI.

    This is used by Playwright so the PDF does not depend on
    MEDIA_URL or an external HTTP request.
    """

    company_info = CompanyInfo.get_solo()

    if not company_info:
        print("WARNING: CompanyInfo not found.")
        return None

    if not company_info.logo:
        print("WARNING: Company logo is not configured.")
        return None

    try:
        logo_path = company_info.logo.path
    except (AttributeError, ValueError) as exc:
        print(f"WARNING: Could not resolve company logo path: {exc}")
        return None

    if not logo_path:
        print("WARNING: Company logo path is empty.")
        return None

    if not os.path.isfile(logo_path):
        print(f"WARNING: Company logo file does not exist: {logo_path}")
        return None

    try:
        mime_type, _ = mimetypes.guess_type(logo_path)

        if not mime_type:
            mime_type = "image/png"

        with open(logo_path, "rb") as image_file:
            encoded = base64.b64encode(
                image_file.read()
            ).decode("ascii")

        logo_base64 = f"data:{mime_type};base64,{encoded}"

        print(
            f"PDF LOGO: loaded successfully "
            f"({mime_type}, {len(encoded)} base64 characters)"
        )

        return logo_base64

    except OSError as exc:
        print(f"WARNING: Failed to read company logo: {exc}")
        return None


def get_pdf_context(context=None):
    """
    Add shared data required by every PDF document.
    """

    context = dict(context or {})

    company_info = CompanyInfo.get_solo()

    context["company_info"] = company_info
    context["logo_base64"] = get_logo_base64()

    return context


def render_pdf_template(request, template_name, context=None):
    """
    Render any document template with the shared PDF context,
    then convert it to PDF.
    """

    pdf_context = get_pdf_context(context)

    html_string = render_to_string(
        template_name,
        pdf_context,
        request=request,
    )

    # Debug check
    if "data:image/" in html_string:
        print("PDF HTML: Base64 image found.")
    else:
        print("WARNING: No Base64 image found in PDF HTML.")

    return render_pdf(html_string)


def render_pdf(
    html_string: str,
    base_url: str | None = None,
) -> bytes:
    """
    Render HTML to PDF using Playwright/Chromium.
    """

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()

        page = browser.new_page()

        page.set_content(
            html_string,
            wait_until="networkidle",
        )

        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
        )

        browser.close()

    return pdf_bytes