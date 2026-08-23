from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from masters.models import Client, Currency, PaymentTerm
from .models import Quotation, QuotationItem

User = get_user_model()


class QuotationModelTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)
        self.rep = User.objects.create_user(username="rep1", password="x")
        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )

    def _make_quotation(self):
        return Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )

    def test_quotation_number_auto_generated(self):
        q1 = self._make_quotation()
        q2 = self._make_quotation()
        self.assertTrue(q1.quotation_number.startswith("QT-"))
        self.assertNotEqual(q1.quotation_number, q2.quotation_number)

    def test_line_item_vat_and_totals(self):
        q = self._make_quotation()
        QuotationItem.objects.create(
            quotation=q, description="Freight Cost", quantity=1,
            unit_price=Decimal("2500.00"), vat_percentage=Decimal("13.00"),
        )
        QuotationItem.objects.create(
            quotation=q, description="Clearance fee", quantity=2,
            unit_price=Decimal("1000.00"), vat_percentage=Decimal("13.00"),
        )
        q.refresh_from_db()
        self.assertEqual(q.subtotal, Decimal("4500.00"))
        self.assertEqual(q.vat_total, Decimal("585.00"))
        self.assertEqual(q.grand_total, Decimal("5085.00"))

    def test_cannot_submit_without_items(self):
        q = self._make_quotation()
        with self.assertRaises(ValidationError):
            q.submit(user=self.rep)

    def test_full_workflow_locks_after_conversion(self):
        q = self._make_quotation()
        QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))
        q.submit(user=self.rep)
        self.assertEqual(q.status, Quotation.Status.SUBMITTED)
        self.assertTrue(q.is_editable is False)

        q.approve(user=self.rep)
        self.assertEqual(q.status, Quotation.Status.APPROVED)

        q.mark_converted(user=self.rep)
        self.assertEqual(q.status, Quotation.Status.CONVERTED)
        self.assertTrue(q.is_locked)

        with self.assertRaises(ValidationError):
            q.submit(user=self.rep)

    def test_cannot_approve_a_draft_directly(self):
        q = self._make_quotation()
        QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))
        with self.assertRaises(ValidationError):
            q.approve(user=self.rep)

    def test_reject_and_revert_to_draft(self):
        q = self._make_quotation()
        QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))
        q.submit(user=self.rep)
        q.reject(user=self.rep)
        self.assertEqual(q.status, Quotation.Status.REJECTED)
        q.revert_to_draft(user=self.rep)
        self.assertEqual(q.status, Quotation.Status.DRAFT)
        self.assertTrue(q.is_editable)

    def test_populate_from_client(self):
        q = Quotation(client=self.client_obj)
        q.populate_from_client()
        self.assertEqual(q.currency_id, self.usd.id)
        self.assertEqual(q.payment_terms_id, self.terms.id)
        self.assertEqual(q.sales_representative_id, self.rep.id)

    def test_deleting_line_item_recalculates_totals(self):
        q = self._make_quotation()
        item = QuotationItem.objects.create(quotation=q, description="Freight", quantity=1, unit_price=Decimal("100"))
        q.refresh_from_db()
        self.assertEqual(q.subtotal, Decimal("100.00"))
        item.delete()
        q.refresh_from_db()
        self.assertEqual(q.subtotal, Decimal("0.00"))


class QuotationViewTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(name="US Dollar", code="USD", symbol="$", exchange_rate=1)
        self.terms = PaymentTerm.objects.create(name="30 Days", days=30)

        self.rep_group = Group.objects.create(name="Sales Representative")
        self.rep_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="quotations",
            codename__in=["add_quotation", "change_quotation", "view_quotation", "submit_quotation"],
        ))
        self.rep = User.objects.create_user(username="rep1", password="pass1234")
        self.rep.groups.add(self.rep_group)

        self.other_rep = User.objects.create_user(username="rep2", password="pass1234")
        self.other_rep.groups.add(self.rep_group)

        self.manager_group = Group.objects.create(name="Sales Manager")
        self.manager_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="quotations",
        ))
        self.manager = User.objects.create_user(username="mgr1", password="pass1234")
        self.manager.groups.add(self.manager_group)

        self.client_obj = Client.objects.create(
            company_name="Acme Ltd", currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )
        self.quotation = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.rep,
        )
        QuotationItem.objects.create(quotation=self.quotation, description="Freight", quantity=1, unit_price=Decimal("100"))

    def test_list_requires_login(self):
        resp = self.client.get(reverse("quotations:list"))
        self.assertEqual(resp.status_code, 302)

    def test_sales_rep_sees_only_own_quotations(self):
        other_quotation = Quotation.objects.create(
            client=self.client_obj, currency=self.usd, payment_terms=self.terms,
            sales_representative=self.other_rep,
        )
        self.client.login(username="rep1", password="pass1234")
        resp = self.client.get(reverse("quotations:list"))
        qs = list(resp.context["quotations"])
        self.assertIn(self.quotation, qs)
        self.assertNotIn(other_quotation, qs)

    def test_manager_sees_all_quotations(self):
        self.client.login(username="mgr1", password="pass1234")
        resp = self.client.get(reverse("quotations:list"))
        self.assertEqual(len(resp.context["quotations"]), 1)

    def test_submit_transition_via_view(self):
        self.client.login(username="rep1", password="pass1234")
        resp = self.client.post(reverse("quotations:submit", args=[self.quotation.pk]))
        self.quotation.refresh_from_db()
        self.assertEqual(self.quotation.status, Quotation.Status.SUBMITTED)
        self.assertEqual(resp.status_code, 302)

    def test_rep_cannot_approve(self):
        self.quotation.submit(user=self.rep)
        self.client.login(username="rep1", password="pass1234")
        resp = self.client.post(reverse("quotations:approve", args=[self.quotation.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_pdf_download(self):
        self.client.login(username="rep1", password="pass1234")
        resp = self.client.get(reverse("quotations:pdf", args=[self.quotation.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
