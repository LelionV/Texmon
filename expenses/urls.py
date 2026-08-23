from django.urls import path
from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.ExpenseListView.as_view(), name="expense_list"),
    path("new/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("<int:pk>/", views.ExpenseDetailView.as_view(), name="expense_detail"),
    path("<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="expense_update"),
    path("<int:pk>/submit/", views.submit_expense, name="expense_submit"),
    path("<int:pk>/approve/", views.approve_expense, name="expense_approve"),
    path("<int:pk>/reject/", views.reject_expense, name="expense_reject"),
    path("<int:pk>/revert/", views.revert_expense, name="expense_revert"),
    path("<int:expense_pk>/payments/add/", views.add_supplier_payment, name="add_supplier_payment"),
    path("supplier-payments/", views.SupplierPaymentListView.as_view(), name="supplier_payment_list"),
]
