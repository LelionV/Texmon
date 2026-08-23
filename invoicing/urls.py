from django.urls import path
from . import views

app_name = "invoicing"

urlpatterns = [
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("invoices/<int:invoice_pk>/payments/add/", views.add_payment, name="add_payment"),
    path("invoices/from-proforma/<int:proforma_pk>/", views.create_from_proforma, name="create_from_proforma"),

    path("payments/", views.PaymentListView.as_view(), name="payment_list"),

    path("receipts/", views.ReceiptListView.as_view(), name="receipt_list"),
    path("receipts/<int:pk>/", views.ReceiptDetailView.as_view(), name="receipt_detail"),
    path("receipts/<int:pk>/pdf/", views.receipt_pdf, name="receipt_pdf"),
]
