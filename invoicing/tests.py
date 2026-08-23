from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from masters.models import Client, Currency, PaymentTerm
from proforma.models import ProformaInvoice
from quotations.models import Quotation, QuotationItem
from .models import Invoice, Payment, Receipt

User = get_user_model()


class InvoiceCreationTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.user = User.objects.create_user(username="rep1", password="x")
        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms,
            sales_representative=self.user,
        )
        self.quotation = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.user,
        )
        QuotationItem.objects.create(
            quotation=self.quotation, description="Freight Cost", quantity=1,
            unit_price=Decimal("2500.00"), vat_percentage=Decimal("13.00"),
        )
        QuotationItem.objects.create(
            quotation=self.quotation, description="Clearance fee", quantity=2,
            unit_price=Decimal("1000.00"), vat_percentage=Decimal("13.00"),
        )
        self.quotation.submit(user=self.user)
        self.quotation.approve(user=self.user)
        self.proforma = ProformaInvoice.create_from_quotation(self.quotation, user=self.user)

    def test_cannot_invoice_non_approved_proforma(self):
        with self.assertRaises(ValidationError):
            Invoice.create_from_proforma(self.proforma, user=self.user)

    def test_invoice_created_from_approved_proforma_locks_pi(self):
        self.proforma.submit(user=self.user)
        self.proforma.approve(user=self.user)

        invoice = Invoice.create_from_proforma(self.proforma, user=self.user)

        self.assertTrue(invoice.invoice_number.startswith("INV-"))
        self.assertEqual(invoice.items.count(), 2)
        self.assertEqual(invoice.grand_total, Decimal("5085.00"))
        self.assertEqual(invoice.balance_due, Decimal("5085.00"))
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)
        self.assertEqual(invoice.due_date, invoice.date + __import__("datetime").timedelta(days=30))

        self.proforma.refresh_from_db()
        self.assertEqual(self.proforma.status, ProformaInvoice.Status.CONVERTED)
        self.assertTrue(self.proforma.is_locked)

        self.quotation.refresh_from_db()
        self.assertTrue(self.quotation.is_locked)

    def test_cannot_invoice_same_proforma_twice(self):
        self.proforma.submit(user=self.user)
        self.proforma.approve(user=self.user)
        Invoice.create_from_proforma(self.proforma, user=self.user)
        with self.assertRaises(ValidationError):
            Invoice.create_from_proforma(self.proforma, user=self.user)


class PaymentAndReceiptTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.user = User.objects.create_user(username="fin1", password="x")
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)
        self.quotation = Quotation.objects.create(client=self.client_obj, currency=self.usd, payment_terms=self.terms)
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("1000.00"), vat_percentage=Decimal("16.00"))
        self.quotation.submit(user=self.user)
        self.quotation.approve(user=self.user)
        self.proforma = ProformaInvoice.create_from_quotation(self.quotation, user=self.user)
        self.proforma.submit(user=self.user)
        self.proforma.approve(user=self.user)
        self.invoice = Invoice.create_from_proforma(self.proforma, user=self.user)
        # grand_total = 1000 + 160 = 1160.00

    def test_partial_payment_updates_balance_and_status(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal("500.00"), created_by=self.user)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("500.00"))
        self.assertEqual(self.invoice.balance_due, Decimal("660.00"))
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIALLY_PAID)

    def test_full_payment_marks_invoice_paid(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal("1160.00"), created_by=self.user)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance_due, Decimal("0.00"))
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertTrue(self.invoice.is_fully_paid)

    def test_cannot_overpay_invoice(self):
        with self.assertRaises(ValidationError):
            Payment.objects.create(invoice=self.invoice, amount=Decimal("2000.00"), created_by=self.user)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("0.00"))

    def test_cannot_overpay_across_multiple_payments(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal("700.00"), created_by=self.user)
        with self.assertRaises(ValidationError):
            Payment.objects.create(invoice=self.invoice, amount=Decimal("500.00"), created_by=self.user)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("700.00"))

    def test_payment_amount_must_be_positive(self):
        with self.assertRaises(ValidationError):
            Payment.objects.create(invoice=self.invoice, amount=Decimal("0.00"), created_by=self.user)
        with self.assertRaises(ValidationError):
            Payment.objects.create(invoice=self.invoice, amount=Decimal("-10.00"), created_by=self.user)

    def test_receipt_auto_created_with_payment(self):
        payment = Payment.objects.create(invoice=self.invoice, amount=Decimal("400.00"), created_by=self.user)
        self.assertTrue(Receipt.objects.filter(payment=payment).exists())
        receipt = payment.receipt
        self.assertTrue(receipt.receipt_number.startswith("RCPT-"))
        self.assertEqual(receipt.amount, Decimal("400.00"))

    def test_multiple_payments_each_get_own_receipt(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal("400.00"), created_by=self.user)
        Payment.objects.create(invoice=self.invoice, amount=Decimal("760.00"), created_by=self.user)
        self.assertEqual(Receipt.objects.filter(invoice=self.invoice).count(), 2)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)


class InvoicingViewTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)

        perms = Permission.objects.filter(content_type__app_label__in=["quotations", "proforma", "invoicing"])
        self.finance_group = Group.objects.create(name="Finance Officer")
        self.finance_group.permissions.add(*perms)
        self.finance_user = User.objects.create_user(username="fin1", password="pass1234")
        self.finance_user.groups.add(self.finance_group)

        self.viewer_group = Group.objects.create(name="Management Viewer")
        self.viewer_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="invoicing", codename__in=["view_invoice"],
        ))
        self.viewer = User.objects.create_user(username="viewer1", password="pass1234")
        self.viewer.groups.add(self.viewer_group)

        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)
        self.quotation = Quotation.objects.create(client=self.client_obj, currency=self.usd, payment_terms=self.terms)
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("1000.00"))
        self.quotation.submit(user=self.finance_user)
        self.quotation.approve(user=self.finance_user)
        self.proforma = ProformaInvoice.create_from_quotation(self.quotation, user=self.finance_user)
        self.proforma.submit(user=self.finance_user)
        self.proforma.approve(user=self.finance_user)

    def test_create_invoice_via_view(self):
        self.client.login(username="fin1", password="pass1234")
        resp = self.client.post(reverse("invoicing:create_from_proforma", args=[self.proforma.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_viewer_cannot_record_payment(self):
        invoice = Invoice.create_from_proforma(self.proforma, user=self.finance_user)
        self.client.login(username="viewer1", password="pass1234")
        resp = self.client.post(reverse("invoicing:add_payment", args=[invoice.pk]), {
            "payment_date": "2026-08-08", "amount": "100.00", "payment_method": "cash",
        })
        self.assertEqual(resp.status_code, 403)

    def test_record_payment_via_view_and_pdf(self):
        invoice = Invoice.create_from_proforma(self.proforma, user=self.finance_user)
        self.client.login(username="fin1", password="pass1234")
        resp = self.client.post(reverse("invoicing:add_payment", args=[invoice.pk]), {
            "payment_date": "2026-08-08", "amount": "500.00", "payment_method": "bank_transfer",
        })
        self.assertEqual(resp.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_amount, Decimal("500.00"))

        receipt = Receipt.objects.get(invoice=invoice)
        resp = self.client.get(reverse("invoicing:receipt_pdf", args=[receipt.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_invoice_pdf(self):
        invoice = Invoice.create_from_proforma(self.proforma, user=self.finance_user)
        self.client.login(username="fin1", password="pass1234")
        resp = self.client.get(reverse("invoicing:invoice_pdf", args=[invoice.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
