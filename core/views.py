from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render

from core.pdf import render_pdf, get_logo_base64

from .models import Quotation
# from activity.models import UserActivityLog
from masters.models import CompanyInfo


@login_required
def quotation_pdf(request, pk):
    """
    Generate a quotation PDF.

    quotation_pdf.html extends documents/base_document.html.
    The company logo is passed to the base template as a
    Base64 data URI.
    """

    quotation = get_object_or_404(
        Quotation.objects.select_related(
            "client",
            "currency",
            "payment_terms",
            "reference_document",
            "created_by",
            "approved_by",
        ),
        pk=pk,
    )

    # ---------------------------------------------------------
    # Company information
    # ---------------------------------------------------------

    company = CompanyInfo.get_solo()

    # ---------------------------------------------------------
    # Company logo
    # ---------------------------------------------------------

    logo_base64 = get_logo_base64()

    # Optional debugging
    print("PDF LOGO EXISTS:", logo_base64 is not None)
    print("PDF LOGO LENGTH:", len(logo_base64 or ""))

    # ---------------------------------------------------------
    # Document context
    # ---------------------------------------------------------

    context = {
        "quotation": quotation,

        "items": quotation.items.select_related(
            "item"
        ),

        "company_info": company,

        "document_number": quotation.quotation_number,

        "reference_number": (
            quotation.reference_document.name
            if quotation.reference_document_id
            else ""
        ),

        "document_date": quotation.date,

        "customer": quotation.client,

        "subtotal": quotation.subtotal,

        "vat_total": quotation.vat_total,

        "grand_total": quotation.grand_total,

        "currency_symbol": (
            quotation.currency.symbol
            if quotation.currency
            else "$"
        ),

        "currency_code": (
            quotation.currency.code
            if quotation.currency
            else "KES"
        ),

        "doc_tag": (
            quotation.get_shipment_type_display()
            if quotation.shipment_type
            else "QUOTATION"
        ),

        "prepared_by": quotation.created_by,

        "approved_by": quotation.approved_by,

        # -----------------------------------------------------
        # IMPORTANT:
        # This is consumed by base_document.html
        # -----------------------------------------------------

        "logo_base64": logo_base64,
    }

    # ---------------------------------------------------------
    # Render quotation_pdf.html
    #
    # quotation_pdf.html extends:
    #
    # documents/base_document.html
    #
    # Therefore the base template receives logo_base64.
    # ---------------------------------------------------------

    html = render(
        request,
        "quotations/quotation_pdf.html",
        context,
    )

    html_string = html.content.decode("utf-8")

    # ---------------------------------------------------------
    # Generate PDF
    # ---------------------------------------------------------

    pdf_bytes = render_pdf(
        html_string=html_string,
    )

    # ---------------------------------------------------------
    # Activity log
    # ---------------------------------------------------------

    UserActivityLog.log(
        request.user,
        UserActivityLog.Action.PRINT,
        f"Downloaded PDF for {quotation.quotation_number}",
        obj=quotation,
        request=request,
    )

    # ---------------------------------------------------------
    # Response
    # ---------------------------------------------------------

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{quotation.quotation_number}.pdf"'
    )

    return response

