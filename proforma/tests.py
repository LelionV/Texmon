from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from masters.models import Client, Currency, PaymentTerm
from quotations.models import Quotation, QuotationItem
from .models import ProformaInvoice

User = get_user_model()


class ProformaCreationTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.rep = User.objects.create_user(username="rep1", password="x")
        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )
        self.quotation = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )
        QuotationItem.objects.create(
            quotation=self.quotation, description="Freight Cost", quantity=1,
            unit_price=Decimal("2500.00"), vat_percentage=Decimal("13.00"),
        )
        QuotationItem.objects.create(
            quotation=self.quotation, description="Clearance fee", quantity=2,
            unit_price=Decimal("1000.00"), vat_percentage=Decimal("13.00"),
        )

    def test_cannot_convert_non_approved_quotation(self):
        with self.assertRaises(ValidationError):
            ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)

    def test_convert_approved_quotation_copies_data_and_locks_quotation(self):
        self.quotation.submit(user=self.rep)
        self.quotation.approve(user=self.rep)

        pi = ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)

        self.assertTrue(pi.pi_number.startswith("PI-"))
        self.assertEqual(pi.client_id, self.quotation.client_id)
        self.assertEqual(pi.items.count(), 2)
        self.assertEqual(pi.subtotal, Decimal("4500.00"))
        self.assertEqual(pi.vat_total, Decimal("585.00"))
        self.assertEqual(pi.grand_total, Decimal("5085.00"))

        self.quotation.refresh_from_db()
        self.assertEqual(self.quotation.status, Quotation.Status.CONVERTED)
        self.assertTrue(self.quotation.is_locked)

    def test_cannot_convert_same_quotation_twice(self):
        self.quotation.submit(user=self.rep)
        self.quotation.approve(user=self.rep)
        ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)
        with self.assertRaises(ValidationError):
            ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)

    def test_editing_pi_does_not_modify_quotation(self):
        self.quotation.submit(user=self.rep)
        self.quotation.approve(user=self.rep)
        pi = ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)

        original_qty = self.quotation.items.first().quantity
        line = pi.items.first()
        line.quantity = Decimal("99")
        line.save()

        self.quotation.refresh_from_db()
        self.assertEqual(self.quotation.items.first().quantity, original_qty)

    def test_pi_workflow(self):
        self.quotation.submit(user=self.rep)
        self.quotation.approve(user=self.rep)
        pi = ProformaInvoice.create_from_quotation(self.quotation, user=self.rep)

        pi.submit(user=self.rep)
        self.assertEqual(pi.status, ProformaInvoice.Status.SUBMITTED)
        pi.approve(user=self.rep)
        self.assertEqual(pi.status, ProformaInvoice.Status.APPROVED)

        pi.mark_converted(user=self.rep)
        self.assertEqual(pi.status, ProformaInvoice.Status.CONVERTED)
        self.assertTrue(pi.is_locked)
        with self.assertRaises(ValidationError):
            pi.submit(user=self.rep)


class ProformaViewTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)

        perms = Permission.objects.filter(content_type__app_label__in=["quotations", "proforma"])
        self.manager_group = Group.objects.create(name="Sales Manager")
        self.manager_group.permissions.add(*perms)
        self.manager = User.objects.create_user(username="mgr1", password="pass1234")
        self.manager.groups.add(self.manager_group)

        self.rep_group = Group.objects.create(name="Sales Representative")
        self.rep_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="quotations", codename__in=["view_quotation"],
        ))
        self.rep = User.objects.create_user(username="rep1", password="pass1234")
        self.rep.groups.add(self.rep_group)

        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms,
            sales_representative=self.manager,
        )
        self.quotation = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.manager,
        )
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("100"))

    def test_rep_without_permission_cannot_convert(self):
        self.quotation.submit(user=self.manager)
        self.quotation.approve(user=self.manager)
        self.client.login(username="rep1", password="pass1234")
        resp = self.client.post(reverse("proforma:create_from_quotation", args=[self.quotation.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_manager_can_convert_via_view(self):
        self.quotation.submit(user=self.manager)
        self.quotation.approve(user=self.manager)
        self.client.login(username="mgr1", password="pass1234")
        resp = self.client.post(reverse("proforma:create_from_quotation", args=[self.quotation.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ProformaInvoice.objects.count(), 1)

    def test_convert_draft_quotation_via_view_fails_gracefully(self):
        self.client.login(username="mgr1", password="pass1234")
        resp = self.client.post(reverse("proforma:create_from_quotation", args=[self.quotation.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ProformaInvoice.objects.count(), 0)

    def test_pdf_download(self):
        self.quotation.submit(user=self.manager)
        self.quotation.approve(user=self.manager)
        pi = ProformaInvoice.create_from_quotation(self.quotation, user=self.manager)
        self.client.login(username="mgr1", password="pass1234")
        resp = self.client.get(reverse("proforma:pdf", args=[pi.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
