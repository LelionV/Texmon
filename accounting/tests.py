from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from invoicing.models import Invoice, Payment
from masters.models import Client, Currency, PaymentTerm
from proforma.models import ProformaInvoice
from quotations.models import Quotation, QuotationItem
from .models import LedgerEntry, StatementOfAccount

User = get_user_model()


class LedgerAutoPostingTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.user = User.objects.create_user(username="acct1", password="x")
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)
        self.quotation = Quotation.objects.create(client=self.client_obj, currency=self.usd, payment_terms=self.terms)
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("1000.00"), vat_percentage=Decimal("16.00"))
        self.quotation.submit(user=self.user)
        self.quotation.approve(user=self.user)
        self.proforma = ProformaInvoice.create_from_quotation(self.quotation, user=self.user)
        self.proforma.submit(user=self.user)
        self.proforma.approve(user=self.user)
        # grand_total = 1160.00

    def test_invoice_creates_debit_ledger_entry(self):
        self.assertEqual(LedgerEntry.objects.filter(client=self.client_obj).count(), 0)
        invoice = Invoice.create_from_proforma(self.proforma, user=self.user)
        entries = LedgerEntry.objects.filter(client=self.client_obj)
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.entry_type, LedgerEntry.EntryType.INVOICE)
        self.assertEqual(entry.debit, Decimal("1160.00"))
        self.assertEqual(entry.credit, Decimal("0.00"))
        self.assertEqual(entry.running_balance, Decimal("1160.00"))

    def test_payment_creates_credit_ledger_entry_and_updates_balance(self):
        invoice = Invoice.create_from_proforma(self.proforma, user=self.user)
        Payment.objects.create(invoice=invoice, amount=Decimal("500.00"), created_by=self.user)
        entries = LedgerEntry.objects.filter(client=self.client_obj).order_by("id")
        self.assertEqual(entries.count(), 2)
        payment_entry = entries.last()
        self.assertEqual(payment_entry.entry_type, LedgerEntry.EntryType.PAYMENT)
        self.assertEqual(payment_entry.credit, Decimal("500.00"))
        self.assertEqual(payment_entry.running_balance, Decimal("660.00"))

    def test_multiple_clients_ledgers_dont_interfere(self):
        other_client = Client.objects.create(company_name="Beta Ltd", currency=self.usd, payment_terms=self.terms)
        other_q = Quotation.objects.create(client=other_client, currency=self.usd, payment_terms=self.terms)
        QuotationItem.objects.create(quotation=other_q, description="Handling", quantity=1, unit_price=Decimal("200.00"))
        other_q.submit(user=self.user)
        other_q.approve(user=self.user)
        other_pi = ProformaInvoice.create_from_quotation(other_q, user=self.user)
        other_pi.submit(user=self.user)
        other_pi.approve(user=self.user)
        Invoice.create_from_proforma(other_pi, user=self.user)

        Invoice.create_from_proforma(self.proforma, user=self.user)

        self.assertEqual(LedgerEntry.objects.filter(client=self.client_obj).first().running_balance, Decimal("1160.00"))
        self.assertEqual(LedgerEntry.objects.filter(client=other_client).first().running_balance, Decimal("200.00"))


class StatementOfAccountTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.user = User.objects.create_user(username="acct1", password="x")
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)
        self.quotation = Quotation.objects.create(client=self.client_obj, currency=self.usd, payment_terms=self.terms)
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("500000.00"))
        self.quotation.submit(user=self.user)
        self.quotation.approve(user=self.user)
        self.proforma = ProformaInvoice.create_from_quotation(self.quotation, user=self.user)
        self.proforma.submit(user=self.user)
        self.proforma.approve(user=self.user)
        self.invoice = Invoice.create_from_proforma(self.proforma, user=self.user)
        Payment.objects.create(invoice=self.invoice, amount=Decimal("200000.00"), created_by=self.user)
        # matches the spec's worked example: Invoice 500,000 / Payment 200,000 / Balance 300,000

    def test_statement_matches_spec_example(self):
        import datetime
        statement = StatementOfAccount.generate(
            client=self.client_obj,
            date_from=datetime.date(2020, 1, 1),
            date_to=timezone_today(),
            user=self.user,
        )
        self.assertTrue(statement.statement_number.startswith("STMT-"))
        self.assertEqual(statement.opening_balance, Decimal("0.00"))
        self.assertEqual(statement.closing_balance, Decimal("300000.00"))
        lines = list(statement.get_lines())
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].debit, Decimal("500000.00"))
        self.assertEqual(lines[1].credit, Decimal("200000.00"))

    def test_statement_pdf(self):
        import datetime
        perms = Permission.objects.filter(content_type__app_label="accounting")
        group = Group.objects.create(name="Finance Officer")
        group.permissions.add(*perms)
        self.user.groups.add(group)
        statement = StatementOfAccount.generate(
            client=self.client_obj, date_from=datetime.date(2020, 1, 1), date_to=timezone_today(), user=self.user,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("accounting:statement_pdf", args=[statement.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")


def timezone_today():
    from django.utils import timezone
    return timezone.localdate()


class StatementViewTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.client_obj = Client.objects.create(company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms)

        perms = Permission.objects.filter(content_type__app_label="accounting")
        self.finance_group = Group.objects.create(name="Finance Officer")
        self.finance_group.permissions.add(*perms)
        self.finance_user = User.objects.create_user(username="fin1", password="pass1234")
        self.finance_user.groups.add(self.finance_group)

        self.viewer_group = Group.objects.create(name="Management Viewer")
        self.viewer_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="accounting", codename="view_statementofaccount",
        ))
        self.viewer = User.objects.create_user(username="viewer1", password="pass1234")
        self.viewer.groups.add(self.viewer_group)

    def test_viewer_cannot_generate_statement(self):
        self.client.login(username="viewer1", password="pass1234")
        resp = self.client.get(reverse("accounting:statement_generate"))
        self.assertEqual(resp.status_code, 403)

    def test_finance_officer_can_generate_statement(self):
        self.client.login(username="fin1", password="pass1234")
        resp = self.client.post(reverse("accounting:statement_generate"), {
            "client": self.client_obj.id, "date_from": "2026-01-01", "date_to": "2026-12-31",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(StatementOfAccount.objects.count(), 1)

    def test_invalid_date_range_rejected(self):
        self.client.login(username="fin1", password="pass1234")
        resp = self.client.post(reverse("accounting:statement_generate"), {
            "client": self.client_obj.id, "date_from": "2026-12-31", "date_to": "2026-01-01",
        })
        self.assertEqual(resp.status_code, 200)  # re-rendered with form errors
        self.assertEqual(StatementOfAccount.objects.count(), 0)
