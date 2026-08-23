from django.urls import path
from . import views

app_name = "proforma"

urlpatterns = [
    path("", views.ProformaListView.as_view(), name="list"),
    path("<int:pk>/", views.ProformaDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProformaUpdateView.as_view(), name="update"),
    path("<int:pk>/submit/", views.submit_proforma, name="submit"),
    path("<int:pk>/approve/", views.approve_proforma, name="approve"),
    path("<int:pk>/reject/", views.reject_proforma, name="reject"),
    path("<int:pk>/revert/", views.revert_proforma, name="revert"),
    path("<int:pk>/pdf/", views.proforma_pdf, name="pdf"),
    path("from-quotation/<int:quotation_pk>/", views.create_from_quotation, name="create_from_quotation"),
]
