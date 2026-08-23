from django.urls import path
from . import views

app_name = "quotations"

urlpatterns = [
    path("", views.QuotationListView.as_view(), name="list"),
    path("new/", views.QuotationCreateView.as_view(), name="create"),
    path("<int:pk>/", views.QuotationDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.QuotationUpdateView.as_view(), name="update"),
    path("<int:pk>/submit/", views.submit_quotation, name="submit"),
    path("<int:pk>/approve/", views.approve_quotation, name="approve"),
    path("<int:pk>/reject/", views.reject_quotation, name="reject"),
    path("<int:pk>/revert/", views.revert_quotation, name="revert"),
    path("<int:pk>/pdf/", views.quotation_pdf, name="pdf"),
    path("items/empty-row/", views.quotation_item_empty_row, name="item_empty_row"),
]
