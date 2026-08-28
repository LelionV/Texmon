from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False)),
    path("dashboard/", include("dashboard.urls")),
    path("masters/", include("masters.urls")),
    path("quotations/", include("quotations.urls")),
    path("proforma/", include("proforma.urls")),
    path("", include("invoicing.urls")),
    path("expenses/", include("expenses.urls")),
    path("accounting/", include("accounting.urls")),
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
