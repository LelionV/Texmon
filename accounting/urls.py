from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    path("statements/", views.StatementListView.as_view(), name="statement_list"),
    path("statements/generate/", views.GenerateStatementView.as_view(), name="statement_generate"),
    path("statements/<int:pk>/", views.StatementDetailView.as_view(), name="statement_detail"),
    path("statements/<int:pk>/pdf/", views.statement_pdf, name="statement_pdf"),
    path("ledger/<int:client_pk>/", views.ClientLedgerView.as_view(), name="client_ledger"),
]
