"""
Template context processors shared across the whole site.

company_info injects the singleton CompanyInfo record (masters app, added in
Phase 2) into every template so base_document.html / the sidebar / the
navbar can render the logo, name and address without every view having to
fetch it manually. Phase 1 has no masters app yet, so this degrades to None
gracefully; Phase 2 will make it real.
"""


def company_info(request):
    try:
        from masters.models import CompanyInfo
        company = CompanyInfo.objects.first()
    except Exception:
        company = None
    return {"company_info": company}
