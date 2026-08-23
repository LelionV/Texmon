from django.urls import path
from . import api, views

app_name = "masters"

urlpatterns = [
    path("api/clients/<int:pk>/autofill/", api.client_autofill, name="client_autofill"),
    path("api/items/<int:pk>/autofill/", api.item_autofill, name="item_autofill"),

    path("", views.MasterHubView.as_view(), name="hub"),
    path("<slug:slug>/", views.MasterListView.as_view(), name="list"),
    path("<slug:slug>/new/", views.MasterCreateView.as_view(), name="create"),
    path("<slug:slug>/<int:pk>/edit/", views.MasterUpdateView.as_view(), name="update"),
    path("<slug:slug>/<int:pk>/delete/", views.MasterDeleteView.as_view(), name="delete"),
    path("<slug:slug>/<int:pk>/history/", views.MasterHistoryView.as_view(), name="history"),
    path("reference-documents/<int:pk>/usage/", views.ReferenceDocumentUsageView.as_view(), name="reference_document_usage"),

    path("singletons/company-info/", views.CompanyInfoUpdateView.as_view(), name="company_info"),
    path("singletons/company-info/history/", views.CompanyInfoHistoryView.as_view(), name="company_info_history"),
    path("singletons/document-settings/", views.DocumentSettingsUpdateView.as_view(), name="document_settings"),
    path("singletons/document-settings/history/", views.DocumentSettingsHistoryView.as_view(), name="document_settings_history"),
]
