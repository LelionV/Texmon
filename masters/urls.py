from django.urls import path
from . import api, views
from .views import (
    CurrencyListView,
    CurrencyCreateView,
    CurrencyUpdateView,
    CurrencyDeleteView,
)

from .views import (
    PaymentTermListView,
    PaymentTermCreateView,
    PaymentTermUpdateView,
    PaymentTermDeleteView,
)

from .views import (
    ReferenceDocumentListView,
    ReferenceDocumentDetailView,
)

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

    path(
        "currencies/",
        CurrencyListView.as_view(),
        name="currency_list",
    ),

    path(
        "currencies/create/",
        CurrencyCreateView.as_view(),
        name="currency_create",
    ),

    path(
        "currencies/<int:pk>/edit/",
        CurrencyUpdateView.as_view(),
        name="currency_edit",
    ),

    path(
        "currencies/<int:pk>/delete/",
        CurrencyDeleteView.as_view(),
        name="currency_delete",
    ),

    path(
        "payment-terms/",
        PaymentTermListView.as_view(),
        name="payment_term_list",
    ),

    path(
        "payment-terms/create/",
        PaymentTermCreateView.as_view(),
        name="payment_term_create",
    ),

    path(
        "payment-terms/<int:pk>/edit/",
        PaymentTermUpdateView.as_view(),
        name="payment_term_edit",
    ),

    path(
        "payment-terms/<int:pk>/delete/",
        PaymentTermDeleteView.as_view(),
        name="payment_term_delete",
    ),

    path(
    "reference-documents/",
    ReferenceDocumentListView.as_view(),
    name="reference_document_list",
),

path(
    "reference-documents/<int:pk>/",
    ReferenceDocumentDetailView.as_view(),
    name="reference_document_detail",
),

]
