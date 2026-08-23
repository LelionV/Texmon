from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from masters.models import Currency, PaymentTerm, Supplier
from .models import Expense, ExpenseCategory, SupplierPayment

User = get_user_model()


class ExpenseModelTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.category = ExpenseCategory.objects.create(name="Transport", category_type=ExpenseCategory.CategoryType.OPERATIONS)
        self.supplier = Supplier.objects.create(company_name="Fuel Co", currency=self.usd, payment_terms=self.terms)
        self.user = User.objects.create_user(username="acct1", password="x")

    def _make_expense(self, amount="1000.00", vat="16.00"):
        return Expense.objects.create(
            category=self.category, supplier=self.supplier, description="Diesel refill",
            amount=Decimal(amount), currency=self.usd, vat_percentage=Decimal(vat),
        )

    def test_expense_number_auto_generated(self):
        e1 = self._make_expense()
        e2 = self._make_expense()
        self.assertTrue(e1.expense_number.startswith("EXP-"))
        self.assertNotEqual(e1.expense_number, e2.expense_number)

    def test_vat_and_total_amount(self):
        e = self._make_expense(amount="1000.00", vat="16.00")
        self.assertEqual(e.vat_amount, Decimal("160.00"))
        self.assertEqual(e.total_amount, Decimal("1160.00"))

    def test_workflow_transitions(self):
        e = self._make_expense()
        with self.assertRaises(ValidationError):
            e.approve(user=self.user)
        e.submit(user=self.user)
        self.assertEqual(e.status, Expense.Status.SUBMITTED)
        e.approve(user=self.user)
        self.assertEqual(e.status, Expense.Status.APPROVED)
        self.assertEqual(e.approved_by, self.user)

    def test_reject_and_revert(self):
        e = self._make_expense()
        e.submit(user=self.user)
        e.reject(user=self.user)
        self.assertEqual(e.status, Expense.Status.REJECTED)
        e.revert_to_draft(user=self.user)
        self.assertEqual(e.status, Expense.Status.DRAFT)
        self.assertTrue(e.is_editable)

    def test_category_type_examples(self):
        admin_cat = ExpenseCategory.objects.create(name="Rent", category_type=ExpenseCategory.CategoryType.ADMINISTRATION)
        self.assertEqual(admin_cat.category_type, "administration")
        self.assertEqual(self.category.category_type, "operations")


class SupplierPaymentTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.category = ExpenseCategory.objects.create(name="Transport", category_type=ExpenseCategory.CategoryType.OPERATIONS)
        self.supplier = Supplier.objects.create(company_name="Fuel Co", currency=self.usd, payment_terms=self.terms)
        self.user = User.objects.create_user(username="acct1", password="x")
        self.expense = Expense.objects.create(
            category=self.category, supplier=self.supplier, description="Diesel refill",
            amount=Decimal("1000.00"), currency=self.usd, vat_percentage=Decimal("16.00"),
        )
        # total_amount = 1160.00

    def test_cannot_pay_unapproved_expense(self):
        with self.assertRaises(ValidationError):
            SupplierPayment.objects.create(
                expense=self.expense, supplier=self.supplier, amount=Decimal("100.00"), created_by=self.user,
            )

    def test_payment_against_approved_expense(self):
        self.expense.submit(user=self.user)
        self.expense.approve(user=self.user)
        SupplierPayment.objects.create(
            expense=self.expense, supplier=self.supplier, amount=Decimal("500.00"), created_by=self.user,
        )
        self.assertEqual(self.expense.paid_amount, Decimal("500.00"))
        self.assertEqual(self.expense.balance_due, Decimal("660.00"))

    def test_cannot_overpay_supplier(self):
        self.expense.submit(user=self.user)
        self.expense.approve(user=self.user)
        SupplierPayment.objects.create(expense=self.expense, supplier=self.supplier, amount=Decimal("700.00"), created_by=self.user)
        with self.assertRaises(ValidationError):
            SupplierPayment.objects.create(expense=self.expense, supplier=self.supplier, amount=Decimal("500.00"), created_by=self.user)
        self.assertEqual(self.expense.paid_amount, Decimal("700.00"))

    def test_supplier_autofilled_from_expense(self):
        self.expense.submit(user=self.user)
        self.expense.approve(user=self.user)
        payment = SupplierPayment.objects.create(expense=self.expense, amount=Decimal("200.00"), created_by=self.user)
        self.assertEqual(payment.supplier_id, self.supplier.id)

    def test_cannot_pay_expense_with_no_supplier(self):
        expense_no_supplier = Expense.objects.create(
            category=self.category, description="Salaries", amount=Decimal("1000.00"),
            currency=self.usd,
        )
        expense_no_supplier.submit(user=self.user)
        expense_no_supplier.approve(user=self.user)
        with self.assertRaises(ValidationError):
            SupplierPayment.objects.create(
                expense=expense_no_supplier, amount=Decimal("100.00"), created_by=self.user,
            )
        self.assertEqual(SupplierPayment.objects.filter(expense=expense_no_supplier).count(), 0)


class ExpenseViewTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.category = ExpenseCategory.objects.create(name="Rent", category_type=ExpenseCategory.CategoryType.ADMINISTRATION)

        perms = Permission.objects.filter(content_type__app_label="expenses")
        self.accountant_group = Group.objects.create(name="Accountant")
        self.accountant_group.permissions.add(*perms)
        self.accountant = User.objects.create_user(username="acct1", password="pass1234")
        self.accountant.groups.add(self.accountant_group)

        self.viewer_group = Group.objects.create(name="Management Viewer")
        self.viewer_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="expenses", codename="view_expense",
        ))
        self.viewer = User.objects.create_user(username="viewer1", password="pass1234")
        self.viewer.groups.add(self.viewer_group)

    def test_list_requires_login(self):
        resp = self.client.get(reverse("expenses:expense_list"))
        self.assertEqual(resp.status_code, 302)

    def test_create_expense_via_view(self):
        self.client.login(username="acct1", password="pass1234")
        resp = self.client.post(reverse("expenses:expense_create"), {
            "category": self.category.id, "date": "2026-08-08", "description": "Office rent",
            "amount": "500.00", "currency": self.usd.id, "vat_percentage": "0.00",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Expense.objects.count(), 1)

    def test_viewer_cannot_create_expense(self):
        self.client.login(username="viewer1", password="pass1234")
        resp = self.client.get(reverse("expenses:expense_create"))
        self.assertEqual(resp.status_code, 403)

    def test_full_workflow_via_views(self):
        expense = Expense.objects.create(
            category=self.category, description="Utility bill", amount=Decimal("300.00"), currency=self.usd,
        )
        self.client.login(username="acct1", password="pass1234")
        self.client.post(reverse("expenses:expense_submit", args=[expense.pk]))
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.SUBMITTED)
        self.client.post(reverse("expenses:expense_approve", args=[expense.pk]))
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.APPROVED)

    def test_payment_view_rejects_expense_with_no_supplier_gracefully(self):
        expense = Expense.objects.create(
            category=self.category, description="Salaries", amount=Decimal("1000.00"), currency=self.usd,
        )
        expense.submit(user=self.accountant)
        expense.approve(user=self.accountant)
        self.client.login(username="acct1", password="pass1234")
        resp = self.client.post(reverse("expenses:add_supplier_payment", args=[expense.pk]), {
            "amount": "100.00", "payment_date": "2026-08-08",
        })
        self.assertEqual(resp.status_code, 302)  # graceful redirect, not a 500
        from .models import SupplierPayment
        self.assertEqual(SupplierPayment.objects.filter(expense=expense).count(), 0)
